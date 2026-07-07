"""Carte du puzzle (vision Alex 07/07) : tests purs de scripts/collect_carte.py
sur fixtures — aucun réseau, aucune source réelle. Vérifie la règle des
couleurs (vert=mesuré conforme, jaune=partiel/UNKNOWN mesuré, rouge=FAIL/blocage,
gris=jamais mesuré = dette de mesure, jamais un acquis) et l'honnêteté du KPI
global (2 chiffres : % mesuré, % conforme du mesuré).
"""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_collect_carte():
    spec = importlib.util.spec_from_file_location(
        "collect_carte_test", ROOT / "scripts" / "collect_carte.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_fixtures(tmp_path: Path, m):
    standards = tmp_path / "standards"
    standards.mkdir()
    (standards / "mixte.yml").write_text(
        json.dumps({  # JSON est du YAML valide — fixture lisible et sans ambiguïté
            "items": [
                {"id": "OBS-DISK-01", "type": "controle", "client_label": "Disque sous contrôle"},
                {"id": "MAINT-RESTORE-01", "type": "controle", "client_label": "Restauration prouvée"},
                {"id": "SEC-UFW-01", "type": "controle", "client_label": "Pare-feu actif"},
                {"id": "TOO-GUARDRAIL-01", "type": "controle", "client_label": "Guardrails actifs"},
                {"id": "TOO-RESOURCES-01", "type": "controle", "client_label": "Ressources suivies"},
                {"id": "SEC-UFW-00", "type": "action", "client_label": "Pare-feu configuré"},
            ]
        }, ensure_ascii=False), encoding="utf-8")

    local_reports = tmp_path / "vps-reports"
    local_reports.mkdir()
    (local_reports / "omar.json").write_text(json.dumps({
        "schema": "oa.vps-report/v1", "vps_id": "vps-omar", "generated_at": "2026-07-07T10:00:00Z",
        "standards": [
            {"item_id": "OBS-DISK-01", "verdict": "PASS", "proof_redacted": "disk 40% < 85%"},
            {"item_id": "MAINT-RESTORE-01", "verdict": "FAIL", "proof_redacted": "no restore evidence"},
            {"item_id": "TOO-GUARDRAIL-01", "verdict": "UNKNOWN", "proof_redacted": "check timed out"},
        ],
    }, ensure_ascii=False), encoding="utf-8")

    inbox = tmp_path / "inbox"
    (inbox / "jab").mkdir(parents=True)
    (inbox / "jab" / "vps-report-latest.json").write_text(json.dumps({
        "schema": "oa.vps-report/v1", "vps_id": "vps-jab", "generated_at": "2026-07-07T10:00:00Z",
        "standards": [{"item_id": "OBS-DISK-01", "verdict": "PASS", "proof_redacted": "disk ok"}],
    }, ensure_ascii=False), encoding="utf-8")
    # pantheos attendu mais MUET → cellule grise « rapport absent »

    (tmp_path / "chantiers.json").write_text(json.dumps([
        {"rang": 1, "nom": "Onboarding client", "horizon": "now", "effort": "M",
         "ecart": "routes vides", "preuve": "routes-active.yaml", "lien": None, "decision_attendue": None},
        {"rang": 2, "nom": "Devis", "horizon": "now", "effort": "S",
         "ecart": "jamais éprouvé", "preuve": "", "lien": None, "decision_attendue": "GO paiement réel"},
        {"rang": 3, "nom": "Audit", "horizon": "next", "effort": "S",
         "ecart": "", "preuve": "curl 200 public", "lien": "https://app.omar.paris/audit/", "decision_attendue": None},
    ], ensure_ascii=False), encoding="utf-8")

    (tmp_path / "boucles.json").write_text(json.dumps({
        "schema": "oa.boucles/1",
        "boucles": [
            {"id": "b1", "nom": "Backup nightly", "fermeture": "fermee", "statut": "actif",
             "done_check": {"detail": "check machine OK"}},
            {"id": "b2", "nom": "Digest 09h/18h", "fermeture": "partielle", "statut": "actif", "done_check": {}},
            {"id": "b3", "nom": "Triage kanban", "fermeture": "partielle", "statut": "degrade", "done_check": {}},
            {"id": "b4", "nom": "Vieux cron mystere", "fermeture": "ouverte", "statut": "legacy_a_trancher", "done_check": {}},
        ],
    }, ensure_ascii=False), encoding="utf-8")

    (tmp_path / "blocages.json").write_text(json.dumps({
        "compteurs": {}, "blocages": [
            {"id": "pr:hub#56", "titre": "omar-hub#56 — cover vault scanner secret redaction",
             "age_jours": 22, "lien": "https://github.com/omar-paris/omar-hub/pull/56",
             "action_1_ligne": "reviewer puis merger la PR qui couvre le scanner de…",
             "texte_complet": "reviewer puis merger la PR qui couvre le scanner de secrets du vault"},
            {"id": "carte:t_1", "titre": "[QG] page ops cassée", "age_jours": 1,
             "lien": "", "action_1_ligne": "sans rapport sécurité"},
        ],
    }, ensure_ascii=False), encoding="utf-8")

    (tmp_path / "fleet-status.json").write_text(json.dumps({
        "sources": [
            {"id": "jab", "label": "VPS JAB", "status": "ok", "heartbeat": "2026-07-07T10:00:00Z"},
            {"id": "pantheos", "label": "Pantheos", "status": "todo_define_hub_status_contract"},
        ],
    }, ensure_ascii=False), encoding="utf-8")

    (tmp_path / "vps-app-inventory.json").write_text(json.dumps({
        "nodes": [{"node": "jab", "apps": [
            {"app_id": "hermes", "status": "ok", "evidence": "service actif"},
            {"app_id": "omarhub", "status": "unknown", "evidence": ""},
            {"app_id": "inter-vps-reporter", "status": "missing", "evidence": ""},
        ]}],
    }, ensure_ascii=False), encoding="utf-8")

    m.STANDARDS_DIR = standards
    m.LOCAL_VPS_REPORT_DIR = local_reports
    m.INTER_VPS_INBOX = inbox
    m.EXPECTED_NODES = ["omar", "jab", "pantheos"]
    m.CHANTIERS_PATH = tmp_path / "chantiers.json"
    m.BOUCLES_PATH = tmp_path / "boucles.json"
    m.BLOCAGES_PATH = tmp_path / "blocages.json"
    m.FLEET_STATUS_PATH = tmp_path / "fleet-status.json"
    m.APP_INVENTORY_PATH = tmp_path / "vps-app-inventory.json"
    m.OUT_PATH = tmp_path / "carte.json"


def _cells(carte, strate_id):
    return {c["nom"]: c for s in carte["strates"] if s["id"] == strate_id for c in s["modules"]}


def test_carte_schema_and_strates_order(tmp_path):
    m = _load_collect_carte()
    _write_fixtures(tmp_path, m)
    carte = m.collect(write=True)
    assert carte["schema"] == "oa.carte/1"
    assert [s["id"] for s in carte["strates"]] == [
        "produit", "fonctionnel", "technique", "securite", "data", "agents"]
    assert [s["ordre"] for s in carte["strates"]] == [1, 2, 3, 4, 5, 6]
    # write=True publie le snapshot
    on_disk = json.loads((tmp_path / "carte.json").read_text(encoding="utf-8"))
    assert on_disk["kpi_global"] == carte["kpi_global"]
    # la règle des couleurs est écrite dans le payload (légende de la page)
    assert set(carte["regle_couleurs"]) == {"vert", "jaune", "rouge", "gris"}


def test_couleurs_viennent_des_sources_jamais_peintes(tmp_path):
    m = _load_collect_carte()
    _write_fixtures(tmp_path, m)
    carte = m.collect()

    produit = _cells(carte, "produit")
    assert produit["1. Onboarding client"]["couleur"] == "jaune"      # écart documenté
    assert produit["2. Devis"]["couleur"] == "rouge"                  # décision Alex attendue
    assert produit["3. Audit"]["couleur"] == "vert"                   # écart nul + preuve

    fonctionnel = _cells(carte, "fonctionnel")
    assert fonctionnel["jab · hermes"]["couleur"] == "vert"
    assert fonctionnel["jab · omarhub"]["couleur"] == "jaune"         # unknown mesuré
    assert fonctionnel["jab · inter-vps-reporter"]["couleur"] == "rouge"

    technique = _cells(carte, "technique")
    assert technique["OBS-DISK-01 @ omar"]["couleur"] == "vert"       # PASS
    assert technique["OBS-DISK-01 @ jab"]["couleur"] == "vert"
    assert technique["TOO-RESOURCES-01"]["couleur"] == "gris"         # jamais mesuré
    assert technique["VPS pantheos — rapport absent"]["couleur"] == "gris"

    securite = _cells(carte, "securite")
    assert securite["SEC-UFW-01"]["couleur"] == "gris"                # catalogue non mesuré
    assert securite["TOO-GUARDRAIL-01 @ omar"]["couleur"] == "jaune"  # UNKNOWN mesuré
    sec_blocages = [n for n in securite if n.startswith("blocage :")]
    assert sec_blocages == ["blocage : omar-hub#56 — cover vault scanner secret redaction"]
    assert securite[sec_blocages[0]]["couleur"] == "rouge"
    # le blocage non-sécurité ne fuit pas dans la strate
    assert not any("page ops" in n for n in securite)

    data = _cells(carte, "data")
    assert data["MAINT-RESTORE-01 @ omar"]["couleur"] == "rouge"      # FAIL
    # MAINT-RESTORE est réclamé par data : pas de doublon en technique
    assert "MAINT-RESTORE-01 @ omar" not in technique

    agents = _cells(carte, "agents")
    assert agents["boucle · Backup nightly"]["couleur"] == "vert"
    assert agents["boucle · Digest 09h/18h"]["couleur"] == "jaune"
    assert agents["boucle · Triage kanban"]["couleur"] == "rouge"     # statut degrade
    assert agents["boucle · Vieux cron mystere"]["couleur"] == "gris" # sans check machine
    assert agents["flotte · VPS JAB"]["couleur"] == "vert"
    assert agents["flotte · Pantheos"]["couleur"] == "gris"           # todo = jamais mesuré

    # les items « action » (…-00) ne sont jamais des cellules (prouvés via -01)
    all_names = [c["nom"] for s in carte["strates"] for c in s["modules"]]
    assert not any("SEC-UFW-00" in n for n in all_names)


def test_kpi_global_honnetete_du_gris(tmp_path):
    m = _load_collect_carte()
    _write_fixtures(tmp_path, m)
    carte = m.collect()
    g = carte["kpi_global"]
    cells = [c for s in carte["strates"] for c in s["modules"]]
    gris = sum(1 for c in cells if c["couleur"] == "gris")
    verts = sum(1 for c in cells if c["couleur"] == "vert")
    assert g["cellules"] == len(cells)
    assert g["mesurees"] == len(cells) - gris          # le gris n'est JAMAIS compté mesuré
    assert g["conformes"] == verts                     # seul le vert est conforme
    assert g["pct_mesure"] == round(100 * g["mesurees"] / g["cellules"])
    assert g["pct_conforme_du_mesure"] == round(100 * verts / g["mesurees"])
    assert f"puzzle mesuré à {g['pct_mesure']} %" in g["libelle"]
    # chaque strate porte un KPI complet {label, valeur, cible, source}
    for s in carte["strates"]:
        for key in ("label", "valeur", "cible", "source"):
            assert s["kpi"][key], (s["id"], key)
    # chaque cellule porte un KPI sourcé et une couleur légale
    for c in cells:
        assert c["couleur"] in ("vert", "jaune", "rouge", "gris")
        assert c["kpi"]["source"], c["nom"]
        assert "…" not in json.dumps(c, ensure_ascii=False)  # zéro ellipsis (tooltips)


def test_app_inventory_frais_prioritaire_sur_snapshot(tmp_path):
    # build.py passe l'inventaire FRAIS calculé dans le même build ; le snapshot
    # public/ (build précédent) ne doit servir qu'en fallback CLI standalone.
    m = _load_collect_carte()
    _write_fixtures(tmp_path, m)
    frais = {"nodes": [{"node": "omar", "apps": [
        {"app_id": "caddy", "status": "ok", "evidence": "vhost actif"},
    ]}]}
    carte = m.collect(app_inventory=frais)
    fonctionnel = _cells(carte, "fonctionnel")
    assert list(fonctionnel) == ["omar · caddy"]
    # inventaire frais vide/invalide → fallback snapshot
    carte = m.collect(app_inventory={"nodes": []})
    assert "jab · hermes" in _cells(carte, "fonctionnel")


def test_sources_absentes_ne_cassent_pas(tmp_path):
    m = _load_collect_carte()
    _write_fixtures(tmp_path, m)
    m.STANDARDS_DIR = tmp_path / "nulle-part"
    m.CHANTIERS_PATH = tmp_path / "nulle-part.json"
    m.APP_INVENTORY_PATH = tmp_path / "nulle-part.json"
    carte = m.collect()
    assert carte["schema"] == "oa.carte/1"
    assert "standards_omar_top_absents" in carte["errors"]
    assert "chantiers_absents" in carte["errors"]
    assert "vps_app_inventory_absent" in carte["errors"]
    assert len(carte["strates"]) == 6
