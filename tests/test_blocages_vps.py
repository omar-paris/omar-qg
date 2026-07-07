"""Blockers multi-VPS (rescue J4 07/07) : agrégation des blockers[] des rapports
oa.vps-report/v1 NON-omar avec origine=<node>, dédupliqués contre les entrées
locales (les blockers d'omar.json PROVIENNENT de blocages.json — jamais doublés).
Tests purs sur collect_blocages.collect_vps_blockers : aucun réseau, aucun kanban.
"""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_collect_blocages():
    spec = importlib.util.spec_from_file_location(
        "collect_blocages_test", ROOT / "scripts" / "collect_blocages.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_report(root: Path, node: str, blockers: list, generated_at: str = "2026-07-07T01:51:27Z"):
    (root / node).mkdir(parents=True, exist_ok=True)
    (root / node / "vps-report-latest.json").write_text(json.dumps({
        "schema": "oa.vps-report/v1",
        "vps_id": f"vps-{node}",
        "tenant": node,
        "generated_at": generated_at,
        "apps": [],
        "standards": [],
        "blockers": blockers,
        "next_action": {"owner": "h-omar", "action_1_line": "n/a"},
        "maturity": "FAIL",
    }, ensure_ascii=False), encoding="utf-8")


def test_vps_blockers_origin_and_dedup(tmp_path, monkeypatch):
    m = _load_collect_blocages()
    monkeypatch.setattr(m, "INTER_VPS_REPORT_DIRS", [tmp_path])
    _write_report(tmp_path, "jab", [
        # 1. duplique EXACTEMENT une entrée locale → annoté, pas doublé
        {"title": "omar-hub#56 — feat: cover vault scanner", "who_unblocks": "alex",
         "age_days": 22, "action_1_line": "reviewer puis merger"},
        # 2. duplique une entrée locale via rédaction remote (token → <redacted-word>)
        {"title": "[OPS] Rotation <redacted-word> machine Caddy", "who_unblocks": "alex",
         "age_days": 2, "action_1_line": "rotater"},
        # 3. propre à JAB → entrée origine=jab
        {"title": "[JAB] PennyLane webhook en erreur 500", "who_unblocks": "agent",
         "age_days": 1, "action_1_line": "relancer le webhook PennyLane"},
    ])
    # Les rapports du VPS local (omar/oa-master) ne sont JAMAIS réimportés.
    _write_report(tmp_path, "omar", [
        {"title": "[LOCAL] ne doit jamais revenir", "who_unblocks": "alex",
         "age_days": 1, "action_1_line": "n/a"},
    ])

    now = m.now_utc()
    local = [
        m.entry("pr:omar-hub#56", "alex", "pr", "omar-hub#56 — feat: cover vault scanner",
                22, "reviewer puis merger", refs=["omar-hub#56"]),
        m.entry("carte:t_rotation", "alex", "sudo", "[OPS] Rotation token machine Caddy",
                2, "rotater", refs=["t_rotation"]),
    ]
    errors: list[str] = []
    entries, stats = m.collect_vps_blockers(now, local, errors)

    assert errors == []
    assert stats["jab"]["total"] == 3
    assert stats["jab"]["dedupliques"] == 2
    assert stats["jab"]["uniques"] == 1
    assert "omar" not in stats

    assert len(entries) == 1
    unique = entries[0]
    assert unique["origine"] == "jab"
    assert unique["type"] == "vps"
    assert unique["qui_debloque"] == "agent"
    assert "PennyLane" in unique["titre"]
    # Les dupliqués annotent l'entrée locale au lieu de la doubler.
    # Correction 07/07 (feedback Alex) : les reflets du kanban central relus
    # par un VPS sont JETES sans annotation — pas de badge sur la file locale.
    assert "aussi_signale_par" not in local[0]
    assert "aussi_signale_par" not in local[1]
    # Les entrées locales portent origine vide (= VPS-Omar).
    assert local[0]["origine"] == ""
