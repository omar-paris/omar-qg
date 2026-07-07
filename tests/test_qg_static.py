from pathlib import Path
import json
import os
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
_LAST_BUILD_KEY = object()

ROUTES = {
    "/": PUBLIC / "index.html",
    "/objectifs": PUBLIC / "objectifs" / "index.html",
    "/ops": PUBLIC / "ops" / "index.html",
    "/partenaires": PUBLIC / "partenaires" / "index.html",
    "/changelog": PUBLIC / "changelog" / "index.html",
    "/apps/app": PUBLIC / "apps" / "app" / "index.html",
}


def build():
    global _LAST_BUILD_KEY
    # scripts/build.py interroge GitHub/health/providers et coûte plusieurs dizaines
    # de secondes. Dans ce module, un rebuild par contexte d'environnement suffit ;
    # le test monkeypatch OA_AGENT_LOOP_REGISTRY_SEED force naturellement un 2e build.
    key = (os.environ.get("OA_AGENT_LOOP_REGISTRY_SEED"),)
    if _LAST_BUILD_KEY != key:
        subprocess.run(["python3", "scripts/build.py"], cwd=ROOT, check=True, env={**os.environ, "QG_USE_TEST_FIXTURES": "1"})
        _LAST_BUILD_KEY = key


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
    assert "Blocages / mandats" in home
    assert "Source unique: collect_blocages.py" in home
    assert "mandat:h-omar-night-2026-06-14" in home
    assert 'href="/builds/"' in home
    assert 'href="/blocages/"' in home


def test_qg_marks_known_stale_layers_honestly():
    build()
    objectifs = (PUBLIC / "objectifs" / "index.html").read_text(encoding="utf-8")
    agent_loop = (PUBLIC / "agent-loop" / "index.html").read_text(encoding="utf-8")
    assert "Donnée figée depuis le 14/06" in objectifs
    assert "figé depuis le 15/06" in agent_loop


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

def test_qg_vps_app_inventory_api_and_clients_surface():
    build()
    api = PUBLIC / "api" / "vps-app-inventory.json"
    assert api.exists()
    payload = json.loads(api.read_text(encoding="utf-8"))
    assert payload["schema"] == "oa.vps-app-inventory/1"
    assert payload["source"] == "oa.vps-report/v1 installed_apps/apps + standards + safe inference"
    assert payload["totals"]["nodes"] >= 1
    assert payload["totals"]["apps"] >= 5
    assert {"hermes", "omarhub", "tailscale", "reverse-proxy", "inter-vps-reporter"} <= {
        app["app_id"] for node in payload["nodes"] for app in node["apps"]
    }
    for node in payload["nodes"]:
        assert {"node", "tenant", "agent", "health_status", "generated_at", "apps", "summary", "standards", "standards_summary"} <= set(node)
        for app in node["apps"]:
            assert {"app_id", "name", "installed", "version_installed", "version_expected", "status", "verdict", "raw_status", "source", "evidence", "last_checked_at"} <= set(app)
            assert app["status"] in {"ok", "outdated", "missing", "unknown", "blocked"}
            assert app["verdict"] in {"PASS", "FAIL", "UNKNOWN"}
            assert "REDACTED" not in app["evidence"] or isinstance(app["evidence"], str)
    omar = next(node for node in payload["nodes"] if node["node"] == "omar")
    assert omar["tenant"] == "oa-internal"
    assert omar["summary"]["pass"] >= 1
    assert omar["summary"]["fail"] >= 1
    assert {"PASS", "FAIL"} <= {standard["verdict"] for standard in omar["standards"]}
    assert "UNKNOWN" in {app["verdict"] for app in omar["apps"]}
    clients = (PUBLIC / "clients" / "index.html").read_text(encoding="utf-8")
    assert "Inventaire apps/version par VPS" in clients
    assert "oa.vps-report/v1" in clients
    assert "/api/vps-app-inventory.json" in clients
    assert "Hermes local" in clients
    assert "tenant oa-internal" in clients
    assert "Standards reportés" in clients
    assert "OBS-SERVICES-01" in clients
    assert "MAINT-DOCTOR-01" in clients
    assert "PASS" in clients
    assert "FAIL" in clients
    assert "UNKNOWN" in clients


def test_qg_ops_vps_fleet_surface_and_api():
    build()
    api = PUBLIC / "api" / "ops" / "vps-fleet.json"
    assert api.exists()
    payload = json.loads(api.read_text(encoding="utf-8"))
    assert payload["schema"] == "oa.vps-fleet-status/1"
    assert payload["summary"]["expected"] == 3
    assert {"reporting", "en_derive", "muets", "standards_fail"} <= set(payload["summary"])
    nodes = {node["node"]: node for node in payload["nodes"]}
    # Les 3 VPS attendus ont TOUJOURS un bloc, rapport reçu ou pas.
    assert {"omar", "jab", "pantheos"} <= set(nodes)
    assert "oa-master" not in nodes  # alias du même VPS que omar, jamais un 4e nœud
    for node in payload["nodes"]:
        assert node["report_status"] in {"fresh", "stale", "missing"}
        assert node["transport_owner"]
        if node["report_status"] == "missing":
            assert node["expected_path"]
        else:
            assert node["maturity"] in {"PASS", "FAIL", "UNKNOWN"}
            assert {"standards_pass", "standards_fail", "fails", "apps_total", "apps_by_kind", "next_action", "generated_at"} <= set(node)

    ops = (PUBLIC / "ops" / "index.html").read_text(encoding="utf-8")
    assert "Flotte VPS" in ops
    assert "VPS rapportent" in ops
    assert "en dérive" in ops
    assert "muet(s)" in ops
    assert "SAV : non instrumenté — aucun flux SAV" in ops
    assert "/api/ops/vps-fleet.json" in ops
    # La tuile flotte de la home pointe vers /ops/.
    home = (PUBLIC / "index.html").read_text(encoding="utf-8")
    assert "VPS rapportent" in home


def test_qg_resource_onboarding_surface_and_appomar_spec():
    build()
    api = PUBLIC / "api" / "vps-resource-onboarding-v0.json"
    assert api.exists()
    payload = json.loads(api.read_text(encoding="utf-8"))
    assert payload["schema"] == "oa.resource-onboarding/public.v0"
    assert payload["visibility"] == "public_qg_redacted_counters_only"
    assert payload["resource_scope_schema"] == "oa.resource-scope/v1"
    assert payload["canonical_cloud_index"]["total_unique_records"] == 222634
    assert payload["canonical_cloud_index"]["google_drive_api_full_records"] == 194326
    assert payload["canonical_cloud_index"]["onedrive_rclone_targeted_records"] == 20901
    forbidden_public_tokens = [
        "/home/omar",
        "cloud-index/db",
        "Pantheos Drive",
        "Drive Omar",
        "Google AI Studio",
        "LADB/Boulangerie",
    ]
    api_text = api.read_text(encoding="utf-8")
    core_api = PUBLIC / "api" / "core-repos.json"
    assert core_api.exists()
    core_payload = json.loads(core_api.read_text(encoding="utf-8"))
    assert core_payload["resource_onboarding"]["schema"] == "oa.resource-onboarding/public.v0"
    assert core_payload["resource_onboarding"]["visibility"] == "public_qg_redacted_counters_only"
    core_text = core_api.read_text(encoding="utf-8")
    for token in forbidden_public_tokens:
        assert token not in api_text
        assert token not in core_text

    clients = (PUBLIC / "clients" / "index.html").read_text(encoding="utf-8")
    for expected in [
        "Ressources &amp; connaissances",
        "Cloud Index records",
        "Google Drive API full",
        "OneDrive ciblé",
        "V3 extraction contrôlée",
        "oa.resource-scope/v1",
        "aucun nom de fichier ni contenu brut",
    ]:
        assert expected in clients
    assert "/home/omar/32-Infra/cloud-index" not in clients
    for token in forbidden_public_tokens:
        assert token not in clients
    assert "lots candidats redacted" in clients

    app_page = (PUBLIC / "apps" / "app" / "index.html").read_text(encoding="utf-8")
    for expected in [
        "Spec onboarding AppOmar",
        "Sources",
        "Périmètres",
        "Classification",
        "Permissions agents",
        "Exclusions",
        "Garde-fou V0",
    ]:
        assert expected in app_page
    assert "aucune extraction texte V3" in app_page

