import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_build():
    spec = importlib.util.spec_from_file_location("qg_build", ROOT / "scripts" / "build.py")
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_inter_vps_collector_preserves_source_and_local_timestamps(tmp_path, monkeypatch):
    mod = load_build()
    inbox = tmp_path / "inter-vps-inbox"
    path = inbox / "pantheos" / "pantheos-health.v1.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema": "oa.vps-report/v1",
                "node": "pantheos",
                "generated_at": "2026-07-20T18:52:43+02:00",
                "source_report_generated_at": "2026-07-06T22:42:04+02:00",
                "health": {"status": "ok"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "INTER_VPS_REPORT_DIRS", [inbox])

    [report] = mod._read_inter_vps_reports()

    assert report["generated_at"] == "2026-07-06T22:42:04+02:00"
    assert report["source_report_generated_at"] == "2026-07-06T22:42:04+02:00"
    assert report["observed_at"] == "2026-07-20T18:52:43+02:00"
    assert report["normalized_at"] == "2026-07-20T18:52:43+02:00"
