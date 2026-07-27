import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_collector():
    spec = importlib.util.spec_from_file_location(
        "delivery_outcomes_under_test", ROOT / "scripts" / "delivery_outcomes.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def valid_outcome():
    return {
        "outcome_id": "outcome-qg-001",
        "project_id": "omar-qg",
        "title": "Outcome visible QG",
        "phase": "review",
        "status": "in_progress",
        "responsible_now": "h-athena",
        "updated_at": "2026-07-26T20:30:00Z",
        "next_gate": "Athena review",
        "feedbacks": [
            {
                "actor": "alex",
                "kind": "decision",
                "summary": "Validate the read model",
                "disposition": "accepted",
                "evidence_refs": ["PR#79"],
            }
        ],
        "delivery": {
            "decisions": [{"summary": "Contract accepted", "evidence_refs": ["decision:outcome-v1"]}],
            "implementation": [{"summary": "Collector added", "evidence_refs": ["PR#79"]}],
            "reviews": [{"summary": "Athena pending", "evidence_refs": ["gate:pending"]}],
            "tests": [{"summary": "pytest", "evidence_refs": ["tests:local"]}],
            "live_proofs": [{"summary": "Not deployed", "evidence_refs": []}],
        },
        "anomalies": [],
    }


def test_collect_valid_outcome_contract_and_public_redaction(tmp_path):
    mod = load_collector()
    source = tmp_path / "outcomes"
    source.mkdir()
    source.joinpath("001.json").write_text(json.dumps(valid_outcome()), encoding="utf-8")

    payload = mod.collect(source)

    assert payload["schema"] == "oa.delivery-outcomes/v1"
    assert payload["status"] == "ok"
    assert payload["summary"]["total"] == 1
    assert payload["items"][0]["outcome_id"] == "outcome-qg-001"
    assert payload["items"][0]["phase"] == "review"
    serialized = json.dumps(payload, ensure_ascii=False)
    for forbidden in ["/home/omar/", "Authorization:", "ghp_", "sk-", "BEGIN OPENSSH"]:
        assert forbidden not in serialized


def test_missing_or_invalid_sources_stay_unknown_with_bounded_errors(tmp_path):
    mod = load_collector()
    missing = mod.collect(tmp_path / "absent")
    assert missing["status"] == "unknown"
    assert missing["items"] == []
    assert missing["errors"] == ["source_missing"]

    source = tmp_path / "outcomes"
    source.mkdir()
    source.joinpath("bad.json").write_text('{"outcome_id":"x","phase":"invented"}', encoding="utf-8")
    invalid = mod.collect(source)
    assert invalid["status"] == "unknown"
    assert invalid["summary"]["unknown"] == 1
    assert invalid["items"][0]["phase"] == "unknown"
    assert len(invalid["errors"]) == 1
    assert invalid["errors"][0].startswith("invalid:bad.json:")


def test_delivery_outcomes_page_renders_feedback_and_unknown_state(tmp_path):
    mod = load_collector()
    source = tmp_path / "outcomes"
    source.mkdir()
    source.joinpath("001.json").write_text(json.dumps(valid_outcome()), encoding="utf-8")
    payload = mod.collect(source)

    build_spec = importlib.util.spec_from_file_location("qg_build_delivery_page", ROOT / "scripts" / "build.py")
    assert build_spec and build_spec.loader
    build = importlib.util.module_from_spec(build_spec)
    sys.modules[build_spec.name] = build
    build_spec.loader.exec_module(build)
    page = build.page_delivery_outcomes(payload)

    assert "Livraisons prouvées" in page
    assert "Outcome visible QG" in page
    assert "Alex · decision" in page
    assert "Athena review" in page
    assert "/api/delivery-outcomes.json" in page
    assert "unknown" in build.page_delivery_outcomes(mod.collect(tmp_path / "absent"))


def test_qg_build_emits_delivery_outcomes_api_and_route_from_fixture(tmp_path):
    source = tmp_path / "outcomes"
    source.mkdir()
    source.joinpath("001.json").write_text(json.dumps(valid_outcome()), encoding="utf-8")
    subprocess.run(
        ["python3", "scripts/build.py"],
        cwd=ROOT,
        check=True,
        env={
            **os.environ,
            "QG_USE_TEST_FIXTURES": "1",
            "OA_DELIVERY_OUTCOMES_SOURCE": str(source),
        },
    )
    payload = json.loads((ROOT / "public" / "api" / "delivery-outcomes.json").read_text(encoding="utf-8"))
    page = (ROOT / "public" / "livraisons" / "index.html").read_text(encoding="utf-8")
    assert payload["status"] == "ok"
    assert payload["items"][0]["outcome_id"] == "outcome-qg-001"
    assert "Outcome visible QG" in page
    assert "/api/delivery-outcomes.json" in page
