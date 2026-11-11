"""Contrat de cycle de vie des alertes QG (carte t_81ecc772).

Trois défauts mesurés le 2026-11-11, figés ici :

1. **Clé volatile** (D1) — la clé d'anomalie contenait le pourcentage mesuré et
   la durée de staleness, donc chaque variation créait une NOUVELLE carte :
   13 cartes `vps-pantheos : disque N% (>70%)` (71 → 100 %) pour une seule
   condition réelle, et une carte `deadman-vps-*` par cycle de staleness.
2. **Aucun marqueur machine** (D2) — `hermes kanban list --json` n'expose pas
   `idempotency_key` : sans ligne `alert-key: <key>` dans le body, aucune carte
   n'est identifiable de façon fiable après coup.
3. **Aucune clôture** (D3) — `main()` n'envoyait qu'un 🟢 Telegram ; la carte
   Kanban restait ouverte des semaines après la disparition de l'anomalie.

Ces tests n'écrivent jamais en prod : board SQLite temporaire + faux binaire
`hermes` qui journalise ses arguments.
"""
import importlib.util
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_alerts():
    spec = importlib.util.spec_from_file_location("qg_alerts_lifecycle", ROOT / "scripts" / "alerts.py")
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------
# D1 — clé stable : aucune valeur volatile dans la clé
# --------------------------------------------------------------------------

def test_vps_alert_key_ignores_percentage_and_threshold():
    """(a) même anomalie disque à 71 %, 79 % ou 100 % -> exactement la même clé."""
    mod = load_alerts()
    keys = {
        mod.vps_alert_key("vps-pantheos", "disque 71% (>70%)"),
        mod.vps_alert_key("vps-pantheos", "disque 79% (>70%)"),
        mod.vps_alert_key("vps-pantheos", "disque 100% (>70%)"),
    }
    assert keys == {"vps-vps-pantheos-disque"}, keys


def test_vps_alert_key_keeps_distinct_anomalies_distinct():
    """Deux anomalies différentes sur le même VPS restent deux clés différentes."""
    mod = load_alerts()
    assert mod.vps_alert_key("vps-omar", "disque 79% (>70%)") != \
        mod.vps_alert_key("vps-omar", "swap 99% (>90)")
    assert mod.vps_alert_key("vps-omar", "swap 99% (>90)") == "vps-vps-omar-swap"
    assert mod.vps_alert_key("vps-pantheos", "disque 79% (>70%)") != \
        mod.vps_alert_key("vps-omar", "disque 79% (>70%)")


def test_deadman_key_is_stable_whatever_the_staleness_duration(tmp_path, monkeypatch):
    """(a) « stale depuis 12 min » et « stale depuis 1563.4 min » -> même clé."""
    mod = load_alerts()
    inbox = tmp_path / "inter-vps-inbox"
    report = inbox / "jab" / "jab-health.v1.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({
        "schema": "oa.vps-report/v1",
        "node": "jab",
        "vps_id": "vps-jab",
        "generated_at": "2026-11-11T10:00:00+00:00",
        "health": {"status": "ok"},
    }), encoding="utf-8")
    monkeypatch.setattr(mod, "INTER_VPS_REPORT_DIRS", [inbox])
    monkeypatch.setattr(mod, "DEADMAN_EXPECTED_NODES", [{
        "id": "jab", "aliases": {"jab", "vps-jab"}, "label": "jab",
        "owner": "cc-jab", "expected_path": "/jab.json", "silence_min": 65,
    }])

    early = mod.collect_vps_deadman(now=datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc))
    late = mod.collect_vps_deadman(now=datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc))

    assert set(early) == {"deadman-vps-jab"}
    assert set(late) == {"deadman-vps-jab"}, "la durée de staleness ne doit pas entrer dans la clé"
    assert "stale depuis 120 min" in early["deadman-vps-jab"]
    assert "stale depuis 1560 min" in late["deadman-vps-jab"]


def test_key_format_migration_is_not_a_new_alert_nor_a_false_resolution():
    """Migration `disque N% (>N%)` -> `disque` : ni carte dupliquée, ni faux « résolu »."""
    mod = load_alerts()
    prev = {"vps-vps-pantheos-disque N% (>N%)": "vps-pantheos : disque 79% (>70%)"}
    cur = {"vps-vps-pantheos-disque": "vps-pantheos : disque 79% (>70%)"}

    new, gone = mod.diff_alerts(prev, cur)

    assert new == {}, "une migration de format de clé ne doit pas créer de carte"
    assert gone == {}, "une migration de format de clé ne doit pas annoncer « résolu »"


def test_real_resolution_and_real_new_anomaly_still_reported():
    """La normalisation ne masque ni une vraie résolution ni une vraie nouvelle panne."""
    mod = load_alerts()
    new, gone = mod.diff_alerts(
        {"vps-vps-pantheos-disque N% (>N%)": "vps-pantheos : disque 79% (>70%)"},
        {"health-qg": "qg.omar.paris ne répond pas (health 502)"},
    )
    assert list(new) == ["health-qg"]
    assert list(gone) == ["vps-vps-pantheos-disque N% (>N%)"]


# --------------------------------------------------------------------------
# D2/D3 — marqueur machine + clôture automatique
# --------------------------------------------------------------------------

def make_board(path: Path, cards: list[dict]) -> Path:
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, body TEXT, status TEXT, "
        "idempotency_key TEXT, created_at INTEGER, result TEXT)"
    )
    for idx, card in enumerate(cards):
        con.execute(
            "INSERT INTO tasks (id, title, body, status, idempotency_key, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (
                card["id"],
                card.get("title", f"ALERTE fixture {card['id']}"),
                card.get("body"),
                card.get("status", "ready"),
                card.get("idempotency_key"),
                1000 + idx,
            ),
        )
    con.commit()
    con.close()
    return path


def fake_hermes(tmp_path: Path, monkeypatch, mod) -> Path:
    log = tmp_path / "hermes-calls.log"
    script = tmp_path / "hermes"
    script.write_text(
        "#!/bin/sh\n"
        f'for a in "$@"; do printf "ARG:%s\\n" "$a"; done >> {log}\n'
        "exit 0\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    monkeypatch.setattr(mod, "HERMES", script)
    return log


def calls(log: Path) -> list[str]:
    if not log.exists():
        return []
    return [line[len("ARG:"):] for line in log.read_text(encoding="utf-8").splitlines()
            if line.startswith("ARG:")]


def setup_env(tmp_path, monkeypatch, mod, *, prev: dict, cur: dict, cards: list[dict]):
    board = make_board(tmp_path / "kanban.db", cards)
    state = tmp_path / "alerts-state.json"
    state.write_text(json.dumps(prev), encoding="utf-8")
    monkeypatch.setattr(mod, "KANBAN_DB", board)
    monkeypatch.setattr(mod, "STATE", state)
    monkeypatch.setattr(mod, "TELEGRAM", tmp_path / "no-telegram.sh")
    monkeypatch.setattr(mod, "collect", lambda **kwargs: dict(cur))
    log = fake_hermes(tmp_path, monkeypatch, mod)
    return board, state, log


def test_created_card_body_carries_the_alert_key_marker(tmp_path, monkeypatch):
    """(c) D2 : le body de la carte créée contient `alert-key: <key>`."""
    mod = load_alerts()
    desc = "landing.omar.paris ne répond pas (health None)"
    board, state, log = setup_env(
        tmp_path, monkeypatch, mod,
        prev={}, cur={"health-landing": desc}, cards=[],
    )

    mod.main()

    argv = calls(log)
    assert "ALERTE: landing.omar.paris ne répond pas (health None)" in argv
    assert "alert-health-landing" in argv
    # Le body est passé en un seul argument multi-ligne : on inspecte le log brut.
    raw = log.read_text(encoding="utf-8")
    assert "alert-key: health-landing" in raw, raw


def test_resolved_alert_closes_card_found_by_body_marker(tmp_path, monkeypatch):
    """(b) D3 : `gone` -> `hermes kanban complete <id>` sur la carte marquée."""
    mod = load_alerts()
    prev = {"health-landing": "landing.omar.paris ne répond pas (health None)"}
    board, state, log = setup_env(
        tmp_path, monkeypatch, mod,
        prev=prev, cur={},
        cards=[{
            "id": "t_card_landing",
            "status": "ready",
            "idempotency_key": None,  # aucune clé d'idempotence : seul le marqueur identifie
            "body": "Alerte automatique oa-alerts.\n\nalert-key: health-landing\n\nlanding HS",
        }],
    )

    mod.main()

    argv = calls(log)
    assert "complete" in argv, argv
    assert "t_card_landing" in argv
    result = argv[argv.index("--result") + 1]
    assert "auto-résolue" in result
    assert "landing.omar.paris" in result
    assert "health-landing" in result, "la preuve doit citer la clé d'alerte"
    assert json.loads(state.read_text(encoding="utf-8")) == {}


def test_resolved_alert_closes_every_duplicate_card(tmp_path, monkeypatch):
    """(b) D3 : plusieurs cartes pour la même clé -> toutes fermées."""
    mod = load_alerts()
    prev = {"vps-vps-pantheos-disque": "vps-pantheos : disque 79% (>70%)"}
    marker = "alert-key: vps-vps-pantheos-disque"
    board, state, log = setup_env(
        tmp_path, monkeypatch, mod,
        prev=prev, cur={},
        cards=[
            {"id": "t_dup_1", "status": "blocked", "body": f"x\n\n{marker}\n\ndisque 72%"},
            {"id": "t_dup_2", "status": "ready", "body": f"x\n\n{marker}\n\ndisque 78%"},
            {"id": "t_other", "status": "ready", "body": "x\n\nalert-key: health-qg\n\nautre"},
        ],
    )

    mod.main()

    argv = calls(log)
    assert "t_dup_1" in argv and "t_dup_2" in argv
    assert "t_other" not in argv, "une autre anomalie ne doit jamais être fermée"


def test_active_alert_never_closes_or_duplicates_a_card(tmp_path, monkeypatch):
    """Une anomalie toujours active : aucune fermeture, aucune carte en plus."""
    mod = load_alerts()
    active = {"vps-vps-pantheos-disque": "vps-pantheos : disque 79% (>70%)"}
    board, state, log = setup_env(
        tmp_path, monkeypatch, mod,
        prev=active, cur=active,
        cards=[{
            "id": "t_card_disk", "status": "ready",
            "body": "x\n\nalert-key: vps-vps-pantheos-disque\n\ndisque 79%",
        }],
    )

    mod.main()

    argv = calls(log)
    assert "complete" not in argv
    assert "create" not in argv
    assert json.loads(state.read_text(encoding="utf-8")) == active


def test_dry_run_has_no_side_effect_on_board_or_state(tmp_path, monkeypatch):
    """`--dry-run` liste les fermetures sans appeler le CLI ni réécrire l'état."""
    mod = load_alerts()
    prev = {"health-landing": "landing.omar.paris ne répond pas (health None)"}
    board, state, log = setup_env(
        tmp_path, monkeypatch, mod,
        prev=prev, cur={},
        cards=[{
            "id": "t_card_landing", "status": "ready",
            "body": "x\n\nalert-key: health-landing\n\nlanding HS",
        }],
    )
    monkeypatch.setattr(sys, "argv", ["alerts.py", "--dry-run"])

    mod.main()

    assert calls(log) == []
    assert json.loads(state.read_text(encoding="utf-8")) == prev
