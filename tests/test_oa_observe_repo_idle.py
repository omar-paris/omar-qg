"""Anti-régression det_repo_idle / réconciliation board — carte t_d1d22bf2.

Défauts couverts (classe, pas cas isolé) :
1. un échec `gh` (n_issues=None) était traité comme « 0 issue » => faux positif
   « pas en mode amélioration » ;
2. returncode/stderr de `gh` étaient jetés => échec invisible ;
3. aucune notion d'intention => repo gelé volontairement indistinguable d'un
   repo abandonné ;
4. la clôture auto dépendait du seul fichier d'état local => une carte dont la
   clé manquait dans le state restait ouverte indéfiniment.
"""
import importlib.util
import json
import subprocess
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_oa_observe():
    spec = importlib.util.spec_from_file_location("oa_observe_repo_idle", ROOT / "scripts/oa-observe.py")
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _fake_subprocess(monkeypatch, mod, *, last_commit_days: float, dirty: str = ""):
    """Remplace subprocess dans le module : git répond, gh n'est jamais appelé."""
    last_ts = str(int(time.time() - last_commit_days * 86400))

    def fake_run(cmd, *args, **kwargs):
        cmd = [str(c) for c in cmd]
        if cmd[:1] == ["git"]:
            if "--format=%ct" in cmd:
                return types.SimpleNamespace(returncode=0, stdout=last_ts + "\n", stderr="")
            if "status" in cmd:
                return types.SimpleNamespace(returncode=0, stdout=dirty, stderr="")
            # rev-parse @{u} : pas d'upstream => pas de finding "non poussé"
            return types.SimpleNamespace(returncode=1, stdout="", stderr="")
        raise AssertionError(f"appel subprocess inattendu : {cmd}")

    monkeypatch.setattr(mod, "subprocess", types.SimpleNamespace(
        run=fake_run, TimeoutExpired=subprocess.TimeoutExpired))
    return fake_run


def _make_repo(tmp_path: Path, name: str = "omar-test") -> Path:
    repo = tmp_path / name
    (repo / ".git").mkdir(parents=True)
    return repo


def _target():
    return {"name": "VPS-Omar", "mode": "local", "host": None, "homes": ["/home/omar"]}


def _detectors(findings):
    return [f.detecteur for f in findings]


def test_gh_unreadable_never_produces_repo_idle(monkeypatch, tmp_path):
    """(a) n_issues=None (échec gh) => gh_unreadable, JAMAIS repo_idle."""
    mod = load_oa_observe()
    _make_repo(tmp_path)
    monkeypatch.setattr(mod, "REPOS_BASE", tmp_path)
    monkeypatch.setattr(mod, "load_repo_intent", lambda *a, **k: {})
    _fake_subprocess(monkeypatch, mod, last_commit_days=400)
    monkeypatch.setattr(
        mod, "_gh_open_issues",
        lambda repo: (None, 1, "gh: HTTP 401: Bad credentials (https://api.github.com/graphql)"))

    findings = mod.det_repo_idle(_target())

    assert "repo_idle" not in _detectors(findings)
    assert _detectors(findings).count("gh_unreadable") == 1
    gh = [f for f in findings if f.detecteur == "gh_unreadable"][0]
    assert gh.severite == "P2"
    assert "illisibles" in gh.titre
    assert "INCONNU" in gh.detail
    # le diagnostic (rc + stderr) doit être remonté dans les notes du scan
    assert any("rc=1" in n and "401" in n for n in mod.SCAN_NOTES)


def test_zero_issues_and_idle_still_emits_repo_idle(monkeypatch, tmp_path):
    """(b) n_issues=0 + idle => repo_idle conservé (comportement historique)."""
    mod = load_oa_observe()
    _make_repo(tmp_path)
    monkeypatch.setattr(mod, "REPOS_BASE", tmp_path)
    monkeypatch.setattr(mod, "load_repo_intent", lambda *a, **k: {})
    _fake_subprocess(monkeypatch, mod, last_commit_days=400)
    monkeypatch.setattr(mod, "_gh_open_issues", lambda repo: (0, 0, ""))

    findings = mod.det_repo_idle(_target())

    assert _detectors(findings) == ["repo_idle"]
    assert findings[0].severite == "P2"
    assert "pas en mode amélioration" in findings[0].titre
    assert "0 issue ouverte" in findings[0].detail


def test_open_issues_and_idle_emit_nothing(monkeypatch, tmp_path):
    """(c) n_issues>0 + idle => aucun finding (le backlog existe)."""
    mod = load_oa_observe()
    _make_repo(tmp_path)
    monkeypatch.setattr(mod, "REPOS_BASE", tmp_path)
    monkeypatch.setattr(mod, "load_repo_intent", lambda *a, **k: {})
    _fake_subprocess(monkeypatch, mod, last_commit_days=400)
    monkeypatch.setattr(mod, "_gh_open_issues", lambda repo: (11, 0, ""))

    assert mod.det_repo_idle(_target()) == []


def test_frozen_repo_emits_no_repo_idle(monkeypatch, tmp_path):
    """(d) repo `frozen` dans le registre => aucun repo_idle, notice informative."""
    mod = load_oa_observe()
    _make_repo(tmp_path)
    monkeypatch.setattr(mod, "REPOS_BASE", tmp_path)
    monkeypatch.setattr(mod, "load_repo_intent", lambda *a, **k: {
        "omar-test": {
            "intent": "frozen",
            "decided_by": "H-Omar",
            "decided_at": "2026-11-11",
            "card": "t_c0baf8f3",
            "reopen_condition": "Certification Chantier 1",
        }
    })
    _fake_subprocess(monkeypatch, mod, last_commit_days=400)
    monkeypatch.setattr(mod, "_gh_open_issues", lambda repo: (0, 0, ""))

    findings = mod.det_repo_idle(_target())

    assert "repo_idle" not in _detectors(findings)
    assert _detectors(findings) == ["repo_intent_frozen"]
    notice = findings[0]
    assert notice.severite not in ("P0", "P1", "P2")
    assert "figé volontairement" in notice.titre
    assert "t_c0baf8f3" in notice.detail
    assert "Certification Chantier 1" in notice.detail


def test_frozen_repo_still_reports_uncommitted_files(monkeypatch, tmp_path):
    """Le gel supprime l'alerte d'intention, pas le risque de perte de travail."""
    mod = load_oa_observe()
    repo = _make_repo(tmp_path)
    stale = repo / "wip.py"
    stale.write_text("print('wip')\n", encoding="utf-8")
    old = time.time() - 72 * 3600
    import os
    os.utime(stale, (old, old))
    monkeypatch.setattr(mod, "REPOS_BASE", tmp_path)
    monkeypatch.setattr(mod, "load_repo_intent", lambda *a, **k: {"omar-test": {"intent": "frozen"}})
    _fake_subprocess(monkeypatch, mod, last_commit_days=400, dirty=" M wip.py\n")
    monkeypatch.setattr(mod, "_gh_open_issues", lambda repo: (0, 0, ""))

    findings = mod.det_repo_idle(_target())

    p1 = [f for f in findings if f.severite == "P1"]
    assert len(p1) == 1
    assert "non commité" in p1[0].titre
    assert "pas en mode amélioration" not in " ".join(f.titre for f in findings)


def test_board_reconciliation_resolves_card_missing_from_empty_state():
    """(e) une carte board absente des findings est résolue même si le state est vide."""
    mod = load_oa_observe()
    key = "oa-observe:VPS-Omar:repo_idle:d13237b9accc4358"
    board_cards = [{
        "task_id": "t_3d7f391b",
        "idempotency_key": key,
        "title": "[OBS][P2] VPS-Omar — omar-catalogue : pas en mode amélioration (37j sans commit)",
        "status": "scheduled",
    }]

    plan, state = mod.plan_kanban_sync([], previous={}, board_cards=board_cards, now_ts=1000)

    assert len(plan) == 1
    assert plan[0]["action"] == "resolve"
    assert plan[0]["task_id"] == "t_3d7f391b"
    assert plan[0]["source"] == "board"
    assert state[key]["status"] == "resolved"
    assert state[key]["task_id"] == "t_3d7f391b"


def test_board_reconciliation_keeps_card_that_is_still_a_finding():
    """Une carte dont la clé est toujours un finding courant n'est PAS résolue."""
    mod = load_oa_observe()
    finding = mod.Finding(
        "P2", "omar-test : pas en mode amélioration (400j sans commit)",
        "omar-test : dernier commit il y a 400 jours et 0 issue ouverte.",
        "VPS-Omar", "Décider.", "repo_idle")
    key = mod.finding_idempotency_key(finding)
    board_cards = [{"task_id": "t_keep", "idempotency_key": key,
                    "title": "[OBS][P2] omar-test", "status": "ready"}]

    plan, _ = mod.plan_kanban_sync([finding], previous={}, board_cards=board_cards)

    assert [op["action"] for op in plan] == ["create"]
    # le task_id du board est récupéré pour les updates/resolve futurs
    assert plan[0]["task_id"] == "t_keep"


def test_repo_idle_fingerprint_is_stable_across_days():
    """La mesure volatile (jours sans commit) ne doit pas créer une carte par jour."""
    mod = load_oa_observe()
    day_37 = mod.Finding(
        "P2", "omar-test : pas en mode amélioration (37j sans commit)",
        "omar-test : dernier commit il y a 37 jours et 0 issue ouverte.",
        "VPS-Omar", "Décider.", "repo_idle")
    day_38 = mod.Finding(
        "P2", "omar-test : pas en mode amélioration (38j sans commit)",
        "omar-test : dernier commit il y a 38 jours et 0 issue ouverte.",
        "VPS-Omar", "Décider.", "repo_idle")
    other_repo = mod.Finding(
        "P2", "omar-autre : pas en mode amélioration (38j sans commit)",
        "omar-autre : dernier commit il y a 38 jours et 0 issue ouverte.",
        "VPS-Omar", "Décider.", "repo_idle")

    assert mod.finding_idempotency_key(day_37) == mod.finding_idempotency_key(day_38)
    assert mod.finding_idempotency_key(day_38) != mod.finding_idempotency_key(other_repo)


def test_partial_scan_does_not_resolve_cards_of_unscanned_detectors():
    """Un scan `--only repo_idle` ne doit pas clore les cartes des autres détecteurs."""
    mod = load_oa_observe()
    repo_key = "oa-observe:VPS-Omar:repo_idle:d13237b9accc4358"
    bloat_key = "oa-observe:VPS-Omar:file_bloat:8b58f5e4bdc726a9"
    board_cards = [
        {"task_id": "t_repo", "idempotency_key": repo_key, "title": "[OBS][P2] repo", "status": "ready"},
        {"task_id": "t_bloat", "idempotency_key": bloat_key, "title": "[OBS][P1] bloat", "status": "ready"},
    ]

    plan, state = mod.plan_kanban_sync(
        [], previous={}, board_cards=board_cards, scanned_detectors={"repo_idle"}, now_ts=1000)

    resolved = {op["task_id"] for op in plan if op["action"] == "resolve"}
    assert resolved == {"t_repo"}
    assert bloat_key not in state


def test_full_scan_resolves_all_orphan_board_cards():
    """Sans restriction (scan complet), toutes les cartes orphelines sont résolues."""
    mod = load_oa_observe()
    board_cards = [
        {"task_id": "t_repo", "idempotency_key": "oa-observe:VPS-Omar:repo_idle:d13237b9accc4358",
         "title": "[OBS][P2] repo", "status": "ready"},
        {"task_id": "t_bloat", "idempotency_key": "oa-observe:VPS-Omar:file_bloat:8b58f5e4bdc726a9",
         "title": "[OBS][P1] bloat", "status": "ready"},
    ]

    plan, _ = mod.plan_kanban_sync([], previous={}, board_cards=board_cards, now_ts=1000)

    assert {op["task_id"] for op in plan if op["action"] == "resolve"} == {"t_repo", "t_bloat"}


def test_info_notice_does_not_become_a_kanban_card():
    """Une notice INFO (repo figé) reste dans le briefing, sans carte à dispatcher."""
    mod = load_oa_observe()
    notice = mod.Finding(
        "INFO", "omar-test : figé volontairement", "détail", "VPS-Omar",
        "Aucune action.", "repo_intent_frozen")

    plan, state = mod.plan_kanban_sync([notice], previous={}, now_ts=1000)

    assert plan == []
    assert state == {}


def test_repo_intent_registry_tolerates_missing_and_bad_schema(tmp_path):
    """Un registre absent ou d'un autre schéma ne doit jamais casser le scan."""
    mod = load_oa_observe()
    assert mod.load_repo_intent(tmp_path / "absent.json") == {}

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "oa.repo-intent/999", "repos": {"x": {"intent": "frozen"}}}),
                   encoding="utf-8")
    mod.SCAN_NOTES.clear()
    assert mod.load_repo_intent(bad) == {}
    assert any("schéma" in n for n in mod.SCAN_NOTES)

    good = tmp_path / "good.json"
    good.write_text(json.dumps({
        "schema": "oa.repo-intent/1",
        "repos": {"omar-catalogue": {"intent": "frozen", "decided_by": "H-Omar"}},
    }), encoding="utf-8")
    registry = mod.load_repo_intent(good)
    assert mod.repo_intent_of("omar-catalogue", registry) == "frozen"
    assert mod.repo_intent_of("omar-hub", registry) == ""
