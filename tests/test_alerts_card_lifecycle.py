"""Anti-récidive cartes ALERTE jamais fermées (carte t_a4f00112).

`alerts.py` créait une carte Kanban idempotente par anomalie
(`--idempotency-key alert-{key}`) mais, à la résolution, se contentait
d'envoyer un 🟢 Telegram et de réécrire son état : la carte restait ouverte
indéfiniment (constat 2026-11-11 : cartes `health None` du 2026-10-06 encore
ouvertes 36 j plus tard, 9 cartes pour la même condition disque Pantheos).

Ces tests figent le contrat de fermeture, sans toucher la prod : base SQLite
temporaire + faux binaire `hermes` qui journalise ses arguments.
"""
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_alerts():
    spec = importlib.util.spec_from_file_location("qg_alerts_cards", ROOT / "scripts" / "alerts.py")
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def make_board(path: Path, cards: list[tuple[str, str, str]]) -> Path:
    """Crée une base Kanban minimale : (task_id, status, idempotency_key)."""
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, status TEXT, "
        "idempotency_key TEXT, created_at INTEGER, result TEXT)"
    )
    for idx, (task_id, status, idem) in enumerate(cards):
        con.execute(
            "INSERT INTO tasks (id, title, status, idempotency_key, created_at) VALUES (?,?,?,?,?)",
            (task_id, f"ALERTE fixture {task_id}", status, idem, 1000 + idx),
        )
    con.commit()
    con.close()
    return path


def card_status(path: Path, task_id: str) -> str:
    con = sqlite3.connect(path)
    try:
        return con.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()[0]
    finally:
        con.close()


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


def setup_env(tmp_path, monkeypatch, mod, *, prev: dict, cur: dict, cards: list[tuple[str, str, str]]):
    board = make_board(tmp_path / "kanban.db", cards)
    state = tmp_path / "alerts-state.json"
    state.write_text(json.dumps(prev), encoding="utf-8")
    monkeypatch.setattr(mod, "KANBAN_DB", board)
    monkeypatch.setattr(mod, "STATE", state)
    monkeypatch.setattr(mod, "TELEGRAM", tmp_path / "no-telegram.sh")
    monkeypatch.setattr(mod, "collect", lambda **kwargs: dict(cur))
    log = fake_hermes(tmp_path, monkeypatch, mod)
    return board, state, log


def calls(log: Path) -> list[str]:
    if not log.exists():
        return []
    return [line[len("ARG:"):] for line in log.read_text(encoding="utf-8").splitlines() if line.startswith("ARG:")]


def test_resolved_alert_closes_its_card_by_idempotency_key(tmp_path, monkeypatch):
    """(d) alerte résolue -> la carte correspondante est fermée avec un résultat probant."""
    mod = load_alerts()
    prev = {"health-landing": "landing.omar.paris ne répond pas (health None)"}
    board, state, log = setup_env(
        tmp_path, monkeypatch, mod,
        prev=prev, cur={},
        cards=[("t_card_landing", "ready", "alert-health-landing")],
    )

    mod.main()

    argv = calls(log)
    assert "complete" in argv, f"la carte doit être fermée via hermes kanban complete (vu: {argv})"
    assert "t_card_landing" in argv
    result_idx = argv.index("--result") + 1
    assert "auto-résolue" in argv[result_idx]
    assert "landing.omar.paris" in argv[result_idx]
    assert "alert-health-landing" in argv[result_idx], "la preuve doit citer la clé d'idempotence"
    # L'état est réécrit : l'alerte ne sera pas rejouée au cycle suivant.
    assert json.loads(state.read_text(encoding="utf-8")) == {}


def test_active_alert_neither_closes_nor_duplicates(tmp_path, monkeypatch):
    """(e) alerte toujours active -> aucune fermeture, aucune carte dupliquée."""
    mod = load_alerts()
    active = {"health-landing": "landing.omar.paris ne répond pas (health None)"}
    board, state, log = setup_env(
        tmp_path, monkeypatch, mod,
        prev=active, cur=active,
        cards=[("t_card_landing", "ready", "alert-health-landing")],
    )

    mod.main()

    argv = calls(log)
    assert "complete" not in argv, "une alerte encore active ne doit jamais être fermée"
    assert "create" not in argv, "une alerte déjà connue ne doit pas recréer de carte"
    assert card_status(board, "t_card_landing") == "ready"
    assert json.loads(state.read_text(encoding="utf-8")) == active


def test_new_alert_creates_exactly_one_card_with_idempotency_key(tmp_path, monkeypatch):
    """(c) échec définitif -> une seule carte, clé d'idempotence alert-{key}."""
    mod = load_alerts()
    desc = "landing.omar.paris ne répond pas (health None)"
    board, state, log = setup_env(
        tmp_path, monkeypatch, mod,
        prev={}, cur={"health-landing": desc}, cards=[],
    )

    mod.main()

    argv = calls(log)
    assert argv.count("create") == 1, f"exactement une carte attendue (vu: {argv})"
    assert "alert-health-landing" in argv
    assert "ALERTE: landing.omar.paris ne répond pas (health None)" in argv


def test_resolved_alert_without_open_card_is_a_noop(tmp_path, monkeypatch):
    """Aucune carte ouverte (déjà fermée/archivée) -> pas de fermeture fantôme."""
    mod = load_alerts()
    prev = {"health-landing": "landing.omar.paris ne répond pas (health None)"}
    board, state, log = setup_env(
        tmp_path, monkeypatch, mod,
        prev=prev, cur={},
        cards=[("t_card_done", "done", "alert-health-landing")],
    )

    mod.main()

    argv = calls(log)
    assert "complete" not in argv
    assert card_status(board, "t_card_done") == "done"


def test_lookup_ignores_other_alerts_and_picks_open_card(tmp_path, monkeypatch):
    """Le lookup est strictement borné à la clé demandée."""
    mod = load_alerts()
    board = make_board(
        tmp_path / "kanban.db",
        [
            ("t_other", "ready", "alert-health-app"),
            ("t_closed", "done", "alert-health-landing"),
            ("t_open", "blocked", "alert-health-landing"),
        ],
    )
    monkeypatch.setattr(mod, "KANBAN_DB", board)

    assert mod.find_open_card_by_idempotency_key("alert-health-landing") == "t_open"
    assert mod.find_open_card_by_idempotency_key("alert-health-omartop") is None


def test_dry_run_reports_without_touching_board_or_state(tmp_path, monkeypatch):
    """`--dry-run` liste les fermetures sans écrire : vérification sans effet de bord."""
    mod = load_alerts()
    prev = {"health-landing": "landing.omar.paris ne répond pas (health None)"}
    board, state, log = setup_env(
        tmp_path, monkeypatch, mod,
        prev=prev, cur={},
        cards=[("t_card_landing", "ready", "alert-health-landing")],
    )
    monkeypatch.setattr(sys, "argv", ["alerts.py", "--dry-run"])

    mod.main()

    assert calls(log) == [], "un dry-run ne doit appeler aucun CLI kanban"
    assert card_status(board, "t_card_landing") == "ready"
    assert json.loads(state.read_text(encoding="utf-8")) == prev
