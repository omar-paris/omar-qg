import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_build():
    spec = importlib.util.spec_from_file_location("qg_candidate_build", ROOT / "scripts" / "build.py")
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def candidate_report(node_id: str = "oa-master") -> dict:
    return {
        "schema": "oa.hub-node-report/v1",
        "generated_at": "2026-07-26T12:00:00Z",
        "source": {"kind": "candidate_smoke", "mode": "candidate", "collector": "omar-hub"},
        "node": {"id": node_id, "label": "Candidate OA Master", "kind": "vps"},
        "status": "healthy",
        "maturity": {"score": 91, "level": "L3", "domains": []},
        "freshness": {"status": "fresh", "checked_at": "2026-07-26T12:00:00Z"},
        "hermes_version": {"current_version": "unknown", "upstream_status": "unknown", "gateway_status": {"status": "ok"}},
        "next_actions": [],
    }


def write_candidate_report(root: Path, payload: dict) -> Path:
    root.mkdir(parents=True)
    path = root / "oa-master.oa.hub-node-report.v1.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_default_hub_report_input_and_output_stay_production(monkeypatch):
    mod = load_build()
    monkeypatch.delenv("QG_HUB_NODE_REPORT_DIR", raising=False)
    monkeypatch.delenv("QG_BUILD_OUTPUT_DIR", raising=False)
    monkeypatch.delenv("QG_USE_TEST_FIXTURES", raising=False)

    assert mod.hub_node_report_dirs() == mod.HUB_NODE_REPORT_DIRS
    assert mod.build_output_dir() == mod.PUBLIC


def test_candidate_report_input_is_exclusive_even_with_test_fixtures(tmp_path, monkeypatch):
    mod = load_build()
    candidate_dir = tmp_path / "candidate-reports"
    write_candidate_report(candidate_dir, candidate_report())
    monkeypatch.setenv("QG_HUB_NODE_REPORT_DIR", str(candidate_dir))
    monkeypatch.setenv("QG_USE_TEST_FIXTURES", "1")

    reports = mod._read_hub_node_reports()

    assert set(reports) == {"oa-master"}
    assert reports["oa-master"]["maturity"]["score"] == 91
    assert reports["oa-master"]["_source_ref"] == "oa.hub-node-report/v1:oa-master:oa-master.oa.hub-node-report.v1.json"


def test_missing_or_invalid_candidate_reports_stay_unknown(tmp_path, monkeypatch):
    mod = load_build()
    candidate_dir = tmp_path / "candidate-reports"
    candidate_dir.mkdir()
    (candidate_dir / "oa-master.oa.hub-node-report.v1.json").write_text('{"schema":"wrong"}', encoding="utf-8")
    monkeypatch.setenv("QG_HUB_NODE_REPORT_DIR", str(candidate_dir))

    payload = mod.collect_hub_node_maturity("2026-07-26T12:00:00Z")

    assert payload["summary"]["reporting"] == 0
    assert payload["summary"]["unknown"] == len(mod.HUB_NODE_EXPECTED)
    assert all(node["report_status"] == "missing" for node in payload["nodes"])
    assert all(node["status"] == "unknown" for node in payload["nodes"])


def test_staging_output_dir_is_separate_from_production_public(tmp_path, monkeypatch):
    mod = load_build()
    staging_dir = tmp_path / "qg-staging-public"
    monkeypatch.setenv("QG_BUILD_OUTPUT_DIR", str(staging_dir))

    assert mod.build_output_dir() == staging_dir
    assert mod.build_output_dir() != mod.PUBLIC
