"""Anti-récidive : un zombie transitoire ne doit plus créer de carte oa-observe.

Contexte (carte t_185f2470) : le détecteur `orphan_procs` comptait tout process
en état Z sur un snapshot unique. Les workers Hermes spawnent des enfants
bash/python courts qui passent par <defunct> pendant quelques ms-s (reap en
cours) : le scan quotidien de 06:00 tombait régulièrement sur l'un d'eux et
recréait une carte P2 « 1 process zombie(s) » non actionnable, jamais
reproductible à la main. Seul un zombie PERSISTANT (>= ZOMBIE_MIN_AGE_S) doit
alerter.
"""
from pathlib import Path
import importlib.util
import sys

import pytest


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "oa-observe.py"
REPO_ROOT = Path(__file__).parents[1]


def load_observe():
    # oa-observe.py importe `scripts.swap_pressure` en repli : la racine du
    # dépôt doit être importable, comme quand le script tourne depuis le repo.
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    spec = importlib.util.spec_from_file_location("oa_observe", MODULE_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Le script utilise `from __future__ import annotations` : les dataclasses
    # résolvent leurs annotations via sys.modules[cls.__module__], donc le
    # module doit y être enregistré AVANT exec_module.
    sys.modules["oa_observe"] = module
    spec.loader.exec_module(module)
    return module


def _ps_output(rows):
    """rows: list of (pid, ppid, etimes, stat, comm)."""
    lines = ["    PID    PPID ELAPSED STAT COMMAND"]
    for pid, ppid, etimes, stat_, comm in rows:
        lines.append(f"{pid:>7} {ppid:>7} {etimes:>7} {stat_:<4} {comm}")
    return "\n".join(lines) + "\n"


def _run(monkeypatch, rows):
    mod = load_observe()
    monkeypatch.setattr(mod, "run_on", lambda t, cmd, timeout=30: (0, _ps_output(rows)))
    return mod.det_orphan_procs({"name": "VPS-Omar", "mode": "local"})


def test_transient_zombie_is_not_an_alert(monkeypatch):
    """Le cas exact de la carte : bash <defunct> vieux de 0 s."""
    findings = _run(monkeypatch, [(3401122, 3399628, 0, "Zs", "bash")])
    assert findings == []


def test_zombie_just_under_threshold_is_ignored(monkeypatch):
    mod = load_observe()
    findings = _run(monkeypatch, [(42, 1, mod.ZOMBIE_MIN_AGE_S - 1, "Z", "bash")])
    assert findings == []


def test_persistent_zombie_still_alerts_p2(monkeypatch):
    mod = load_observe()
    findings = _run(monkeypatch, [(42, 1, mod.ZOMBIE_MIN_AGE_S + 60, "Z", "python3")])
    assert len(findings) == 1
    f = findings[0]
    assert f.severite == "P2"
    assert f.detecteur == "orphan_procs"
    assert f.titre == "1 process zombie(s)"
    assert f.vps == "VPS-Omar"


def test_many_persistent_zombies_escalate_to_p1(monkeypatch):
    mod = load_observe()
    rows = [(100 + i, 1, 3600, "Z", "bash") for i in range(6)]
    findings = _run(monkeypatch, rows)
    assert len(findings) == 1
    assert findings[0].severite == "P1"
    assert findings[0].titre == "6 process zombie(s)"


def test_fingerprint_stable_for_real_zombie_finding(monkeypatch):
    """La clé d'idempotence d'un vrai zombie reste stable -> pas de doublon."""
    mod = load_observe()
    a = _run(monkeypatch, [(42, 1, 400, "Z", "bash")])[0]
    b = _run(monkeypatch, [(43, 2, 900, "Z", "bash")])[0]
    assert mod.finding_idempotency_key(a) == mod.finding_idempotency_key(b)
    assert mod.finding_idempotency_key(a).startswith("oa-observe:VPS-Omar:orphan_procs:")


def test_orphan_agent_branch_unaffected(monkeypatch):
    """Le volet orphelins claude/native-binary (ppid=1, >1h) reste actif."""
    findings = _run(monkeypatch, [(77, 1, 7200, "S", "claude")])
    assert len(findings) == 1
    assert findings[0].titre == "1 process claude/agent orphelin(s)"
