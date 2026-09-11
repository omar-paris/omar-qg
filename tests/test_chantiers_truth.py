import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_build():
    spec = importlib.util.spec_from_file_location("qg_build_chantiers_truth", ROOT / "scripts" / "build.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def historical_source():
    return {
        "schema": "oa.chantiers-source/v1",
        "source": {
            "id": "product-truth-2026-07-04",
            "checked_at": "2026-07-04T12:00:00Z",
            "freshness_ttl_days": 14,
            "description": "Constat historique PRODUCT-TRUTH du 04/07.",
        },
        "items": [
            {
                "rang": 6,
                "nom": "QG",
                "horizon": "next",
                "objectif": "Rendre le QG reboot-safe.",
                "ecart": "26 dirty + 3 PRs draft sur omar-qg.",
                "effort": "S",
                "preuve": "qg_api.py :8097 · PRs #51/#52/#53",
                "owner": "CCMA + oa-athena",
                "remaining_gap": "Vérifier l'état Git et les PRs avec une collecte autorisée.",
                "next_proof": "Lookup GitHub et Git local daté, hors rebuild.",
            }
        ],
        "history": [
            {
                "checked_at": "2026-07-04T12:00:00Z",
                "summary": "Constat initial conservé sans réécriture.",
            }
        ],
    }


def test_historical_july_source_is_stale_at_frozen_september_time_and_never_uses_built_at():
    build = load_build()

    contract = build.normalize_chantiers_contract(
        historical_source(), now="2026-09-11T10:00:00Z"
    )

    assert contract["schema"] == "oa.chantiers/v2"
    assert contract["compatibility"]["legacy_api"] == "/api/chantiers-legacy.json"
    assert contract["source"]["checked_at"] == "2026-07-04T12:00:00Z"
    assert contract["freshness"] == "stale"
    assert contract["items"][0]["freshness"] == "stale"
    assert contract["items"][0]["historical"] is True
    assert "26 dirty + 3 PRs draft" in contract["items"][0]["ecart"]
    assert contract["items"][0]["remaining_gap"]
    assert contract["items"][0]["owner"]
    assert contract["items"][0]["next_proof"]
    assert contract["history"][0]["summary"] == "Constat initial conservé sans réécriture."



def test_recent_checked_source_is_fresh_at_frozen_time():
    build = load_build()
    source = historical_source()
    source["source"]["checked_at"] = "2026-09-10T12:00:00Z"

    contract = build.normalize_chantiers_contract(source, now="2026-09-11T10:00:00Z")

    assert contract["freshness"] == "fresh"
    assert contract["items"][0]["freshness"] == "fresh"
    assert contract["items"][0]["historical"] is False


def test_missing_or_non_parseable_source_is_unknown_not_a_reused_projection(tmp_path):
    build = load_build()

    missing = build.load_chantiers_contract(tmp_path / "missing.json", now="2026-09-11T10:00:00Z")
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text("not-json", encoding="utf-8")
    invalid = build.load_chantiers_contract(invalid_path, now="2026-09-11T10:00:00Z")

    for contract in (missing, invalid):
        assert contract["schema"] == "oa.chantiers/v2"
        assert contract["freshness"] == "unknown"
        assert contract["items"] == []
        assert contract["source"]["checked_at"] is None
        assert contract["errors"]


def test_json_projection_and_html_render_share_the_same_truth_verdict(tmp_path):
    build = load_build()
    source_path = tmp_path / "chantiers.json"
    source_path.write_text(json.dumps(historical_source()), encoding="utf-8")

    contract = build.load_chantiers_contract(source_path, now="2026-09-11T10:00:00Z")
    page = build.page_chantiers(contract)

    assert contract["freshness"] == "stale"
    assert 'data-chantiers-freshness="stale"' in page
    assert "Historique — source vérifiée le 2026-07-04T12:00:00Z" in page
    assert "Vérifier l&#x27;état Git et les PRs avec une collecte autorisée." in page
    assert "Lookup GitHub et Git local daté, hors rebuild." in page
