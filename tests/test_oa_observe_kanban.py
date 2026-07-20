import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
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


def test_backup_stale_accepts_status_ok_log(monkeypatch):
    mod = load_oa_observe()
    now = 1_800_000_000

    def fake_run_on(target, cmd, timeout=20):
        del target, cmd, timeout
        return 0, "[2027-01-15T07:55:00+00:00] status=OK file=/var/backups/oa-daily/jab.tar.gz.age"

    monkeypatch.setattr(mod, "run_on", fake_run_on)
    monkeypatch.setattr(mod.time, "time", lambda: now)

    findings = mod.det_backup_stale({"name": "VPS-Test", "backup_logs": ["/home/omar/4-Infra/logs/pull-backup-jab.log"]})

    assert findings == []


def test_backup_stale_accepts_legacy_db_ok_log(monkeypatch):
    mod = load_oa_observe()
    now = 1_800_000_000

    def fake_run_on(target, cmd, timeout=20):
        del target, cmd, timeout
        return 0, "[2027-01-15T07:55:00+00:00] DB oadmin OK (183M)"

    monkeypatch.setattr(mod, "run_on", fake_run_on)
    monkeypatch.setattr(mod.time, "time", lambda: now)

    findings = mod.det_backup_stale({"name": "VPS-Test", "backup_logs": ["/var/log/oadmin-backup.log"]})

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

    findings = mod.det_backup_stale({"name": "VPS-Test", "backup_logs": ["/home/omar/23-Offre/actifs/omar-top/state/compliance/omar/backup.log"]})

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
    assert findings[0].detail == (
        "Le contrôle client JAB pull (/tmp/jab.log) signale: aucun status=OK. "
        "Le backup primaire peut être sain, mais la réplication/pull client doit rester visible."
    )


def test_backup_stale_flags_stale_primary_ok_as_p1(monkeypatch):
    mod = load_oa_observe()
    now = datetime(2027, 1, 15, 7, 55, tzinfo=timezone.utc).timestamp()
    stale_ts = datetime(2027, 1, 13, 15, 55, tzinfo=timezone.utc).isoformat()

    def fake_run_on(target, cmd, timeout=20):
        del target, cmd, timeout
        return 0, f"[{stale_ts}] status=OK file=/var/backups/oa-daily/kanban.db"

    monkeypatch.setattr(mod, "run_on", fake_run_on)
    monkeypatch.setattr(mod.time, "time", lambda: now)

    findings = mod.det_backup_stale({"name": "VPS-Test", "backup_logs": ["/var/log/oadmin-backup.log"]})

    assert len(findings) == 1
    assert findings[0].severite == "P1"
    assert findings[0].titre == "Backup ancien : dernier OK il y a 40h"
    assert findings[0].detail == "Le backup OK primaire le plus récent date de 40h (seuil 36h). Le job s'est peut-être arrêté."


def test_backup_stale_flags_absent_or_failed_primary_as_p0(monkeypatch):
    mod = load_oa_observe()

    def fake_run_on(target, cmd, timeout=20):
        del target, cmd, timeout
        return 0, "[2027-01-15T07:55:00+00:00] status=NOFILE file=none"

    monkeypatch.setattr(mod, "run_on", fake_run_on)
    monkeypatch.setattr(mod.time, "time", lambda: 1_800_000_000)

    findings = mod.det_backup_stale({"name": "VPS-Test", "backup_logs": ["/var/log/oadmin-backup.log"]})

    assert len(findings) == 1
    assert findings[0].severite == "P0"
    assert findings[0].titre == "Aucun backup OK trouvé"
    assert findings[0].remediation == "Vérifier le cron/timer de backup et lancer un backup manuel de contrôle."


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
