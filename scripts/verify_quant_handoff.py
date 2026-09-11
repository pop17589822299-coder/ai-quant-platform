"""Read-only C delivery gate for B's immutable v1-frozen-package-r2.

Checks all eight extracted JSON assets, plus the original ZIP if supplied.
Never downloads, extracts, rewrites inputs, opens a database, or calls an LLM.
This verifies delivery, NOT full quant or end-to-end acceptance.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.quant.config import QuantConfig
from scripts.validate_quant_consistency import (
    EXPECTED, assert_equal, package_path, require, sha256, strict_json,
)

HANDOFF_PATH = ROOT / "docs" / "C_FROZEN_R2_HANDOFF.json"
RELEASE_TAG = "v1-frozen-package-r2"
DOWNLOAD_PREFIX = (
    "https://github.com/Lawera2601/ai-quant-platform/releases/download/"
    f"{RELEASE_TAG}/"
)
ASSET_NAMES = {
    "archive": "ai-quant-v1-frozen-package-r2.zip",
    "kline": "600519_qfq_20250101_20260831.json",
    "calendar": "a_share_trade_dates.json",
    "stock": "stock_basic_600519.json",
    "readback": "mysql_readback_600519.json",
    "metadata": "metadata.json",
    "manifest": "MANIFEST.json",
    "stock_raw": "stock_basic_600519.raw.json",
    "stock_provenance": "stock_basic_600519.provenance.json",
}


def read_handoff():
    """Trust the reviewed repository checklist, not downloaded self-reported hashes."""
    handoff = strict_json(HANDOFF_PATH)
    require(type(handoff["schema_version"]) is int and handoff["schema_version"] == 1,
            "unsupported C handoff schema")
    require(handoff["release_tag"] == RELEASE_TAG, "not the pinned R2 release")
    require(handoff["download_prefix"] == DOWNLOAD_PREFIX, "unexpected download prefix")
    assets = handoff["assets"]
    require(isinstance(assets, list) and len(assets) == len(ASSET_NAMES),
            "handoff must list all nine R2 assets")
    require({asset["kind"] for asset in assets} == set(ASSET_NAMES),
            "missing or duplicate handoff asset kind")
    for asset in assets:
        require(asset["file"] == ASSET_NAMES[asset["kind"]], "unexpected R2 asset filename")
        require(type(asset["bytes"]) is int and asset["bytes"] > 0, "invalid asset size")
        require(isinstance(asset["sha256"], str)
                and re.fullmatch(r"[0-9a-f]{64}", asset["sha256"]), "invalid asset SHA-256")
    assert_equal(QuantConfig().to_parameters(), handoff["quant_config"], "handoff.quant_config")
    assert_equal(EXPECTED, handoff["quant_expectations"], "handoff.quant_expectations")
    return handoff


def verify_quant_handoff(frozen_dir, archive=None):
    handoff = read_handoff()
    root = Path(frozen_dir).resolve()
    require(root.is_dir(), "frozen directory does not exist")
    verified = {}
    documents = {}
    # Validate EVERY byte hash before invoking D's parser or any other service.
    # Even changing data AND downloaded metadata/MANIFEST cannot bypass this pin.
    for asset in handoff["assets"]:
        kind = asset["kind"]
        if kind == "archive" and archive is None:
            continue
        path = Path(archive).resolve() if kind == "archive" else package_path(root, asset["file"])
        require(path.is_file(), f"missing R2 asset: {asset['file']}")
        digest = sha256(path)
        require(digest == asset["sha256"], f"SHA-256 mismatch: {asset['file']}")
        require(path.stat().st_size == asset["bytes"], f"size mismatch: {asset['file']}")
        verified[asset["file"]] = {
            "sha256": digest, "bytes": asset["bytes"],
            "download_url": handoff["download_prefix"] + asset["file"],
        }
        if kind != "archive":
            documents[kind] = path

    metadata = strict_json(documents["metadata"])
    for field, expected in handoff["sample"].items():
        assert_equal(expected, metadata[field], f"metadata.{field}")
    assert_equal(handoff["quant_config"], metadata["quant_config"], "metadata.quant_config")
    assert_equal(handoff["quant_expectations"], metadata["quant_expectations"],
                 "metadata.quant_expectations")
    for kind in ("kline", "calendar", "stock", "readback"):
        name = ASSET_NAMES[kind]
        require(metadata[kind]["file"] == name, f"metadata.{kind}.file mismatch")
        assert_equal(verified[name]["sha256"], metadata[kind]["sha256"], f"metadata.{kind}.sha256")
    manifest = strict_json(documents["manifest"])
    # B's manifest has six entries; C additionally pins provenance, manifest and ZIP.
    expected_manifest = {
        ASSET_NAMES[kind]: verified[ASSET_NAMES[kind]]["sha256"]
        for kind in ("kline", "calendar", "stock", "stock_raw", "readback", "metadata")
    }
    assert_equal(expected_manifest, manifest["files"], "MANIFEST.files")
    require(metadata["news"] is None and metadata["news_status"].startswith("absent"),
            "R2 has no news snapshot; do not claim real-news acceptance")

    from scripts.frozen_acceptance import load_package
    load_package(root, str(documents["metadata"]))
    return {
        "status": "PASS_DELIVERY_ONLY", "release_tag": handoff["release_tag"],
        "code_references": handoff["code_references"],
        "handoff_manifest_sha256": sha256(HANDOFF_PATH),
        "verified_asset_count": len(verified), "verified_assets": verified,
        "archive_status": "PASS" if archive is not None else "NOT_CHECKED (not supplied)",
        "d_load_package": "PASS", "rows": metadata["rows"],
        "quant_config": metadata["quant_config"],
        "expected_not_computed": metadata["quant_expectations"],
        "connected_to_mysql": False, "news_snapshot": "absent",
        "not_run": ["full quant consistency (use validate_quant_consistency.py)",
                    "live MySQL", "live AKShare", "real LLM / browser / ai_analysis persistence"],
        "merge_approval": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen-dir", required=True, help="Directory of extracted R2 JSON files")
    parser.add_argument("--archive", help="Optional original R2 ZIP; checked without extracting")
    args = parser.parse_args(argv)
    try:
        report = verify_quant_handoff(args.frozen_dir, args.archive)
    except (AssertionError, ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
