"""C's offline V1 regression: frozen inputs, B export, real B/D service wiring.

This command NEVER connects to MySQL, calls AKShare/LLM, or modifies input files.
SQLite service evidence and the independent comparison of a B-supplied MySQL
export are labelled separately; neither is a new live-MySQL acceptance run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import re
import subprocess
import sys
from datetime import date, datetime, timezone
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from backend.app.data.trading_calendar import TradingCalendarProvider
from backend.app.quant.config import QuantConfig
from backend.app.quant.pipeline import analyze_quant_dataframe
from backend.app.schemas.stock import DailyKlineSchema

B_REFERENCE = "35a048271d437281ed837ac94b437aac5302f332"
D_REFERENCE = "a097f9a58c457d0fe194a038d8ad1d49ef044337"
FIELDS = {
    "stock_code", "trade_date", "open", "high", "low", "close", "volume",
    "amount", "turnover_rate", "change_pct",
}
PRECISION = {"open": 4, "high": 4, "low": 4, "close": 4,
             "amount": 2, "turnover_rate": 6, "change_pct": 6}
EXPECTED = {"score": 33, "order_count": 24, "equity_curve_points": 403,
            "total_return": -0.09165774117956027,
            "final_equity": 90834.22588204397}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def strict_json(path: Path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def constant(value):
        raise ValueError(f"non-finite JSON constant: {value}")

    def number(value):
        parsed = float(value)
        require(math.isfinite(parsed), f"non-finite JSON number: {value}")
        return parsed

    return json.loads(path.read_text(encoding="utf-8-sig"),
                      object_pairs_hook=pairs, parse_constant=constant, parse_float=number)


def sha256(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_file(path: Path, expected: str):
    require(isinstance(expected, str) and re.fullmatch(r"[0-9a-fA-F]{64}", expected),
            f"invalid SHA-256 for {path.name}")
    require(sha256(path) == expected.lower(), f"SHA-256 mismatch: {path.name}")
    return strict_json(path)


def package_path(root: Path, name: str):
    path = (root / name).resolve()
    require(path.is_relative_to(root.resolve()), "file path escapes frozen directory")
    return path


def validate_records(records, *, canonical=False, expected_rows=403, label="data"):
    """Reject bad input BEFORE Pydantic/coercion/sorting can conceal a defect."""
    require(isinstance(records, list) and len(records) == expected_rows and len(records) >= 60,
            f"{label}: expected {expected_rows} rows (at least 60)")
    dates = []
    for i, row in enumerate(records):
        at = f"{label}[{i}]"
        require(isinstance(row, dict) and set(row) == FIELDS, f"{at}: unexpected fields")
        require(type(row["stock_code"]) is str and row["stock_code"] == "600519",
                f"{at}.stock_code: expected string 600519")
        value = row["trade_date"]
        require(isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value),
                f"{at}.trade_date: expected YYYY-MM-DD")
        dates.append(date.fromisoformat(value))
        for field in FIELDS - {"stock_code", "trade_date"}:
            value = row[field]
            if value is None and field in {"amount", "turnover_rate", "change_pct"}:
                continue
            require(type(value) in (int, float) and math.isfinite(value),
                    f"{at}.{field}: expected finite JSON number")
            if canonical and field in PRECISION:
                require(value == round(value, PRECISION[field]),
                        f"{at}.{field}: violates canonical precision")
        require(type(row["volume"]) is int and row["volume"] >= 0,
                f"{at}.volume: expected nonnegative integer")
        require(0 < row["low"] <= min(row["open"], row["close"])
                <= max(row["open"], row["close"]) <= row["high"], f"{at}: invalid OHLC")
    require(all(a < b for a, b in zip(dates, dates[1:])),
            f"{label}: dates must be unique and strictly increasing")
    return dates


def canonicalize_records(source):
    """Independent CONTRACT oracle, not B's rounding implementation.

    Only pre-storage input is rounded. NEVER apply this to received readback.
    """
    return [{key: round(value, PRECISION[key])
             if key in PRECISION and value is not None else value
             for key, value in row.items()} for row in source]


def assert_equal(expected, actual, path="result"):
    """Exact recursive comparison with the first differing JSON path."""
    if isinstance(expected, dict):
        require(isinstance(actual, dict) and expected.keys() == actual.keys(),
                f"{path}: object keys differ")
        for key in expected:
            assert_equal(expected[key], actual[key], f"{path}.{key}")
    elif isinstance(expected, list):
        require(isinstance(actual, list) and len(expected) == len(actual),
                f"{path}: array lengths differ")
        for i, (left, right) in enumerate(zip(expected, actual)):
            assert_equal(left, right, f"{path}[{i}]")
    else:
        require(expected == actual and isinstance(expected, bool) == isinstance(actual, bool),
                f"{path}: expected {expected!r}, received {actual!r}")


def load_inputs(root, metadata_path, readback_path=None, readback_sha=None, *, full_package=False):
    meta = strict_json(metadata_path)
    require(isinstance(meta, dict), "metadata must be an object")
    kmeta = meta["kline"]
    if full_package:
        # D owns this full-bundle contract. Do not fabricate absent stock/news.
        from scripts.frozen_acceptance import load_package
        load_package(root, str(metadata_path))
        declared = meta
        readback_path = package_path(root, meta["readback"]["file"])
        readback_sha = meta["readback"]["sha256"]
        captured = meta["captured_at"]
    else:
        declared = kmeta
        captured = kmeta["fetch_finished_at_utc"]
        require(readback_path is not None and readback_sha is not None,
                "quant-only mode requires received readback path AND B's SHA-256")
    require(declared.get("adjust", kmeta.get("adjust")) == "qfq",
            "metadata must explicitly declare qfq (cannot infer from prices)")
    require(declared.get("stock_code") == "600519", "metadata stock_code must be 600519")
    period = declared.get("period", kmeta.get("period", meta.get("quant_config", {}).get("frequency")))
    require(period == "daily", "metadata must declare daily period")
    captured_time = datetime.fromisoformat(captured.replace("Z", "+00:00"))
    require(captured_time.tzinfo is not None, "capture time must include a timezone")

    paths = {kind: package_path(root, meta[kind]["file"]) for kind in ("kline", "calendar")}
    records = checked_file(paths["kline"], kmeta["sha256"])
    calendar_raw = checked_file(paths["calendar"], meta["calendar"]["sha256"])
    received = checked_file(readback_path, readback_sha)
    dates = validate_records(records, label="source")
    received_dates = validate_records(received, canonical=True, label="mysql_export")
    require(declared["rows"] == len(records), "metadata row count mismatch")
    require(declared["actual_start_date"] == dates[0].isoformat()
            and declared["actual_end_date"] == dates[-1].isoformat(), "metadata window mismatch")
    require(isinstance(calendar_raw, list) and all(
                isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) for v in calendar_raw),
            "calendar must be an array of ISO dates")
    calendar_dates = [date.fromisoformat(value) for value in calendar_raw]
    require(all(a < b for a, b in zip(calendar_dates, calendar_dates[1:])),
            "calendar must be unique and increasing")
    require(calendar_dates and calendar_dates[0] <= dates[0] and calendar_dates[-1] >= dates[-1],
            "calendar does not cover the entire sample window")
    expected_dates = [day for day in calendar_dates if dates[0] <= day <= dates[-1]]
    assert_equal(expected_dates, dates, "calendar_vs_source_dates")
    assert_equal(dates, received_dates, "source_vs_export_dates")
    canonical = canonicalize_records(records)
    validate_records(canonical, canonical=True, label="canonical_source")
    assert_equal(canonical, received, "canonical_source_vs_mysql_export")
    return {
        "source": records, "canonical": canonical, "received": received,
        "calendar": TradingCalendarProvider(trade_dates=calendar_dates),
        "provenance": meta,
        "hashes": {"metadata": sha256(metadata_path), "kline": sha256(paths["kline"]),
                   "calendar": sha256(paths["calendar"]), "mysql_export": sha256(readback_path)},
    }


def code_identity():
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=ROOT).decode("utf-8").strip()
    head = git("rev-parse", "HEAD")
    for ref in (B_REFERENCE, D_REFERENCE):
        subprocess.run(["git", "merge-base", "--is-ancestor", ref, head], cwd=ROOT, check=True)
    return {"head": head, "b_reference": B_REFERENCE, "d_reference": D_REFERENCE,
            "working_tree_status": git("status", "--short"),
            "c_validation_files_sha256": {str(path.relative_to(ROOT)): sha256(path)
                for path in sorted((ROOT / "scripts").glob("*quant*consistency*.py"))}}


def run(args):
    full = args.frozen_dir is not None
    root = Path(args.frozen_dir or args.source_dir).resolve()
    metadata = Path(args.metadata).resolve() if args.metadata else root / "metadata.json"
    inputs = load_inputs(root, metadata,
                         Path(args.readback).resolve() if args.readback else None,
                         args.readback_sha256, full_package=full)
    config = QuantConfig()
    direct = analyze_quant_dataframe(pd.DataFrame(inputs["canonical"]), config)
    exported = analyze_quant_dataframe(pd.DataFrame(inputs["received"]), config)
    assert_equal(direct, exported, "direct_vs_mysql_export_analysis")
    observed = {"score": direct["score"]["score"], "order_count": direct["backtest"]["order_count"],
                "equity_curve_points": len(direct["backtest"]["equity_curve"]),
                "total_return": direct["backtest"]["total_return"],
                "final_equity": direct["backtest"]["final_equity"]}
    assert_equal(EXPECTED, observed, "frozen_600519_expectations")

    from scripts.quant_consistency_regression import run_sqlite_regression
    service = run_sqlite_regression(
        [DailyKlineSchema.model_validate(row) for row in inputs["source"]],
        [DailyKlineSchema.model_validate(row) for row in inputs["canonical"]], inputs["calendar"])
    assert_equal(direct, service.pop("direct_analysis"), "cli_vs_service_direct_analysis")
    report = {
        "status": "PASS_SCOPED", "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "offline_sqlite_http_and_b_export_comparison", "connected_to_mysql": False,
        "arguments": vars(args),
        "code": code_identity(), "hashes": inputs["hashes"],
        "versions": {"python": platform.python_version(), **{name: version(name) for name in
                     ("pandas", "numpy", "SQLAlchemy", "fastapi", "pydantic")}},
        "rows": len(inputs["canonical"]), "bundle_complete": full,
        "actual_window": {"start": inputs["canonical"][0]["trade_date"],
                          "end": inputs["canonical"][-1]["trade_date"]},
        "input_provenance": inputs["provenance"], "quant_config": config.to_parameters(),
        "canonical_precision": PRECISION, "comparison": "exact; no tolerance; export never re-rounded",
        "b_export_comparison": {"status": "PASS", "data_equal": True, "analysis_equal": True,
                                "connected_to_mysql": False},
        "sqlite_service_and_http_regression": service,
        "indicator_null_counts": {key: sum(row[key] is None for row in direct["series"]["indicators"])
                                  for key in direct["series"]["indicators"][0]},
        "not_run": ["new live MySQL first-query/cache/readback verification",
                    "live AKShare smoke", "real LLM / ai_analysis persistence / browser acceptance"],
        "limitations": ["qfq is attested by captured metadata, not inferred from OHLC values",
                        "B supplied the MySQL export; C verified bytes and calculations, not export provenance at a live server",
                        "This scoped PASS is not V1 delivery or merge approval"],
    }
    if not full:
        report["not_run"].append("D full frozen package validation: new stock snapshot/unified metadata not supplied")
    if args.output_dir:
        output = Path(args.output_dir).resolve()
        output.mkdir(parents=True, exist_ok=True)
        # Never overwrite evidence inputs or a previous run's output.
        for name in ("quant_consistency_report.json", "quant_direct_analysis.json"):
            require(not (output / name).exists(), f"output already exists: {name}; choose a new directory")
        (output / "quant_direct_analysis.json").write_text(
            json.dumps(direct, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        report["direct_analysis_sha256"] = sha256(output / "quant_direct_analysis.json")
        (output / "quant_consistency_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--source-dir", help="Legacy C quant-only snapshots; NOT D's complete bundle")
    group.add_argument("--frozen-dir", help="Complete B/D frozen bundle; uses D's loader first")
    parser.add_argument("--metadata")
    parser.add_argument("--readback", help="Actual B MySQL export (quant-only mode)")
    parser.add_argument("--readback-sha256", help="Hash independently received from B")
    parser.add_argument("--output-dir", help="New output directory; existing results are never replaced")
    args = parser.parse_args(argv)
    if args.frozen_dir and (args.readback or args.readback_sha256):
        parser.error("full-package mode must use the manifest's readback file/hash")
    try:
        return run(args)
    except (AssertionError, ValueError, RuntimeError, OSError, KeyError, TypeError,
            subprocess.CalledProcessError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
