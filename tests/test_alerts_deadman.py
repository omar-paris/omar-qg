import importlib.util
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


def test_deadman_flags_oa_master_after_silence_threshold(monkeypatch):
    mod = load_alerts()
    monkeypatch.setattr(mod, "INTER_VPS_REPORT_DIRS", [ROOT / "tests" / "fixtures" / "inter-vps-inbox"])
    monkeypatch.setattr(mod, "HEARTBEAT_SILENCE_MIN", 6)

    now = datetime(2026, 7, 7, 0, 6, tzinfo=timezone.utc)
    raw = mod.collect_vps_deadman(now=now)

    assert "deadman-vps-oa-master" in raw
    assert "silence oa-master / VPS-Omar" in raw["deadman-vps-oa-master"]
    assert "seuil 6 min" in raw["deadman-vps-oa-master"]


def test_deadman_does_not_flag_oa_master_at_normal_five_minute_cadence(monkeypatch):
    mod = load_alerts()
    monkeypatch.setattr(mod, "INTER_VPS_REPORT_DIRS", [ROOT / "tests" / "fixtures" / "inter-vps-inbox"])
    monkeypatch.setattr(mod, "HEARTBEAT_SILENCE_MIN", 6)

    raw = mod.collect_vps_deadman(now=datetime(2026, 7, 7, 0, 5, tzinfo=timezone.utc))

    assert "deadman-vps-oa-master" not in raw


def test_deadman_respects_each_nodes_real_emission_cadence(monkeypatch):
    mod = load_alerts()
    monkeypatch.setattr(mod, "INTER_VPS_REPORT_DIRS", [ROOT / "tests" / "fixtures" / "inter-vps-inbox"])
    monkeypatch.setattr(
        mod,
        "DEADMAN_EXPECTED_NODES",
        [
            {
                "id": "fast",
                "aliases": {"oa-master", "omar", "vps-omar"},
                "label": "fast",
                "owner": "h-omar",
                "expected_path": "/fast.json",
                "silence_min": 4,
            },
            {
                "id": "daily",
                "aliases": {"oa-master", "omar", "vps-omar"},
                "label": "daily",
                "owner": "h-edilia",
                "expected_path": "/daily.json",
                "silence_min": 1560,
            },
        ],
    )

    now = datetime(2026, 7, 7, 0, 4, tzinfo=timezone.utc)
    raw = mod.collect_vps_deadman(now=now)

    assert "deadman-vps-fast" in raw
    assert "seuil 4 min" in raw["deadman-vps-fast"]
    assert "deadman-vps-daily" not in raw


def test_deadman_default_timing_guarantees_strict_alert_under_ten_minutes(monkeypatch):
    mod = load_alerts()
    monkeypatch.setattr(mod, "HEARTBEAT_SILENCE_MIN", 6)
    monkeypatch.setattr(mod, "DEADMAN_DAMPING_CYCLES", 2)
    monkeypatch.setattr(mod, "ALERTS_CRON_INTERVAL_MIN", 2)

    alert_latency_min = mod.HEARTBEAT_SILENCE_MIN + (mod.DEADMAN_DAMPING_CYCLES - 1) * mod.ALERTS_CRON_INTERVAL_MIN

    assert alert_latency_min == 8
    assert alert_latency_min < 10


def test_deadman_damping_requires_two_consecutive_cycles(monkeypatch):
    mod = load_alerts()
    monkeypatch.setattr(mod, "DEADMAN_DAMPING_CYCLES", 2)
    raw = {"deadman-vps-oa-master": "Dead-man's-switch: silence oa-master"}

    first, state = mod.apply_deadman_damping(raw, {}, now_ts=100)
    second, state = mod.apply_deadman_damping(raw, state, now_ts=200)

    assert first == {}
    assert second["deadman-vps-oa-master"].endswith("confirmé 2 cycles consécutifs")
    assert state["deadman-vps-oa-master"]["consecutive"] == 2


def test_deadman_heartbeat_return_clears_candidate_before_alert(monkeypatch):
    mod = load_alerts()
    monkeypatch.setattr(mod, "INTER_VPS_REPORT_DIRS", [ROOT / "tests" / "fixtures" / "inter-vps-inbox"])
    monkeypatch.setattr(
        mod,
        "DEADMAN_EXPECTED_NODES",
        [{**node, "silence_min": 4} if node["id"] == "oa-master" else node for node in mod.DEADMAN_EXPECTED_NODES],
    )

    stale_now = datetime(2026, 7, 7, 0, 4, tzinfo=timezone.utc)
    fresh_now = datetime(2026, 7, 7, 0, 3, 59, tzinfo=timezone.utc)

    raw_stale = mod.collect_vps_deadman(now=stale_now)
    _, state = mod.apply_deadman_damping(raw_stale, {}, now_ts=100)
    raw_fresh = mod.collect_vps_deadman(now=fresh_now)
    active, state = mod.apply_deadman_damping(raw_fresh, state, now_ts=200)

    assert "deadman-vps-oa-master" in raw_stale
    assert "deadman-vps-oa-master" not in raw_fresh
    assert active == {}
    assert "deadman-vps-oa-master" not in state
