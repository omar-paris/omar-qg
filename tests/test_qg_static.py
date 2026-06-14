from pathlib import Path
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"

ROUTES = {
    "/": PUBLIC / "index.html",
    "/objectifs": PUBLIC / "objectifs" / "index.html",
    "/ops": PUBLIC / "ops" / "index.html",
    "/partenaires": PUBLIC / "partenaires" / "index.html",
    "/changelog": PUBLIC / "changelog" / "index.html",
    "/apps/app": PUBLIC / "apps" / "app" / "index.html",
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
    ledger = json.loads((PUBLIC / "api" / "daily-ledger" / "index.json").read_text(encoding="utf-8"))
    assert ledger["latest"].startswith("/api/daily-ledger/")
    snapshot_name = ledger["latest"].removeprefix("/api/daily-ledger/")
    snapshot = json.loads((PUBLIC / "api" / "daily-ledger" / snapshot_name).read_text(encoding="utf-8"))
    assert ledger["items"][0] == snapshot
    assert ledger["items"][0]["github_totals"]


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
    assert "/ops/" in text
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


def test_qg_app_detail_pages_from_registry_data():
    build()
    registry = (PUBLIC / "index.html").read_text(encoding="utf-8")
    assert 'href="/apps/app/"' in registry
    app_page = (PUBLIC / "apps" / "app" / "index.html").read_text(encoding="utf-8")
    for expected in ["AppOmar", "Portail client", "P0/P1 du jour", "Derniers commits", "Historique 7 jours"]:
        assert expected in app_page
    assert "https://github.com/omar-paris/omar-app/issues/" in app_page
    ledger = json.loads((PUBLIC / "api" / "daily-ledger" / "index.json").read_text(encoding="utf-8"))
    assert 1 <= len(ledger["items"]) <= 7


def test_qg_objectifs_page_and_api():
    build()
    # Page /objectifs/ existe et liste les objectifs seed
    obj_html = (PUBLIC / "objectifs" / "index.html").read_text(encoding="utf-8")
    assert "JAB pleinement servi" in obj_html
    assert "Observabilite Langfuse" in obj_html
    # Progression rendue sous forme de barre
    assert "width:55%" in obj_html
    # API snapshot republie
    api = PUBLIC / "api" / "objectifs.json"
    assert api.exists()
    objectifs = json.loads(api.read_text(encoding="utf-8"))
    assert isinstance(objectifs, list) and len(objectifs) >= 3
    for obj in objectifs:
        assert {"id", "titre", "statut", "progression", "decisions_liees", "description"} <= set(obj)
        assert obj["statut"] in ("a_faire", "en_cours", "fait")
        assert 0 <= int(obj["progression"]) <= 100


def test_qg_objectifs_on_home_before_registry():
    build()
    home = (PUBLIC / "index.html").read_text(encoding="utf-8")
    body = home.split("<main", 1)[1]
    # Les objectifs apparaissent EN TÊTE, avant le registry de repos
    assert "Objectifs</h2>" in body
    assert body.index("Objectifs</h2>") < body.index("Registry CORE OA</h1>")
    # Lien nav vers la page dédiée
    assert 'href="/objectifs/"' in home


def test_qg_objectifs_link_to_decisions():
    build()
    obj_html = (PUBLIC / "objectifs" / "index.html").read_text(encoding="utf-8")
    objectifs = json.loads((PUBLIC / "api" / "objectifs.json").read_text(encoding="utf-8"))
    linked = [d for obj in objectifs for d in obj.get("decisions_liees", [])]
    assert linked, "au moins un objectif relie a une decision"
    # Chaque decision liee renvoie vers son ancre sur /decisions/
    for did in linked:
        assert f"/decisions/#card-{did}" in obj_html


def test_qg_app_detail_hides_unmeasured_app_sources():
    build()
    payload = json.loads((PUBLIC / "api" / "core-repos.json").read_text(encoding="utf-8"))
    app = next(item for item in payload["items"] if item["id"] == "app")
    assert app["version_source"] == "unmeasured"
    assert app["version"] == "version non mesurée"
    assert app["has_contract_source"] is False
    assert app["has_changelog_source"] is False

    app_page = (PUBLIC / "apps" / "app" / "index.html").read_text(encoding="utf-8")
    assert "V0.3.0" not in app_page
    assert "version non mesurée" in app_page
    assert "https://github.com/omar-paris/omar-app/blob/main/CONTRACT.md" not in app_page
    assert "https://app.omar.paris/changelog/" not in app_page
