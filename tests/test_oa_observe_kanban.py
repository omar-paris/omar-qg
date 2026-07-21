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


def test_ram_swap_fingerprint_ignores_dynamic_percentage_within_same_severity():
    mod = load_oa_observe()
    at_83_percent = mod.Finding(
        "P1", "Swap sous pression : 83% (5100/6144 Mo)",
        "Swap élevé avec pression mémoire active.", "VPS-Omar",
        "Diagnostiquer la pression mémoire.", "ram_swap")
    at_86_percent = mod.Finding(
        "P1", "Swap sous pression : 86% (5280/6144 Mo)",
        "Swap élevé avec pression mémoire active.", "VPS-Omar",
        "Diagnostiquer la pression mémoire.", "ram_swap")

    key = mod.finding_idempotency_key(at_83_percent)
    assert key == mod.finding_idempotency_key(at_86_percent)

    create_plan, state = mod.plan_kanban_sync([at_83_percent], previous={})
    update_plan, _ = mod.plan_kanban_sync([at_86_percent], previous=state)

    assert create_plan[0]["action"] == "create"
    assert len(update_plan) == 1
    assert update_plan[0]["action"] == "update"
    assert update_plan[0]["idempotency_key"] == key
    assert update_plan[0]["task_id"] is None


def test_non_ram_swap_findings_with_distinct_details_get_distinct_keys():
    mod = load_oa_observe()
    first = mod.Finding(
        "P1", "Fichier volumineux : alpha.log (12 Go)",
        "Le fichier /var/log/alpha.log dépasse le seuil.", "VPS-Omar",
        "Analyser /var/log/alpha.log.", "file_bloat")
    second = mod.Finding(
        "P1", "Fichier volumineux : beta.log (12 Go)",
        "Le fichier /var/log/beta.log dépasse le seuil.", "VPS-Omar",
        "Analyser /var/log/beta.log.", "file_bloat")

    first_key = mod.finding_idempotency_key(first)
    second_key = mod.finding_idempotency_key(second)

    assert first_key != second_key
    plan, state = mod.plan_kanban_sync([first, second], previous={})
    assert [op["action"] for op in plan] == ["create", "create"]
    assert {op["idempotency_key"] for op in plan} == {first_key, second_key}
    assert set(state) == {first_key, second_key}


def test_ram_swap_high_occupancy_without_pressure_or_activity_is_not_p1(monkeypatch):
    mod = load_oa_observe()
    outputs = iter([
        "Mem: 16000 8000 1000 100 7000 8000\nSwap: 6144 5300 844\n",
        "some avg10=0.00 avg60=0.00 avg300=0.00 total=0\n"
        "full avg10=0.00 avg60=0.00 avg300=0.00 total=0\n"
        "procs -----------memory---------- ---swap-- -----io---- -system-- ------cpu-----\n"
        " r  b     swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st\n"
        " 0  0  5300000 8000000 100000 100000    0    0     1     1    1    1  1  1 98  0  0\n"
        " 0  0  5300000 8000000 100000 100000    0    0     1     1    1    1  1  1 98  0  0\n"
        " 0  0  5300000 8000000 100000 100000    0    0     1     1    1    1  1  1 98  0  0\n",
    ])
    monkeypatch.setattr(mod, "run_on", lambda *args, **kwargs: (0, next(outputs)))

    assert mod.det_ram_swap({"name": "VPS-Test"}) == []


def test_ram_swap_high_occupancy_with_memory_pressure_is_p1(monkeypatch):
    mod = load_oa_observe()
    outputs = iter([
        "Mem: 16000 8000 1000 100 7000 8000\nSwap: 6144 5300 844\n",
        "some avg10=0.25 avg60=0.10 avg300=0.05 total=0\n"
        "full avg10=0.00 avg60=0.00 avg300=0.00 total=0\n",
    ])
    monkeypatch.setattr(mod, "run_on", lambda *args, **kwargs: (0, next(outputs)))

    findings = mod.det_ram_swap({"name": "VPS-Test"})

    assert len(findings) == 1
    assert findings[0].severite == "P1"
    assert "pression" in findings[0].titre.lower()


def test_ram_swap_p0_available_threshold_is_unchanged(monkeypatch):
    mod = load_oa_observe()
    monkeypatch.setattr(
        mod, "run_on",
        lambda *args, **kwargs: (0, "Mem: 16000 15000 1000 100 700 399\nSwap: 6144 0 6144\n"),
    )

    findings = mod.det_ram_swap({"name": "VPS-Test"})

    assert len(findings) == 1
    assert findings[0].severite == "P0"
    assert "399 Mo disponibles" in findings[0].titre


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


def test_backup_stale_accepts_status_ok_log(monkeypatch):
    mod = load_oa_observe()
    now = 1_800_000_000

    def fake_run_on(target, cmd, timeout=20):
        del target, cmd, timeout
        return 0, "[2027-01-15T07:55:00+00:00] status=OK file=/var/backups/oa-daily/jab.tar.gz.age"

    monkeypatch.setattr(mod, "run_on", fake_run_on)
    monkeypatch.setattr(mod.time, "time", lambda: now)

    findings = mod.det_backup_stale({"name": "VPS-Test", "backup_logs": ["/tmp/backup.log"]})

    assert findings == []


def test_backup_stale_accepts_legacy_db_ok_log(monkeypatch):
    mod = load_oa_observe()
    now = 1_800_000_000

    def fake_run_on(target, cmd, timeout=20):
        del target, cmd, timeout
        return 0, "[2027-01-15T07:55:00+00:00] DB oadmin OK (183M)"

    monkeypatch.setattr(mod, "run_on", fake_run_on)
    monkeypatch.setattr(mod.time, "time", lambda: now)

    findings = mod.det_backup_stale({"name": "VPS-Test", "backup_logs": ["/tmp/legacy.log"]})

    assert findings == []


def test_backup_stale_accepts_fresh_integrity_ok_manifest(monkeypatch):
    mod = load_oa_observe()
    now = 1_800_000_000
    manifest = json.dumps({
        "schema": "oa.backup-manifest/v1",
        "ts": "2027-01-15T07:55:00Z",
        "all_integrity_ok": True,
        "files": [{"name": "kanban.db", "integrity": "ok"}],
    })

    def fake_run_on(target, cmd, timeout=20):
        del target, cmd, timeout
        return 0, manifest

    monkeypatch.setattr(mod, "run_on", fake_run_on)
    monkeypatch.setattr(mod.time, "time", lambda: now)

    findings = mod.det_backup_stale({"name": "VPS-Test", "backup_logs": ["/tmp/backup.log"]})

    assert findings == []


def test_backup_stale_warns_when_client_pull_failed_even_if_primary_is_ok(monkeypatch):
    mod = load_oa_observe()
    now = 1_800_000_000
    logs = {
        "/tmp/primary.log": json.dumps({
            "schema": "oa.backup-manifest/v1",
            "ts": "2027-01-15T07:55:00Z",
            "all_integrity_ok": True,
        }),
        "/tmp/jab.log": "[2027-01-15T07:56:00+00:00] status=NOFILE file=none",
    }

    def fake_run_on(target, cmd, timeout=20):
        del target, timeout
        for path, output in logs.items():
            if path in cmd:
                return 0, output
        return 0, "__ABSENT__"

    monkeypatch.setattr(mod, "run_on", fake_run_on)
    monkeypatch.setattr(mod.time, "time", lambda: now)

    findings = mod.det_backup_stale({
        "name": "VPS-Omar",
        "backup_logs": [
            {"path": "/tmp/primary.log", "scope": "primary"},
            {"path": "/tmp/jab.log", "scope": "client", "label": "JAB pull"},
        ],
    })

    assert len(findings) == 1
    assert findings[0].severite == "P1"
    assert findings[0].titre == "Backup client JAB pull sans OK frais"


def test_file_bloat_uses_specific_hermes_state_db_threshold(monkeypatch):
    mod = load_oa_observe()

    def fake_run_on(target, cmd, timeout=90):
        del target, cmd, timeout
        return 0, "\n".join([
            f"{600 * 1024**2}\t/home/omar/.hermes/state.db",
            f"{600 * 1024**2}\t/home/omar/oa-admin/live.sqlite",
        ])

    monkeypatch.setattr(mod, "run_on", fake_run_on)

    findings = mod.det_file_bloat({"homes": ["/home/omar"], "name": "VPS-Omar"})

    assert len(findings) == 1
    assert findings[0].titre == "Fichier volumineux : live.sqlite (0.6 Go)"
    assert "seuil P1 500 MiB" in findings[0].detail


def test_file_bloat_reports_hermes_state_db_above_specific_threshold(monkeypatch):
    mod = load_oa_observe()

    def fake_run_on(target, cmd, timeout=90):
        del target, cmd, timeout
        return 0, f"{800 * 1024**2}\t/home/omar/.hermes/state.db"

    monkeypatch.setattr(mod, "run_on", fake_run_on)

    findings = mod.det_file_bloat({"homes": ["/home/omar"], "name": "VPS-Omar"})

    assert len(findings) == 1
    assert findings[0].titre == "Fichier volumineux : state.db (0.8 Go)"
    assert "seuil P1 768 MiB" in findings[0].detail


def mod_finding_dict():
    return {
        "severite": "P1",
        "titre": "Kanban : 2 tâche(s) running > 6h",
        "detail": "Deux workers semblent bloqués depuis plus de 6h.",
        "vps": "VPS-Omar",
        "remediation": "Lister les cartes et débloquer les workers.",
        "detecteur": "kanban_loop",
    }
