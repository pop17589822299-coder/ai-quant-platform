"""Offline C/B/D consistency checks using a disposable SQLite database.

The caller supplies both provider rows and an independently normalized oracle.
Only the database, provider and calendar dependencies are replaced; D builds
the real application and the production services perform every calculation.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy import BIGINT, create_engine, delete
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.data.trading_calendar import TradingCalendarProvider
from backend.app.models.stock_daily import StockDaily
from backend.app.quant.pipeline import analyze_quant_dataframe
from backend.app.schemas.stock import DailyKlineSchema
from backend.app.services.market_data_service import MarketDataRepository, MarketDataService
from backend.app.services.stock_service import StockService


@compiles(BIGINT, "sqlite")
def _sqlite_bigint(type_, compiler, **kwargs):
    """SQLite rowid autoincrement requires INTEGER; MySQL stays unchanged."""
    return "INTEGER"


def _assert_equal(expected: Any, actual: Any, path: str) -> None:
    """Report the first differing field, including missing/extra nested keys."""
    if type(expected) is not type(actual):
        raise AssertionError(
            f"{path}: type {type(actual).__name__}, expected {type(expected).__name__}"
        )
    if isinstance(expected, dict):
        missing = expected.keys() - actual.keys()
        extra = actual.keys() - expected.keys()
        if missing or extra:
            raise AssertionError(f"{path}: missing={sorted(missing)}, extra={sorted(extra)}")
        for key in expected:
            _assert_equal(expected[key], actual[key], f"{path}.{key}")
    elif isinstance(expected, list):
        if len(expected) != len(actual):
            raise AssertionError(f"{path}: length {len(actual)}, expected {len(expected)}")
        for index, (left, right) in enumerate(zip(expected, actual)):
            _assert_equal(left, right, f"{path}[{index}]")
    elif expected != actual:
        raise AssertionError(f"{path}: got {actual!r}, expected {expected!r}")


def _json_rows(rows: List[DailyKlineSchema]) -> List[Dict[str, Any]]:
    return [row.model_dump(mode="json") for row in rows]


def _at_layer(path, operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except AssertionError:
        raise
    except Exception as exc:
        raise AssertionError(f"{path}: {type(exc).__name__}: {exc}") from exc


def _frame(rows: List[DailyKlineSchema]) -> pd.DataFrame:
    # Preserve optional nulls exactly at the Provider boundary. A float-typed
    # pandas column otherwise changes None into NaN before B sees the input.
    result = pd.DataFrame([row.model_dump() for row in rows])
    return result.astype(object).where(pd.notna(result), None)


class _OfflineProvider:
    def __init__(self, rows: List[DailyKlineSchema]) -> None:
        self.rows = rows
        self.calls: List[Dict[str, Any]] = []

    def get_daily_kline(self, stock_code, start_date, end_date, adjust="qfq"):
        self.calls.append({
            "stock_code": stock_code,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "adjust": adjust,
        })
        if adjust != "qfq":
            raise AssertionError(f"provider.adjust: got {adjust!r}, expected 'qfq'")
        return _frame([
            row for row in self.rows
            if row.stock_code == stock_code and start_date <= row.trade_date <= end_date
        ])

    def get_stock_info(self, *args, **kwargs):
        raise AssertionError("provider.stock_info: unexpected external-data path")

    def search_stocks(self, *args, **kwargs):
        raise AssertionError("provider.search: unexpected external-data path")

    def get_stock_news(self, *args, **kwargs):
        raise AssertionError("provider.news: unexpected external-data path")


def run_sqlite_regression(
    source_rows: List[DailyKlineSchema],
    canonical_rows: List[DailyKlineSchema],
    calendar: TradingCalendarProvider,
) -> Dict[str, Any]:
    """Assert strict full-result equality across direct C, B and D HTTP.

    No production session is opened. The caller must provide a calendar with
    explicit ``trade_dates``; an unloaded calendar is rejected before it could
    invoke an external fetch. Database tables and corruption tests exist only
    in this function's private ``sqlite://`` in-memory engine.
    """
    if len(canonical_rows) < 64:
        raise AssertionError("input.rows: at least 64 rows required for missing-row checks")
    if getattr(calendar, "_trade_dates", None) is None:
        raise AssertionError("input.calendar: explicit offline trade_dates are required")
    expected_rows = _json_rows(canonical_rows)
    try:
        json.dumps(_json_rows(source_rows), allow_nan=False)
        json.dumps(expected_rows, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise AssertionError(f"input.rows: non-JSON-safe numeric value ({exc})") from exc

    oracle = _at_layer("direct.analysis", analyze_quant_dataframe, _frame(canonical_rows))
    code = canonical_rows[0].stock_code
    start, end = canonical_rows[0].trade_date, canonical_rows[-1].trade_date
    _assert_equal(
        [(row.stock_code, row.trade_date) for row in canonical_rows],
        [(row.stock_code, row.trade_date) for row in source_rows],
        "input.source_keys",
    )
    _assert_equal(len(canonical_rows), calendar.count_between(start, end), "input.calendar.coverage")

    # The real D module constructs its global engine lazily with respect to
    # connections. Its get_db dependency is always overridden below, so this
    # harness never calls production SessionLocal or connects that engine.
    from backend.app.api.v1.dependencies import (
        get_data_provider, get_trading_calendar_provider,
    )
    from backend.app.db.session import get_db
    from backend.app.main import create_app

    provider = _OfflineProvider(source_rows)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    checks: Dict[str, Any] = {}
    provider_calls: Dict[str, int] = {"initial": 0}
    app = None

    def isolated_db():
        with Session(engine) as session:
            yield session

    def calls_at(stage: str, expected: int) -> None:
        provider_calls[stage] = len(provider.calls)
        _assert_equal(expected, len(provider.calls), f"{stage}.provider_calls")

    def validate_rows(rows: List[DailyKlineSchema], stage: str) -> None:
        _assert_equal(expected_rows, _json_rows(rows), f"{stage}.kline")
        actual = _at_layer(f"{stage}.analysis", analyze_quant_dataframe, _frame(rows))
        _assert_equal(oracle, actual, f"{stage}.analysis")
        checks[stage] = {"kline": True, "full_analysis": True, "rows": len(rows)}

    def query_b() -> List[DailyKlineSchema]:
        with Session(engine) as session:
            return MarketDataService(
                stock_service=StockService(provider=provider),
                repository=MarketDataRepository(session),
                trading_days=calendar.count_between,
            ).query_daily(code, start, end, min_rows=60, max_stale_days=3, max_gap_days=15)

    def read_repository() -> List[DailyKlineSchema]:
        with Session(engine) as session:
            return MarketDataRepository(session).list_daily(code, start, end)

    def http_check(client: TestClient, stage: str, expected_calls: int) -> None:
        params = {"start_date": start.isoformat(), "end_date": end.isoformat()}
        projections = {
            "kline": expected_rows,
            "indicators": oracle["series"]["indicators"],
            "score": oracle["score"],
            "backtests": {**oracle["backtest"], "stock_code": code},
        }
        for endpoint, expected in projections.items():
            if endpoint == "backtests":
                response = _at_layer(
                    f"{stage}.{endpoint}.request", client.post,
                    "/api/v1/backtests", json={"stock_code": code, **params},
                )
            else:
                response = _at_layer(
                    f"{stage}.{endpoint}.request", client.get,
                    f"/api/v1/stocks/{code}/{endpoint}", params=params,
                )
            _assert_equal(200, response.status_code, f"{stage}.{endpoint}.status")
            _assert_equal(
                {"code": 0, "message": "success", "data": expected},
                response.json(), f"{stage}.{endpoint}.response",
            )
            calls_at(f"{stage}.{endpoint}", expected_calls)
        checks[stage] = {endpoint: True for endpoint in projections}

    def delete_internal(indices: List[int], stage: str) -> None:
        dates = [canonical_rows[index].trade_date for index in indices]
        if min(indices) <= 0 or max(indices) >= len(canonical_rows) - 1:
            raise AssertionError(f"{stage}: deletion must preserve range endpoints")
        with Session(engine) as session:
            result = session.execute(delete(StockDaily).where(
                StockDaily.stock_code == code, StockDaily.trade_date.in_(dates),
            ))
            _assert_equal(len(indices), result.rowcount, f"{stage}.deleted_rows")
            session.commit()
        remaining = read_repository()
        _assert_equal(len(canonical_rows) - len(indices), len(remaining), f"{stage}.remaining_rows")
        if len(remaining) < 60:
            raise AssertionError(f"{stage}: partial cache must still contain at least 60 rows")
        largest_gap = max((b.trade_date - a.trade_date).days for a, b in zip(remaining, remaining[1:]))
        if largest_gap >= 15:
            raise AssertionError(f"{stage}.gap_days: {largest_gap}, expected < 15")
        checks[stage] = {
            "deleted_dates": [day.isoformat() for day in dates],
            "remaining_rows": len(remaining), "largest_gap_days": largest_gap,
            "endpoints_preserved": True,
        }

    try:
        StockDaily.__table__.create(engine)
        app = create_app()
        app.dependency_overrides[get_db] = isolated_db
        app.dependency_overrides[get_data_provider] = lambda: provider
        app.dependency_overrides[get_trading_calendar_provider] = lambda: calendar
        checks["direct"] = {"full_analysis": True, "rows": len(canonical_rows)}

        validate_rows(query_b(), "b_first")
        calls_at("b_first", 1)
        validate_rows(read_repository(), "repository_first_readback")
        calls_at("repository_first_readback", 1)
        validate_rows(query_b(), "b_cache")
        calls_at("b_cache", 1)

        with TestClient(app) as client:
            http_check(client, "d_http_cached", 1)

            middle = len(canonical_rows) // 2
            candidates = sorted(range(1, len(canonical_rows) - 2), key=lambda i: abs(i - middle))
            contiguous_start = next((i for i in candidates if (
                canonical_rows[i + 2].trade_date - canonical_rows[i - 1].trade_date
            ).days < 15), None)
            if contiguous_start is None:
                raise AssertionError("contiguous_partial_cache: no internal two-row gap below 15 days")
            delete_internal([contiguous_start, contiguous_start + 1], "contiguous_partial_cache")
            calls_at("contiguous_partial_cache", 1)
            # D's real kline endpoint must detect the incomplete B cache and
            # refill it; the remaining HTTP projections then reuse that fill.
            http_check(client, "d_http_contiguous_recovery", 2)
            validate_rows(read_repository(), "contiguous_repository_recovered")
            validate_rows(query_b(), "contiguous_cache_recovered")
            calls_at("contiguous_cache_recovered", 2)

            scattered = []
            for target in (len(canonical_rows) // 4, middle, len(canonical_rows) * 3 // 4):
                candidates = sorted(range(1, len(canonical_rows) - 1), key=lambda i: abs(i - target))
                chosen = next((i for i in candidates if (
                    all(abs(i - previous) > 1 for previous in scattered)
                    and (canonical_rows[i + 1].trade_date - canonical_rows[i - 1].trade_date).days < 15
                )), None)
                if chosen is None:
                    raise AssertionError("scattered_partial_cache: no separated internal row below 15 days")
                scattered.append(chosen)
            delete_internal(scattered, "scattered_partial_cache")
            calls_at("scattered_partial_cache", 2)
            validate_rows(query_b(), "scattered_b_recovered")
            calls_at("scattered_b_recovered", 3)
            validate_rows(read_repository(), "scattered_repository_recovered")
            validate_rows(query_b(), "scattered_cache_recovered")
            calls_at("scattered_cache_recovered", 3)
            http_check(client, "d_http_scattered_recovery", 3)

        expected_call = {
            "stock_code": code, "start_date": start.isoformat(),
            "end_date": end.isoformat(), "adjust": "qfq",
        }
        _assert_equal([expected_call] * 3, provider.calls, "provider.request_parameters")
        checks["provider_request_parameters"] = True
        backtest = oracle["backtest"]
        report = {
            "mode": "sqlite_service_regression",
            "database_engine": "sqlite",
            "connected_to_mysql": False,
            "checks": checks,
            "provider_calls": provider_calls,
            "summary": {
                "score": oracle["score"]["score"],
                "order_count": backtest["order_count"],
                "trade_count": backtest["trade_count"],
                "points": {name: len(points) for name, points in oracle["series"].items()},
                "total_return": backtest["total_return"],
                "final_equity": backtest["final_equity"],
                "max_drawdown": backtest["max_drawdown"],
                "sharpe_ratio": backtest["sharpe_ratio"],
            },
            "direct_analysis": oracle,
        }
        json.dumps(report, allow_nan=False)
        return report
    except AssertionError:
        raise
    except Exception as exc:
        raise AssertionError(f"regression.sqlite_runtime: {type(exc).__name__}: {exc}") from exc
    finally:
        if app is not None:
            app.dependency_overrides.clear()
        engine.dispose()
