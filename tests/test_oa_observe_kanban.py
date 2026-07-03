import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_oa_observe():
    spec = importlib.util.spec_from_file_location("oa_observe", ROOT / "scripts/oa-observe.py")
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sample_finding():
    mod = load_oa_observe()
    return mod.Finding(
        "P1",
        "Kanban : 2 tâche(s) running > 6h",
        "Deux workers semblent bloqués depuis plus de 6h.",
        "VPS-Omar",
        "Lister les cartes et débloquer les workers.",
        "kanban_loop",
    )


def test_finding_json_exposes_stable_fingerprint_and_idempotency_key():
    mod = load_oa_observe()
    finding = sample_finding()

    payload = mod.structured_finding(finding)

    assert payload["schema"] == "oa.observe.finding/1"
    assert payload["fingerprint"] == mod.finding_fingerprint(finding)
    assert payload["idempotency_key"] == f"oa-observe:VPS-Omar:kanban_loop:{payload['fingerprint']}"
    assert payload["severite"] == "P1"


def test_kanban_dry_run_plans_create_then_update_without_duplicate():
    mod = load_oa_observe()
    finding = sample_finding()
    key = mod.finding_idempotency_key(finding)

    create_plan, state = mod.plan_kanban_sync([finding], previous={})
    assert create_plan[0]["action"] == "create"
    assert create_plan[0]["idempotency_key"] == key
    assert state[key]["status"] == "active"

    update_plan, state2 = mod.plan_kanban_sync([finding], previous=state)
    assert update_plan[0]["action"] == "update"
    assert update_plan[0]["idempotency_key"] == key
    assert state2[key]["last_seen_at"] >= state[key]["last_seen_at"]


def test_kanban_plan_resolves_disappeared_alert_with_comment_and_complete():
    mod = load_oa_observe()
    finding = sample_finding()
    key = mod.finding_idempotency_key(finding)
    previous = {
        key: {
            "status": "active",
            "task_id": "t_alert",
            "title": finding.titre,
            "last_seen_at": 1,
        }
    }

    plan, state = mod.plan_kanban_sync([], previous=previous, now_ts=2)

    assert plan == [{
        "action": "resolve",
        "idempotency_key": key,
        "task_id": "t_alert",
        "title": finding.titre,
    }]
    assert state[key]["status"] == "resolved"
    assert state[key]["resolved_at"] == 2


def test_cli_json_outputs_structured_findings_for_fixture(tmp_path):
    fixture = tmp_path / "findings.json"
    fixture.write_text(json.dumps({"findings": [mod_finding_dict()]}), encoding="utf-8")

    cp = subprocess.run(
        ["python3", "scripts/oa-observe.py", "--fixture", str(fixture), "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(cp.stdout)
    assert payload["schema"] == "oa.observe.scan/1"
    assert payload["findings"][0]["schema"] == "oa.observe.finding/1"
    assert payload["findings"][0]["idempotency_key"].startswith("oa-observe:VPS-Omar:kanban_loop:")


def mod_finding_dict():
    return {
        "severite": "P1",
        "titre": "Kanban : 2 tâche(s) running > 6h",
        "detail": "Deux workers semblent bloqués depuis plus de 6h.",
        "vps": "VPS-Omar",
        "remediation": "Lister les cartes et débloquer les workers.",
        "detecteur": "kanban_loop",
    }
