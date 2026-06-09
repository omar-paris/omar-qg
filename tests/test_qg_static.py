from pathlib import Path
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"

ROUTES = {
    "/": PUBLIC / "index.html",
    "/partenaires": PUBLIC / "partenaires" / "index.html",
    "/changelog": PUBLIC / "changelog" / "index.html",
}


def build():
    subprocess.run(["python3", "scripts/build.py"], cwd=ROOT, check=True)


def test_qg_builds_core_routes_and_api():
    build()
    for route, path in ROUTES.items():
        assert path.exists(), route
        text = path.read_text(encoding="utf-8")
        assert "qg.omar.paris" in text
    # Registry specifically has CORE OA
    assert "CORE OA" in (PUBLIC / "index.html").read_text(encoding="utf-8")
    api = PUBLIC / "api" / "core-repos.json"
    assert api.exists()
    payload = json.loads(api.read_text(encoding="utf-8"))
    assert payload["version"].startswith("V")
    assert len(payload["items"]) >= 7


def test_qg_lists_required_core_repos():
    build()
    payload = json.loads((PUBLIC / "api" / "core-repos.json").read_text(encoding="utf-8"))
    ids = {item["id"] for item in payload["items"]}
    for required in ["landing", "app", "catalogue", "lab", "qg", "hub", "omartop"]:
        assert required in ids
    qg = next(item for item in payload["items"] if item["id"] == "qg")
    assert qg["repo"].endswith("omar-qg")


def test_qg_pages_link_to_changelogs_and_no_secrets():
    build()
    text = "\n".join(p.read_text(encoding="utf-8") for p in PUBLIC.rglob("*.html"))
    for word in ["landing", "AppOmar", "catalogue", "hub", "OmarTop"]:
        assert word in text
    assert "/changelog/" in text
    forbidden = ["ghp_", "sk-", "BEGIN OPENSSH PRIVATE KEY", "POSTGRES_PASSWORD"]
    for token in forbidden:
        assert token not in text


def test_qg_registry_has_core_oa_scopes():
    build()
    text = (PUBLIC / "index.html").read_text(encoding="utf-8")
    assert "CORE OA" in text
    assert "VPS Hermes OA" in text
    assert "Healthy" in text
    # Partners page exists
    assert (PUBLIC / "partenaires" / "index.html").exists()


def test_qg_api_has_live_data_fields():
    build()
    payload = json.loads((PUBLIC / "api" / "core-repos.json").read_text(encoding="utf-8"))
    assert "built_at" in payload
    assert payload["built_at"]
    counts = payload["counts"]
    assert "healthy" in counts
    assert "open_issues_total" in counts
    assert "open_prs_total" in counts
    for item in payload["items"]:
        assert "health" in item
        assert "status" in item["health"]
        assert "github" in item
        assert "open_issues" in item["github"]
        assert "open_prs" in item["github"]


def test_qg_health_column_in_html():
    build()
    text = (PUBLIC / "index.html").read_text(encoding="utf-8")
    assert "Health" in text
    # At least one successful probe visible (200)
    assert "200" in text


def test_qg_no_hardcoded_live_status_pill():
    build()
    text = (PUBLIC / "index.html").read_text(encoding="utf-8")
    assert 'pill">live<' not in text
    assert 'pill">tailnet<' not in text
    assert 'pill">public<' not in text
