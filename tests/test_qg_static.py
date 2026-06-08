from pathlib import Path
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"

ROUTES = {
    "/": PUBLIC / "index.html",
    "/registry": PUBLIC / "registry" / "index.html",
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
        assert "V0.1.0" in text
        assert "CORE OA" in text
    api = PUBLIC / "api" / "core-repos.json"
    assert api.exists()
    payload = json.loads(api.read_text(encoding="utf-8"))
    assert payload["version"] == "V0.1.0"
    assert len(payload["items"]) >= 7


def test_qg_lists_required_core_repos():
    build()
    payload = json.loads((PUBLIC / "api" / "core-repos.json").read_text(encoding="utf-8"))
    ids = {item["id"] for item in payload["items"]}
    for required in ["landing", "app", "catalogue", "lab", "qg", "hub", "omartop"]:
        assert required in ids
    qg = next(item for item in payload["items"] if item["id"] == "qg")
    assert qg["version"] == "V0.1.0"
    assert qg["repo"].endswith("omar-qg")


def test_qg_pages_link_to_changelogs_and_no_secrets():
    build()
    text = "\n".join(p.read_text(encoding="utf-8") for p in PUBLIC.rglob("*.html"))
    for word in ["landing", "admin-app", "catalogue", "hub", "OmarTop"]:
        assert word in text
    assert "/changelog/" in text
    forbidden = ["ghp_", "sk-", "BEGIN OPENSSH PRIVATE KEY", "POSTGRES_PASSWORD"]
    for token in forbidden:
        assert token not in text


def test_qg_registry_explains_lab_vs_qg_vs_hub_top():
    build()
    text = (PUBLIC / "index.html").read_text(encoding="utf-8")
    assert "Lab = atelier" in text
    assert "QG = registry" in text
    assert "Hub/OmarTop = VPS Hermes OA" in text
