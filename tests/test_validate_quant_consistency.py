"""Offline validation tests using synthetic records, never actual B/C evidence.

The calendar below is a sequence of consecutive dates for parser tests only;
it is deliberately not represented as a real exchange trading calendar.
"""

import copy
import json
import re
import sys
from datetime import date, timedelta
from types import ModuleType, SimpleNamespace

import pytest

from scripts import validate_quant_consistency as runner


INDICATORS = (
    "ma5", "ma10", "ma20", "ma60", "macd", "macd_signal", "macd_hist",
    "rsi14", "boll_upper", "boll_middle", "boll_lower",
)


def synthetic_records(count=60):
    """Small, legal numeric examples; these are not market observations."""
    start = date(2024, 1, 1)
    return [
        {
            "stock_code": "600519",
            "trade_date": (start + timedelta(days=index)).isoformat(),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1000 + index,
            "amount": 100500.0,
            "turnover_rate": 0.01,
            "change_pct": 0.005,
        }
        for index in range(count)
    ]


def write_json(path, value):
    path.write_text(json.dumps(value, allow_nan=False), encoding="utf-8")


@pytest.fixture
def synthetic_legacy_package(tmp_path):
    records = synthetic_records(403)
    records[0]["open"] = 100.123456
    canonical = runner.canonicalize_records(records)
    paths = {
        "kline": tmp_path / "synthetic_kline.json",
        "calendar": tmp_path / "synthetic_calendar.json",
        "readback": tmp_path / "synthetic_export.json",
    }
    write_json(paths["kline"], records)
    write_json(paths["calendar"], [row["trade_date"] for row in records])
    write_json(paths["readback"], canonical)
    metadata = {
        "reviewed_commit": "synthetic-unit-test-only",
        "kline": {
            "file": paths["kline"].name,
            "sha256": runner.sha256(paths["kline"]),
            "stock_code": "600519",
            "adjust": "qfq",
            "period": "daily",
            "rows": 403,
            "actual_start_date": records[0]["trade_date"],
            "actual_end_date": records[-1]["trade_date"],
            "fetch_finished_at_utc": "2024-01-01T00:00:00+00:00",
            "data_kind": "synthetic_unit_test",
        },
        "calendar": {
            "file": paths["calendar"].name,
            "sha256": runner.sha256(paths["calendar"]),
            "data_kind": "synthetic_unit_test",
        },
        "notes": ["Synthetic parser fixture; no MySQL or live-source evidence."],
    }
    metadata_path = tmp_path / "metadata.json"
    write_json(metadata_path, metadata)
    return SimpleNamespace(
        root=tmp_path, paths=paths, metadata=metadata, metadata_path=metadata_path,
        records=records, canonical=canonical,
        readback_sha=runner.sha256(paths["readback"]),
    )


def load_synthetic(package, **kwargs):
    return runner.load_inputs(
        package.root, package.metadata_path, package.paths["readback"],
        package.readback_sha, **kwargs,
    )


@pytest.mark.parametrize("text", [
    '{"rows": 1, "rows": 2}',
    '{"kline": {"sha256": "a", "sha256": "b"}}',
    '[{"close": 1, "close": 2}]',
])
def test_strict_json_rejects_duplicate_keys_at_any_depth(tmp_path, text):
    path = tmp_path / "duplicate.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON key"):
        runner.strict_json(path)


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity", "1e999", "-1e999"])
@pytest.mark.parametrize("template", ["{}", '{{"nested": [{}]}}'])
def test_strict_json_rejects_nonfinite_literals_and_exponent_overflow(tmp_path, token, template):
    path = tmp_path / "nonfinite.json"
    path.write_text(template.format(token), encoding="utf-8")
    with pytest.raises(ValueError, match="non-finite|finite"):
        runner.strict_json(path)


def test_strict_json_accepts_bom_null_and_finite_exponents(tmp_path):
    path = tmp_path / "valid.json"
    path.write_text('{"values": [null, 1e3, -2.5, true]}', encoding="utf-8-sig")
    assert runner.strict_json(path) == {"values": [None, 1000.0, -2.5, True]}


def test_validate_records_accepts_legal_values_and_optional_nulls():
    records = synthetic_records()
    for field in ("amount", "turnover_rate", "change_pct"):
        records[0][field] = None
    dates = runner.validate_records(records, canonical=True, expected_rows=60)
    assert dates == [date.fromisoformat(row["trade_date"]) for row in records]


@pytest.mark.parametrize("case", ["duplicate", "reversed", "middle_swap"])
def test_validate_records_rejects_duplicate_or_unsorted_dates(case):
    records = synthetic_records()
    if case == "duplicate":
        records[31]["trade_date"] = records[30]["trade_date"]
    elif case == "reversed":
        records.reverse()
    else:
        records[30], records[31] = records[31], records[30]
    original = copy.deepcopy(records)
    with pytest.raises(ValueError, match="unique and strictly increasing"):
        runner.validate_records(records, expected_rows=60)
    assert records == original


@pytest.mark.parametrize("value", ["2024-1-01", "2024-01-01T00:00:00", "2024-02-30", 20240101])
def test_validate_records_rejects_non_iso_or_impossible_dates(value):
    records = synthetic_records()
    records[0]["trade_date"] = value
    with pytest.raises(ValueError):
        runner.validate_records(records, expected_rows=60)


@pytest.mark.parametrize("field,value", [
    ("open", "100.0"), ("amount", "100500"), ("volume", "1000"),
    ("close", True), ("volume", False), ("change_pct", True),
    ("volume", None), ("open", None), ("volume", 1000.5), ("volume", 1000.0),
    ("volume", -1), ("close", float("nan")), ("amount", float("inf")),
])
def test_validate_records_rejects_coercible_or_invalid_numbers(field, value):
    records = synthetic_records()
    records[7][field] = value
    with pytest.raises(ValueError, match=re.escape(f"data[7].{field}")):
        runner.validate_records(records, expected_rows=60)


@pytest.mark.parametrize("field", ["open", "high", "low", "close"])
def test_validate_records_rejects_zero_ohlc(field):
    records = synthetic_records()
    records[5][field] = 0
    with pytest.raises(ValueError, match=r"data\[5\]: invalid OHLC"):
        runner.validate_records(records, expected_rows=60)


@pytest.mark.parametrize("field,value", [
    ("open", 100.00001), ("high", 101.00001), ("low", 99.00001),
    ("close", 100.50001), ("amount", 100500.001),
    ("turnover_rate", 0.0100001), ("change_pct", 0.0050001),
])
def test_validate_records_rejects_noncanonical_received_precision(field, value):
    records = synthetic_records()
    records[3][field] = value
    runner.validate_records(records, canonical=False, expected_rows=60)
    with pytest.raises(ValueError, match=re.escape(f"data[3].{field}: violates canonical precision")):
        runner.validate_records(records, canonical=True, expected_rows=60)


def test_canonicalize_records_preserves_input_and_rounds_only_contract_fields():
    source = synthetic_records()
    source[0].update(open=100.123456, amount=100500.126,
                     turnover_rate=0.01234567, change_pct=None)
    before = copy.deepcopy(source)
    canonical = runner.canonicalize_records(source)
    assert source == before
    assert canonical is not source
    assert all(left is not right for left, right in zip(source, canonical))
    assert canonical[0] == {
        **before[0], "open": 100.1235, "amount": 100500.13, "turnover_rate": 0.012346,
    }
    canonical[0]["volume"] = 0
    assert source == before


@pytest.mark.parametrize("field", INDICATORS)
@pytest.mark.parametrize("initial", [None, 1.0], ids=["warmup-null", "computed-value"])
def test_assert_equal_detects_every_indicator_and_null_at_deep_path(field, initial):
    expected = {"series": {"indicators": [{}, {field: initial}]}}
    actual = copy.deepcopy(expected)
    actual["series"]["indicators"][1][field] = 2.0
    path = f"result.series.indicators[1].{field}"
    with pytest.raises(ValueError, match=re.escape(path)):
        runner.assert_equal(expected, actual)


@pytest.mark.parametrize("field,initial,replacement", [
    ("order_id", 2, 3), ("signal_date", "2024-01-01", "2024-01-02"),
    ("execution_date", "2024-01-02", "2024-01-03"), ("side", "buy", "sell"),
    ("execution_price", 100.0, 101.0), ("shares", 10.0, 11.0),
    ("gross_amount", 1000.0, 1001.0), ("fee", 1.0, 2.0),
    ("cash_after", 9000.0, 9001.0), ("position_after", 1, 0),
    ("round_trip_pnl", None, 0.0), ("round_trip_return", None, 0.0),
])
def test_assert_equal_detects_order_fields_including_null_pnl(field, initial, replacement):
    expected = {"backtest": {"trades": [{}, {field: initial}]}}
    actual = copy.deepcopy(expected)
    actual["backtest"]["trades"][1][field] = replacement
    with pytest.raises(ValueError, match=re.escape(f"result.backtest.trades[1].{field}")):
        runner.assert_equal(expected, actual)


@pytest.mark.parametrize("container", ["series", "backtest"])
@pytest.mark.parametrize("curve,field", [
    ("equity_curve", "equity"), ("benchmark_curve", "benchmark_equity"),
    ("drawdown_curve", "drawdown"),
])
def test_assert_equal_detects_all_curve_values_at_deep_path(container, curve, field):
    expected = {container: {curve: [{field: 1.0}, {field: 2.0}]}}
    actual = copy.deepcopy(expected)
    actual[container][curve][1][field] += 0.000000001
    with pytest.raises(ValueError, match=re.escape(f"result.{container}.{curve}[1].{field}")):
        runner.assert_equal(expected, actual)


@pytest.mark.parametrize("expected,actual,path", [
    ({"series": {"indicators": []}}, {"series": {}}, "result.series"),
    ({"trades": [{}, {}]}, {"trades": [{}]}, "result.trades"),
    ({"parameters": {"allow_fractional_shares": True}},
     {"parameters": {"allow_fractional_shares": 1}}, "result.parameters.allow_fractional_shares"),
    ({"score": 1}, {"score": True}, "result.score"),
    ({"null": None}, {"null": 0}, "result.null"),
])
def test_assert_equal_rejects_missing_keys_lengths_and_boolean_numeric_aliases(expected, actual, path):
    with pytest.raises(ValueError, match=re.escape(path)):
        runner.assert_equal(expected, actual)


def test_load_inputs_accepts_synthetic_legacy_quant_only_files_without_mutation(synthetic_legacy_package):
    package = synthetic_legacy_package
    before = {key: path.read_bytes() for key, path in package.paths.items()}
    inputs = load_synthetic(package)
    assert inputs["source"] == package.records
    assert inputs["received"] == package.canonical
    assert inputs["canonical"] == package.canonical
    assert inputs["provenance"] == package.metadata
    assert inputs["hashes"]["mysql_export"] == package.readback_sha
    assert before == {key: path.read_bytes() for key, path in package.paths.items()}


@pytest.mark.parametrize("kind", ["kline", "calendar", "readback"])
def test_load_inputs_rejects_hash_mismatch_before_validation_or_service(synthetic_legacy_package, monkeypatch, kind):
    package = synthetic_legacy_package
    if kind == "readback":
        package.readback_sha = "0" * 64
    else:
        package.metadata[kind]["sha256"] = "0" * 64
        write_json(package.metadata_path, package.metadata)

    def forbidden(*args, **kwargs):
        pytest.fail("a bad input hash must fail before record validation, quant, or service execution")

    monkeypatch.setattr(runner, "validate_records", forbidden)
    monkeypatch.setattr(runner, "analyze_quant_dataframe", forbidden)
    service_module = ModuleType("scripts.quant_consistency_regression")
    service_module.run_sqlite_regression = forbidden
    monkeypatch.setitem(sys.modules, service_module.__name__, service_module)
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        load_synthetic(package)
    assert runner.main([
        "--source-dir", str(package.root), "--readback", str(package.paths["readback"]),
        "--readback-sha256", package.readback_sha,
    ]) == 1


def test_load_inputs_cannot_reround_noncanonical_readback_to_hide_difference(synthetic_legacy_package, monkeypatch):
    package = synthetic_legacy_package
    # This altered export would match again if somebody rounded it to four places.
    received = copy.deepcopy(package.canonical)
    received[0]["open"] += 0.000001
    assert round(received[0]["open"], 4) == package.canonical[0]["open"]
    write_json(package.paths["readback"], received)
    package.readback_sha = runner.sha256(package.paths["readback"])

    def forbidden(*args, **kwargs):
        pytest.fail("received export must fail precision validation before any canonicalization")

    monkeypatch.setattr(runner, "canonicalize_records", forbidden)
    with pytest.raises(ValueError, match=r"mysql_export\[0\].open: violates canonical precision"):
        load_synthetic(package)


def test_load_inputs_cannot_hide_canonical_but_different_readback(synthetic_legacy_package):
    package = synthetic_legacy_package
    received = copy.deepcopy(package.canonical)
    received[50]["volume"] += 1
    write_json(package.paths["readback"], received)
    package.readback_sha = runner.sha256(package.paths["readback"])
    with pytest.raises(ValueError, match=re.escape("canonical_source_vs_mysql_export[50].volume")):
        load_synthetic(package)


def test_incomplete_legacy_manifest_is_rejected_by_actual_d_full_bundle_loader(synthetic_legacy_package):
    from scripts.frozen_acceptance import FrozenAcceptanceError

    with pytest.raises(FrozenAcceptanceError, match="missing required fields"):
        load_synthetic(synthetic_legacy_package, full_package=True)


def test_full_bundle_cli_returns_failure_for_legacy_manifest_without_service(synthetic_legacy_package, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("incomplete bundle must fail before quant or service execution")

    monkeypatch.setattr(runner, "analyze_quant_dataframe", forbidden)
    assert runner.main(["--frozen-dir", str(synthetic_legacy_package.root)]) == 1
    output = capsys.readouterr()
    assert "FAIL" in output.err
    assert "PASS_SCOPED" not in output.out


def test_legacy_mode_report_never_claims_d_bundle_or_live_mysql_acceptance(synthetic_legacy_package, monkeypatch, capsys):
    # Stub the expensive work to examine reporting scope, not to assert that these
    # synthetic prices produce the known real-sample score or backtest numbers.
    analysis = {
        "score": {"score": runner.EXPECTED["score"]},
        "backtest": {
            "order_count": runner.EXPECTED["order_count"],
            "equity_curve": [None] * runner.EXPECTED["equity_curve_points"],
            "total_return": runner.EXPECTED["total_return"],
            "final_equity": runner.EXPECTED["final_equity"],
        },
        "series": {"indicators": [{"ma5": None}]},
    }
    monkeypatch.setattr(runner, "analyze_quant_dataframe", lambda *args: copy.deepcopy(analysis))
    monkeypatch.setattr(runner, "code_identity", lambda: {"head": "synthetic-report-test"})
    monkeypatch.setattr(runner, "version", lambda name: "test-version")
    service_module = ModuleType("scripts.quant_consistency_regression")
    service_module.run_sqlite_regression = lambda *args: {
        "status": "PASS", "database_engine": "sqlite", "connected_to_mysql": False,
        "direct_analysis": copy.deepcopy(analysis),
    }
    monkeypatch.setitem(sys.modules, service_module.__name__, service_module)
    package = synthetic_legacy_package
    assert runner.main([
        "--source-dir", str(package.root), "--readback", str(package.paths["readback"]),
        "--readback-sha256", package.readback_sha,
    ]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "PASS_SCOPED"
    assert report["bundle_complete"] is False
    assert report["b_export_comparison"]["connected_to_mysql"] is False
    assert report["sqlite_service_and_http_regression"]["database_engine"] == "sqlite"
    assert any("D full frozen package validation" in item for item in report["not_run"])
    assert any("live MySQL" in item for item in report["not_run"])
    assert any("real LLM" in item for item in report["not_run"])
