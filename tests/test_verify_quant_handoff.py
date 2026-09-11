"""Offline delivery-gate tests; all temp assets below are synthetic, not evidence.

D's loader is replaced ONLY for these small byte-integrity unit tests. Real R2
and the actual D loader are exercised separately by the documented CLI run.
"""

import copy
import json
from types import SimpleNamespace

import pytest

from scripts import frozen_acceptance
from scripts import validate_quant_consistency as quant
from scripts import verify_quant_handoff as gate


def write_json(path, value):
    path.write_text(json.dumps(value, allow_nan=False), encoding="utf-8")


@pytest.fixture
def synthetic_handoff(tmp_path, monkeypatch):
    handoff = copy.deepcopy(gate.read_handoff())
    package = tmp_path / "synthetic-package"
    package.mkdir()
    archive = tmp_path / gate.ASSET_NAMES["archive"]
    archive.write_bytes(b"synthetic unit fixture; not a real ZIP or market data")
    for kind in ("kline", "calendar", "stock", "readback", "stock_raw", "stock_provenance"):
        write_json(package / gate.ASSET_NAMES[kind], {"kind": kind, "synthetic": True})
    metadata = {
        **handoff["sample"],
        "quant_config": handoff["quant_config"],
        "quant_expectations": handoff["quant_expectations"],
        "news": None, "news_status": "absent (synthetic test)",
    }
    for kind in ("kline", "calendar", "stock", "readback"):
        name = gate.ASSET_NAMES[kind]
        metadata[kind] = {"file": name, "sha256": gate.sha256(package / name)}
    write_json(package / "metadata.json", metadata)
    manifest = {"files": {
        gate.ASSET_NAMES[kind]: gate.sha256(package / gate.ASSET_NAMES[kind])
        for kind in ("kline", "calendar", "stock", "stock_raw", "readback", "metadata")
    }}
    write_json(package / "MANIFEST.json", manifest)
    # Synthetic test trust anchor, NEVER used for release validation.
    for asset in handoff["assets"]:
        path = archive if asset["kind"] == "archive" else package / asset["file"]
        asset.update(sha256=gate.sha256(path), bytes=path.stat().st_size)
    pin_path = tmp_path / "synthetic-handoff.json"
    write_json(pin_path, handoff)
    monkeypatch.setattr(gate, "HANDOFF_PATH", pin_path)
    calls = []
    monkeypatch.setattr(frozen_acceptance, "load_package", lambda *args: calls.append(args))
    return SimpleNamespace(root=package, archive=archive, pins=handoff, pin_path=pin_path, calls=calls)


def test_reviewed_handoff_contains_complete_defaults_and_nine_distinct_assets():
    handoff = gate.read_handoff()
    assert len({item["file"] for item in handoff["assets"]}) == 9
    assert handoff["quant_config"] == quant.QuantConfig().to_parameters()
    assert handoff["quant_expectations"] == quant.EXPECTED
    assert handoff["code_references"]["b_delivery"] == "7157cf6abcdfba010bbbb164a460ccd9463e837f"
    assert handoff["sample"]["rows"] == 403
    assert handoff["acceptance_scope"]["merge_approval"] is False


@pytest.mark.parametrize("with_archive", [False, True])
def test_gate_is_read_only_and_labels_its_limited_scope(synthetic_handoff, with_archive):
    fixture = synthetic_handoff
    before = {path.name: path.read_bytes() for path in fixture.root.iterdir()}
    archive_before = fixture.archive.read_bytes()
    report = gate.verify_quant_handoff(fixture.root, fixture.archive if with_archive else None)
    assert report["status"] == "PASS_DELIVERY_ONLY"
    assert report["verified_asset_count"] == (9 if with_archive else 8)
    assert (report["archive_status"] == "PASS") == with_archive
    assert report["connected_to_mysql"] is False
    assert report["merge_approval"] is False
    assert report["news_snapshot"] == "absent"
    assert "expected_not_computed" in report
    assert any("full quant" in item for item in report["not_run"])
    assert len(fixture.calls) == 1
    assert before == {path.name: path.read_bytes() for path in fixture.root.iterdir()}
    assert archive_before == fixture.archive.read_bytes()


@pytest.mark.parametrize("kind", gate.ASSET_NAMES)
def test_all_nine_assets_are_pinned_before_d_loader(synthetic_handoff, kind):
    fixture = synthetic_handoff
    path = fixture.archive if kind == "archive" else fixture.root / gate.ASSET_NAMES[kind]
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        gate.verify_quant_handoff(fixture.root, fixture.archive)
    assert fixture.calls == []


@pytest.mark.parametrize("kind", [kind for kind in gate.ASSET_NAMES if kind != "archive"])
def test_missing_assets_are_not_silently_optional(synthetic_handoff, kind):
    fixture = synthetic_handoff
    (fixture.root / gate.ASSET_NAMES[kind]).unlink()
    with pytest.raises(ValueError, match="missing R2 asset"):
        gate.verify_quant_handoff(fixture.root)
    assert fixture.calls == []


def test_supplied_missing_archive_fails_instead_of_reporting_not_checked(synthetic_handoff):
    fixture = synthetic_handoff
    with pytest.raises(ValueError, match="missing R2 asset"):
        gate.verify_quant_handoff(fixture.root, fixture.root / "missing.zip")
    assert fixture.calls == []


def test_mutating_data_and_self_reported_hashes_cannot_replace_reviewed_pins(synthetic_handoff):
    fixture = synthetic_handoff
    name = gate.ASSET_NAMES["readback"]
    write_json(fixture.root / name, {"synthetic": "changed"})
    metadata = gate.strict_json(fixture.root / "metadata.json")
    metadata["readback"]["sha256"] = gate.sha256(fixture.root / name)
    write_json(fixture.root / "metadata.json", metadata)
    manifest = gate.strict_json(fixture.root / "MANIFEST.json")
    for asset in (name, "metadata.json"):
        manifest["files"][asset] = gate.sha256(fixture.root / asset)
    write_json(fixture.root / "MANIFEST.json", manifest)
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        gate.verify_quant_handoff(fixture.root)
    assert fixture.calls == []


@pytest.mark.parametrize("change,message", [
    ("empty", "all nine"), ("duplicate", "missing or duplicate"),
    ("filename", "unexpected R2 asset filename"), ("hash", "invalid asset SHA-256"),
    ("boolean_size", "invalid asset size"), ("version", "pinned R2"),
    ("prefix", "download prefix"), ("default_drift", "quant_config.initial_cash"),
])
def test_invalid_or_drifting_handoff_fails_closed(synthetic_handoff, change, message):
    fixture = synthetic_handoff
    pins = fixture.pins
    if change == "empty":
        pins["assets"] = []
    elif change == "duplicate":
        pins["assets"][-1] = copy.deepcopy(pins["assets"][0])
    elif change == "filename":
        pins["assets"][1]["file"] = "../outside.json"
    elif change == "hash":
        pins["assets"][1]["sha256"] = "invalid"
    elif change == "boolean_size":
        pins["assets"][1]["bytes"] = True
    elif change == "version":
        pins["release_tag"] = "v1-frozen-package-r3"
    elif change == "prefix":
        pins["download_prefix"] = "https://example.invalid/"
    elif change == "default_drift":
        pins["quant_config"]["initial_cash"] = 1
    write_json(fixture.pin_path, pins)
    with pytest.raises(ValueError, match=message):
        gate.verify_quant_handoff(fixture.root)
    assert fixture.calls == []


def test_gate_cli_returns_nonzero_without_pass_on_corruption(synthetic_handoff, capsys):
    fixture = synthetic_handoff
    (fixture.root / "MANIFEST.json").write_bytes(b"corrupt")
    assert gate.main(["--frozen-dir", str(fixture.root)]) == 1
    output = capsys.readouterr()
    assert "SHA-256 mismatch" in output.err
    assert "PASS" not in output.out
    assert fixture.calls == []


def test_main_regression_stops_before_quant_or_service_on_bad_handoff(synthetic_handoff, monkeypatch):
    fixture = synthetic_handoff
    (fixture.root / "stock_basic_600519.provenance.json").write_bytes(b"corrupt")

    def forbidden(*args, **kwargs):
        pytest.fail("bad R2 delivery must fail before load_inputs or quant/service execution")

    monkeypatch.setattr(quant, "load_inputs", forbidden)
    monkeypatch.setattr(quant, "analyze_quant_dataframe", forbidden)
    assert quant.main(["--frozen-dir", str(fixture.root), "--verify-r2-handoff"]) == 1
    assert fixture.calls == []


@pytest.mark.parametrize("args", [
    ["--source-dir", "unused", "--verify-r2-handoff"],
    ["--frozen-dir", "unused", "--verify-r2-handoff", "--metadata", "another.json"],
    ["--frozen-dir", "unused", "--archive", "unused.zip"],
])
def test_r2_cli_cannot_silently_check_a_different_metadata_or_legacy_mode(args):
    with pytest.raises(SystemExit) as error:
        quant.main(args)
    assert error.value.code == 2
