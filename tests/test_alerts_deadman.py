import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_alerts():
    spec = importlib.util.spec_from_file_location("qg_alerts", ROOT / "scripts" / "alerts.py")
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_report(path: Path, *, node="pantheos", generated_at: str, **extra):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "oa.vps-report/v1",
        "node": node,
        "vps_id": f"vps-{node}",
        "generated_at": generated_at,
        "agent": "fixture",
        "health": {"status": "ok"},
    }
    payload.update(extra)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_deadman_uses_source_heartbeat_not_synthetic_local_refresh(tmp_path, monkeypatch):
    mod = load_alerts()
    inbox = tmp_path / "inter-vps-inbox"
    # Reproduction incident: canonical QG refreshed now, native Pantheos source 14 days old.
    write_report(
        inbox / "pantheos" / "pantheos-health.v1.json",
        generated_at="2026-07-20T18:52:43+02:00",
        source_report_generated_at="2026-07-06T22:42:04+02:00",
        observed_at="2026-07-20T18:52:43+02:00",
        normalized_at="2026-07-20T18:52:43+02:00",
    )
    monkeypatch.setattr(mod, "INTER_VPS_REPORT_DIRS", [inbox])
    monkeypatch.setattr(
        mod,
        "DEADMAN_EXPECTED_NODES",
        [{"id": "pantheos", "aliases": {"pantheos", "vps-pantheos"}, "label": "pantheos", "owner": "h-aurel", "expected_path": "/pantheos.json", "silence_min": 65}],
    )

    raw = mod.collect_vps_deadman(now=datetime(2026, 7, 20, 19, 0, tzinfo=timezone.utc))

    assert "deadman-vps-pantheos" in raw
    assert "source heartbeat" in raw["deadman-vps-pantheos"]
    assert "2026-07-06T22:42:04+02:00" in raw["deadman-vps-pantheos"]


def test_deadman_resolves_on_real_fresh_source_heartbeat(tmp_path, monkeypatch):
    mod = load_alerts()
    inbox = tmp_path / "inter-vps-inbox"
    write_report(
        inbox / "pantheos" / "pantheos-health.v1.json",
        generated_at="2026-07-20T18:52:43+02:00",
        source_report_generated_at="2026-07-20T18:35:00+02:00",
        observed_at="2026-07-20T18:52:43+02:00",
        normalized_at="2026-07-20T18:52:43+02:00",
    )
    monkeypatch.setattr(mod, "INTER_VPS_REPORT_DIRS", [inbox])
    monkeypatch.setattr(
        mod,
        "DEADMAN_EXPECTED_NODES",
        [{"id": "pantheos", "aliases": {"pantheos", "vps-pantheos"}, "label": "pantheos", "owner": "h-aurel", "expected_path": "/pantheos.json", "silence_min": 65}],
    )

    raw = mod.collect_vps_deadman(now=datetime(2026, 7, 20, 17, 0, tzinfo=timezone.utc))

    assert raw == {}


def test_deadman_damping_prevents_flap_between_pull_cycles(tmp_path, monkeypatch):
    mod = load_alerts()
    inbox = tmp_path / "inter-vps-inbox"
    # Pull cadence is 30 min; Pantheos threshold is 65 min, so two 5-min alert cycles
    # between pulls must not create a transient stale→resolved flap.
    write_report(
        inbox / "pantheos" / "pantheos-health.v1.json",
        generated_at="2026-07-20T18:30:00+02:00",
        source_report_generated_at="2026-07-20T18:30:00+02:00",
        observed_at="2026-07-20T18:30:00+02:00",
        normalized_at="2026-07-20T18:30:00+02:00",
    )
    monkeypatch.setattr(mod, "INTER_VPS_REPORT_DIRS", [inbox])
    monkeypatch.setattr(
        mod,
        "DEADMAN_EXPECTED_NODES",
        [{"id": "pantheos", "aliases": {"pantheos", "vps-pantheos"}, "label": "pantheos", "owner": "h-aurel", "expected_path": "/pantheos.json", "silence_min": 65}],
    )

    first_cycle = mod.collect_vps_deadman(now=datetime(2026, 7, 20, 16, 55, tzinfo=timezone.utc))
    second_cycle = mod.collect_vps_deadman(now=datetime(2026, 7, 20, 17, 0, tzinfo=timezone.utc))
    active, state = mod.apply_deadman_damping(first_cycle, {}, now_ts=100)
    active, state = mod.apply_deadman_damping(second_cycle, state, now_ts=200)

    assert first_cycle == {}
    assert second_cycle == {}
    assert active == {}
    assert state == {}


def test_deadman_damping_confirms_real_stale_after_two_consecutive_cycles(monkeypatch):
    mod = load_alerts()
    monkeypatch.setattr(mod, "DEADMAN_DAMPING_CYCLES", 2)
    raw = {"deadman-vps-pantheos": "Dead-man's-switch: source heartbeat pantheos stale"}

    first, state = mod.apply_deadman_damping(raw, {}, now_ts=100)
    second, state = mod.apply_deadman_damping(raw, state, now_ts=200)

    assert first == {}
    assert second["deadman-vps-pantheos"].endswith("confirmé 2 cycles consécutifs")
    assert state["deadman-vps-pantheos"]["consecutive"] == 2
