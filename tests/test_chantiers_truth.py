import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_build():
    spec = importlib.util.spec_from_file_location("qg_build_chantiers_truth_r2", ROOT / "scripts" / "build.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def anonymous_source(checked_at: object = "2026-07-04T12:00:00Z"):
    return {
        "schema": "oa.chantiers-source/v1",
        "source": {
            "id": "historical-fixture-2026-07",
            "checked_at": checked_at,
            "freshness_ttl_days": 14,
            "description": "Anonymous historical fixture.",
        },
        "items": [
            {
                "rang": 1,
                "nom": "Historical workstream",
                "horizon": "next",
                "objectif": "Demonstrate age handling without operational data.",
                "ecart": "Historical assertion retained for age demonstration only.",
                "effort": "S",
                "owner": "unassigned",
                "remaining_gap": "A dated, authorized proof is required.",
                "next_proof": "Provide a redacted dated proof outside the rebuild.",
            }
        ],
        "history": [{"checked_at": "2026-07-04T12:00:00Z", "summary": "Anonymous historical record."}],
    }


def test_historical_source_is_stale_at_frozen_time_and_keeps_legacy_uri():
    build = load_build()

    contract = build.normalize_chantiers_contract(
        anonymous_source(), now="2026-09-11T10:00:00Z"
    )

    assert contract["schema"] == "oa.chantiers/v2"
    assert contract["compatibility"]["legacy_api"] == "/api/chantiers.json"
    assert contract["compatibility"]["v2_api"] == "/api/chantiers-v2.json"
    assert contract["freshness"] == "stale"
    assert contract["items"][0]["historical"] is True
    assert contract["items"][0]["freshness"] == "stale"
    assert contract["history"] == anonymous_source()["history"]


def test_recent_checked_source_is_fresh_at_frozen_time():
    build = load_build()

    contract = build.normalize_chantiers_contract(
        anonymous_source("2026-09-10T12:00:00Z"), now="2026-09-11T10:00:00Z"
    )

    assert contract["freshness"] == "fresh"
    assert contract["items"][0]["historical"] is False


def test_missing_invalid_or_future_checked_at_fails_closed_to_empty_unknown():
    build = load_build()

    for checked_at in (None, "not-a-date", "2026-09-12T10:00:00Z"):
        contract = build.normalize_chantiers_contract(
            anonymous_source(checked_at), now="2026-09-11T10:00:00Z"
        )
        assert contract["freshness"] == "unknown"
        assert contract["items"] == []
        assert contract["source"]["checked_at"] is None
        assert contract["errors"]


def test_missing_or_non_parseable_source_is_unknown_and_empty(tmp_path):
    build = load_build()

    missing = build.load_chantiers_contract(tmp_path / "missing.json", now="2026-09-11T10:00:00Z")
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text("not-json", encoding="utf-8")
    invalid = build.load_chantiers_contract(invalid_path, now="2026-09-11T10:00:00Z")

    for contract in (missing, invalid):
        assert contract["freshness"] == "unknown"
        assert contract["items"] == []
        assert contract["errors"]


def test_json_contract_and_html_render_share_stale_verdict_and_versioned_link(tmp_path):
    build = load_build()
    source_path = tmp_path / "chantiers.json"
    source_path.write_text(json.dumps(anonymous_source()), encoding="utf-8")

    contract = build.load_chantiers_contract(source_path, now="2026-09-11T10:00:00Z")
    page = build.page_chantiers(contract)

    assert contract["freshness"] == "stale"
    assert 'data-chantiers-freshness="stale"' in page
    assert "/api/chantiers-v2.json" in page
    assert "/api/chantiers.json" in page
    assert "Historical workstream" in page


def test_tracked_source_is_minimal_anonymous_fixture():
    source = json.loads((ROOT / "data" / "chantiers.json").read_text(encoding="utf-8"))
    archive = json.loads((ROOT / "data" / "chantiers-2026-07-04.json").read_text(encoding="utf-8"))

    assert source["schema"] == "oa.chantiers-source/v1"
    assert source["source"]["archive"] == "chantiers-2026-07-04.json"
    assert archive == anonymous_source()["items"]
