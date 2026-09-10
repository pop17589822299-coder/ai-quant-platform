"""Synthetic fixtures for C's offline full-result cross-layer regression."""

import json
import math

import pandas as pd
import pytest

from backend.app.data.trading_calendar import TradingCalendarProvider
from backend.app.schemas.stock import DailyKlineSchema
from backend.app.services.quant_service import QuantService
from backend.app.services.market_data_service import MarketDataService
from scripts.quant_consistency_regression import run_sqlite_regression


@pytest.fixture
def synthetic_input():
    """Weekday dates are synthetic test data, not an exchange calendar."""
    source = []
    canonical = []
    days = [day.date() for day in pd.bdate_range("2025-01-02", periods=140)]
    for index, day in enumerate(days):
        close = 100 + index * 0.02 + 5 * math.sin(index / 7)
        row = DailyKlineSchema(
            stock_code="000001", trade_date=day,
            open=close * 0.999, high=close * 1.01, low=close * 0.99, close=close,
            volume=100000 + index * 97, amount=close * (100000 + index * 97),
            turnover_rate=None if index % 7 == 0 else 0.012345678,
            change_pct=None if index == 0 else 0.001234567,
        )
        source.append(row)
        # Independent test oracle: never call B's private round helpers.
        fields = row.model_dump()
        for field in ("open", "high", "low", "close"):
            fields[field] = round(fields[field], 4)
        for field, digits in (("amount", 2), ("turnover_rate", 6), ("change_pct", 6)):
            if fields[field] is not None:
                fields[field] = round(fields[field], digits)
        canonical.append(DailyKlineSchema(**fields))
    return source, canonical, TradingCalendarProvider(trade_dates=days)


def test_full_c_b_d_regression_and_partial_cache_recovery(synthetic_input):
    result = run_sqlite_regression(*synthetic_input)
    assert result["mode"] == "sqlite_service_regression"
    assert result["database_engine"] == "sqlite"
    assert result["connected_to_mysql"] is False
    assert result["provider_calls"]["b_first"] == 1
    assert result["provider_calls"]["b_cache"] == 1
    assert result["provider_calls"]["d_http_cached.backtests"] == 1
    assert result["provider_calls"]["d_http_contiguous_recovery.kline"] == 2
    assert result["provider_calls"]["d_http_scattered_recovery.backtests"] == 3
    assert result["checks"]["contiguous_partial_cache"]["remaining_rows"] == 138
    assert result["checks"]["scattered_partial_cache"]["remaining_rows"] == 137
    assert result["summary"]["order_count"] > 0
    assert result["summary"]["points"]["indicators"] == 140
    assert result["direct_analysis"]["meta"]["stock_code"] == "000001"
    json.dumps(result, allow_nan=False)


def test_production_database_session_and_engine_are_never_used(synthetic_input, monkeypatch):
    from backend.app.db import session as production_db

    def forbidden(*args, **kwargs):
        raise AssertionError("production database must never be used")

    monkeypatch.setattr(production_db, "SessionLocal", forbidden)
    monkeypatch.setattr(production_db.engine, "connect", forbidden)
    result = run_sqlite_regression(*synthetic_input)
    assert result["provider_calls"]["d_http_scattered_recovery.backtests"] == 3


def test_wrong_http_nested_output_reports_exact_layer_and_path(synthetic_input, monkeypatch):
    original = QuantService.run_backtest

    def corrupted(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        result["equity_curve"][1]["equity"] += 0.00001
        return result

    monkeypatch.setattr(QuantService, "run_backtest", corrupted)
    with pytest.raises(AssertionError, match=r"d_http_cached.backtests.response.data.equity_curve\[1\].equity"):
        run_sqlite_regression(*synthetic_input)


def test_wrong_independent_precision_oracle_is_detected(synthetic_input):
    source, canonical, calendar = synthetic_input
    canonical[40] = canonical[40].model_copy(update={"amount": canonical[40].amount + 0.01})
    with pytest.raises(AssertionError, match=r"b_first.kline\[40\].amount"):
        run_sqlite_regression(source, canonical, calendar)


def test_row_count_only_cache_acceptance_is_detected(synthetic_input, monkeypatch):
    monkeypatch.setattr(
        MarketDataService, "_is_cache_complete",
        staticmethod(lambda cached, *args: len(cached) >= 60),
    )
    with pytest.raises(AssertionError, match=r"d_http_contiguous_recovery.kline.response.data: length"):
        run_sqlite_regression(*synthetic_input)


def test_missing_calendar_date_cannot_be_used_as_coverage(synthetic_input):
    source, canonical, calendar = synthetic_input
    partial = TradingCalendarProvider(trade_dates=calendar.get_trade_dates()[1:])
    with pytest.raises(AssertionError, match="input.calendar.coverage"):
        run_sqlite_regression(source, canonical, partial)


def test_unloaded_calendar_is_rejected_without_fetching(synthetic_input):
    source, canonical, _ = synthetic_input
    calls = []
    calendar = TradingCalendarProvider(fetch=lambda: calls.append("external") or [])
    with pytest.raises(AssertionError, match="input.calendar"):
        run_sqlite_regression(source, canonical, calendar)
    assert calls == []


def test_nonfinite_optional_value_is_rejected(synthetic_input):
    source, canonical, calendar = synthetic_input
    source[0] = source[0].model_copy(update={"change_pct": float("nan")})
    with pytest.raises(AssertionError, match="input.rows: non-JSON-safe"):
        run_sqlite_regression(source, canonical, calendar)


def test_too_few_rows_for_internal_gap_regression(synthetic_input):
    source, canonical, calendar = synthetic_input
    with pytest.raises(AssertionError, match="input.rows"):
        run_sqlite_regression(source[:60], canonical[:60], calendar)
