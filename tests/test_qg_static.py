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


def test_qg_home_surfaces_latest_result_and_mandates():
    build()
    home = (PUBLIC / "index.html").read_text(encoding="utf-8")
    assert "Dernier résultat livré" in home
    assert "Décisions / mandats" in home
    assert "mandat:h-omar-night-2026-06-14" in home
    assert 'href="/builds/"' in home
    assert 'href="/decisions/"' in home


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


def test_qg_repo_health_api_and_ops_surface():
    build()
    api = PUBLIC / "api" / "repo-health.json"
    assert api.exists()
    payload = json.loads(api.read_text(encoding="utf-8"))
    assert payload["schema"] == "oa.repo-health/1"
    assert payload["totals"]["repos"] >= 5
    assert {"dirty", "p0", "p1", "p2", "open_prs", "conflict_prs"} <= set(payload["totals"])
    for repo in payload["repos"]:
        assert {"slug", "risk", "dirty_count", "next_action"} <= set(repo)
        assert repo["risk"] in {"P0", "P1", "P2", "OK"}
    ops = (PUBLIC / "ops" / "index.html").read_text(encoding="utf-8")
    assert "Repo Health" in ops
    assert "/api/repo-health.json" in ops


def test_qg_agent_loop_registry_api_and_surface(tmp_path, monkeypatch):
    seed = tmp_path / "agent-loop-seed.json"
    seed.write_text(json.dumps({
        "schema": "oa.registry.min.test",
        "github_pr": {
            "number": 48,
            "state": "MERGED",
            "title": "feat(app): devis PDF + provisioning dry-run",
            "url": "https://github.com/omar-paris/omar-app/pull/48",
            "mergedAt": "2026-06-30T18:03:16Z",
            "mergeCommit": {"oid": "f399b9074d576d2ce7db9caa885d094fcf27c0a6"},
        },
        "kanban_tasks": [
            {"id": "t_builder", "title": "Builder fixed PR #48", "status": "done"},
            {"id": "t_review", "title": "Athena review PR #48", "status": "done"},
        ],
        "artifacts": ["/tmp/review_result.json"],
    }), encoding="utf-8")
    monkeypatch.setenv("OA_AGENT_LOOP_REGISTRY_SEED", str(seed))

    build()
    api = PUBLIC / "api" / "agent-loop-registry.json"
    assert api.exists()
    payload = json.loads(api.read_text(encoding="utf-8"))
    assert payload["schema"] == "oa.agent-loop-registry/1"
    assert payload["status"] == "healthy"
    assert payload["source"] == str(seed)
    assert payload["summary"]["prs"] >= 1
    assert payload["summary"]["cards"] >= 1
    assert payload["summary"]["gates"] >= 1
    assert payload["summary"]["merges"] >= 1
    assert payload["summary"]["artifacts"] >= 1
    assert any(item.get("kind") == "pr" and item.get("number") == 48 for item in payload["items"])
    assert any(item.get("kind") == "merge" for item in payload["items"])

    page = (PUBLIC / "agent-loop" / "index.html").read_text(encoding="utf-8")
    assert "Boucles prouvées" in page
    assert "registry P4" in page
    assert "feat(app): devis PDF + provisioning dry-run" in page
    assert "/api/agent-loop-registry.json" in page



def test_qg_storage_summary_api_and_ops_surface():
    build()
    api = PUBLIC / "api" / "ops" / "storage-summary.json"
    assert api.exists()
    payload = json.loads(api.read_text(encoding="utf-8"))
    assert {"meta", "status", "mounts", "memory", "backup_sets", "cloud_archives", "docker", "risks", "recommended_actions"} <= set(payload)
    assert payload["meta"]["source"] == "scripts/collect_storage.py"
    assert payload["status"] in {"ok", "warning", "critical", "unknown"}
    assert len(payload["mounts"]) >= 1
    for mount in payload["mounts"]:
        assert {"path", "label", "status", "exists"} <= set(mount)
    for backup_set in payload["backup_sets"]:
        assert "path" not in backup_set
        assert "latest" not in backup_set
        assert "archives_tail" not in backup_set
        assert {"count", "total_h", "latest_age_hours", "latest_checksum_exists"} <= set(backup_set)
    backup_serialized = json.dumps(payload["backup_sets"], ensure_ascii=False)
    assert "hermes-dbs-" not in backup_serialized
    assert "oa-offload-hermes-backups" not in backup_serialized
    docker = payload["docker"]
    assert {"safe_to_prune", "theoretical_reclaimable_hint", "dangling_images", "containers_stopped", "interpretation"} <= set(docker)
    if not docker["safe_to_prune"]:
        assert all(r.get("code") != "DOCKER_SAFE_PRUNE" for r in payload["risks"])
        assert not any("Docker:" in action for action in payload["recommended_actions"])
    ops = (PUBLIC / "ops" / "index.html").read_text(encoding="utf-8")
    assert "Stockage &amp; sauvegardes" in ops
    assert "Docker prune sûr" in ops
    assert "/api/ops/storage-summary.json" in ops
    assert "Backups Hermes DB" in ops
