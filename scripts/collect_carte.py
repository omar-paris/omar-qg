#!/usr/bin/env python3
"""collect_carte.py — La Carte du puzzle OA (schéma oa.carte/1).

Vision Alex (07/07) : « visualiser l'ensemble de notre puzzle, toutes les
strates, où on en est, où on va » — une ligne par strate, sur chaque ligne
tous les modules, colorés, avec des KPI exigeants par case et par strate.

6 strates, chacune MAPPÉE depuis une source de vérité existante (rien inventé) :
  1. produit      — var/chantiers.json (8 briques PRODUCT-TRUTH 04/07)
  2. fonctionnel  — public/api/vps-app-inventory.json (apps par nœud VPS)
  3. technique    — contrôles OmarTop OBS-*/MAINT-*/TOO-* × verdicts vps-report
  4. securite     — contrôles SEC-*/GUARDRAIL/REDACT × verdicts + blocages sécurité
  5. data         — contrôles backup/restore/export/chiffrement (MAINT-*/REV-*)
  6. agents       — var/boucles.json (boucles fermées/partielles/ouvertes) + flotte

Règle des couleurs (exigence Alex — chaque couleur VIENT d'une source,
jamais peinte à la main) :
  vert  = mesuré ET conforme (PASS / écart nul / boucle fermée / app ok)
  jaune = partiel, ou mesuré UNKNOWN (la mesure existe mais ne conclut pas)
  rouge = FAIL / blocage / NO-GO / dégradé
  gris  = PAS ENCORE MESURÉ — jamais « acquis par défaut ». Le gris est une
          dette de mesure et il est affiché comme telle.

Sortie : var/carte.json (republié en /api/carte.json par build.py).
Read-only sur toutes les sources ; aucun réseau ; aucun secret (les preuves
proviennent des champs *_redacted des rapports).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

STANDARDS_DIR = Path("/home/omar/23-Offre/actifs/omar-top/standards")
LOCAL_VPS_REPORT_DIR = ROOT / "var" / "vps-reports"
INTER_VPS_INBOX = Path("/home/omar/11-Pilotage/sujets-actifs/inter-vps-inbox")
if os.environ.get("QG_USE_TEST_FIXTURES") == "1":
    # Cohérent avec build.py : fixtures exclusives pour un build déterministe.
    INTER_VPS_INBOX = ROOT / "tests" / "fixtures" / "inter-vps-inbox"

# Les nœuds attendus au rapport standards. Un nœud muet = dette de mesure (gris).
EXPECTED_NODES = ["omar", "jab", "pantheos"]

CHANTIERS_PATH = ROOT / "var" / "chantiers.json"
BOUCLES_PATH = ROOT / "var" / "boucles.json"
BLOCAGES_PATH = ROOT / "var" / "blocages.json"
FLEET_STATUS_PATH = ROOT / "var" / "fleet-status.json"
APP_INVENTORY_PATH = ROOT / "public" / "api" / "vps-app-inventory.json"
OUT_PATH = ROOT / "var" / "carte.json"

OMARTOP_URL = "https://top.omar.paris/"

# Répartition des contrôles OmarTop entre strates (un contrôle vit dans UNE
# seule strate — data et sécurité « réclament » leurs items avant technique).
_DATA_ID_RX = re.compile(r"BACKUP|RESTORE|EXPORT|ENCRYPT|ARCHIV|\bDB\b")
_SEC_ID_RX = re.compile(r"^SEC-|GUARDRAIL|REDACT")
_TECH_ID_RX = re.compile(r"^(OBS|MAINT|TOO)-")
_SEC_BLOCAGE_RX = re.compile(
    r"s[ée]curit|security|secret|redact|guardrail|\bufw\b|\bssh\b", re.IGNORECASE
)

VERDICT_COLOR = {"PASS": "vert", "FAIL": "rouge"}  # tout autre verdict mesuré → jaune
APP_STATUS_COLOR = {
    "ok": "vert",
    "outdated": "jaune",
    "unknown": "jaune",   # mesuré, mais la mesure ne conclut pas
    "missing": "rouge",
    "blocked": "rouge",
}

STRATES = [
    ("produit", "Produit / Funnel"),
    ("fonctionnel", "Fonctionnel / Apps"),
    ("technique", "Technique / Infra"),
    ("securite", "Sécurité"),
    ("data", "Data"),
    ("agents", "Agents / Boucles"),
]


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _cell(nom: str, strate: str, couleur: str, kpi_label: str, kpi_valeur: str,
          kpi_cible: str, kpi_source: str, lien: str, preuve: str = "") -> dict:
    return {
        "nom": nom,
        "strate": strate,
        "couleur": couleur,
        "kpi": {"label": kpi_label, "valeur": kpi_valeur, "cible": kpi_cible, "source": kpi_source},
        "lien": lien,
        "preuve": preuve,
    }


# ── Sources ───────────────────────────────────────────────────────────────────

def load_standards_controls() -> dict[str, dict]:
    """Contrôles OmarTop (type=controle) indexés par id.

    Les items « action » (…-00) sont prouvés via leur contrôle (…-01,
    champ satisfied_by) : la carte affiche les contrôles, pas les actions.
    """
    controls: dict[str, dict] = {}
    if not STANDARDS_DIR.exists():
        return controls
    for path in sorted(STANDARDS_DIR.glob("*.yml")):
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        for item in doc.get("items", []) or []:
            if isinstance(item, dict) and item.get("id") and item.get("type") == "controle":
                item = dict(item)
                item["_file"] = path.name
                controls[str(item["id"])] = item
    return controls


def load_vps_reports() -> tuple[dict[str, dict], list[str]]:
    """{node: {item_id: standard}} depuis les rapports oa.vps-report/v1.

    Retourne aussi la liste des nœuds attendus MUETS (aucun rapport) —
    ils deviennent des cellules grises : dette de mesure, pas un acquis.
    """
    reports: dict[str, dict] = {}

    def _keep(payload, fallback_node: str):
        if not isinstance(payload, dict) or payload.get("schema") != "oa.vps-report/v1":
            return
        node = str(payload.get("vps_id") or "").strip().lower().removeprefix("vps-") or fallback_node
        prev = reports.get(node)
        if not prev or str(payload.get("generated_at") or "") >= str(prev.get("generated_at") or ""):
            reports[node] = payload

    if LOCAL_VPS_REPORT_DIR.exists():
        for path in sorted(LOCAL_VPS_REPORT_DIR.glob("*.json")):
            _keep(_read_json(path), path.stem.split("-")[0].lower())
    for node in EXPECTED_NODES:
        _keep(_read_json(INTER_VPS_INBOX / node / "vps-report-latest.json"), node)

    verdicts: dict[str, dict] = {}
    for node, payload in reports.items():
        by_id = {}
        for std in payload.get("standards", []) or []:
            if isinstance(std, dict) and std.get("item_id"):
                by_id[str(std["item_id"])] = std
        verdicts[node] = by_id
    muets = [n for n in EXPECTED_NODES if n not in verdicts]
    return verdicts, muets


# ── Strates ───────────────────────────────────────────────────────────────────

def strate_produit(chantiers: list) -> list[dict]:
    cells = []
    for c in sorted(chantiers or [], key=lambda x: x.get("rang", 99)):
        nom = f"{c.get('rang', '?')}. {c.get('nom') or 'Brique'}"
        source = "var/chantiers.json (PRODUCT-TRUTH 04/07)"
        if c.get("decision_attendue"):
            couleur, valeur = "rouge", "décision Alex attendue"
        elif not str(c.get("ecart") or "").strip():
            if str(c.get("preuve") or "").strip():
                couleur, valeur = "vert", "aucun écart vs promesse"
            else:
                couleur, valeur = "gris", "jamais audité — dette de mesure"
        else:
            couleur, valeur = "jaune", f"écart documenté ({c.get('horizon') or '?'}, effort {c.get('effort') or '?'})"
        cells.append(_cell(
            nom, "produit", couleur,
            "écart vs promesse", valeur, "aucun écart", source,
            c.get("lien") or "/chantiers/", str(c.get("preuve") or ""),
        ))
    return cells


def strate_fonctionnel(inventory: dict) -> list[dict]:
    cells = []
    for node in (inventory or {}).get("nodes", []) or []:
        node_name = str(node.get("node") or "?")
        for app in node.get("apps", []) or []:
            status = str(app.get("status") or "").lower()
            couleur = APP_STATUS_COLOR.get(status, "gris")
            valeur = status if status else "aucun statut remonté"
            cells.append(_cell(
                f"{node_name} · {app.get('app_id') or app.get('name') or 'app'}",
                "fonctionnel", couleur,
                "statut app", valeur, "ok",
                f"vps-app-inventory.json · nœud {node_name}",
                "/clients/", str(app.get("evidence") or ""),
            ))
    return cells


def _standards_cells(strate: str, item_ids: list[str], controls: dict,
                     verdicts: dict[str, dict]) -> list[dict]:
    cells = []
    nodes = sorted(verdicts)
    for item_id in sorted(item_ids):
        label = str(controls.get(item_id, {}).get("client_label") or item_id)
        measured = False
        for node in nodes:
            std = verdicts[node].get(item_id)
            if not std:
                continue
            measured = True
            verdict = str(std.get("verdict") or "UNKNOWN").upper()
            couleur = VERDICT_COLOR.get(verdict, "jaune")
            cells.append(_cell(
                f"{item_id} @ {node}", strate, couleur,
                f"contrôle OmarTop — {label}", verdict, "PASS",
                f"vps-report {node} (oa.vps-report/v1)",
                OMARTOP_URL, str(std.get("proof_redacted") or ""),
            ))
        if not measured:
            cells.append(_cell(
                item_id, strate, "gris",
                f"contrôle OmarTop — {label}",
                "non mesuré sur aucun VPS", "PASS mesuré partout",
                f"omar-top/standards/{controls.get(item_id, {}).get('_file', '?')}",
                OMARTOP_URL, "",
            ))
    return cells


def strate_securite_blocages(blocages: dict) -> list[dict]:
    cells = []
    for b in (blocages or {}).get("blocages", []) or []:
        titre = str(b.get("titre") or "")
        if not _SEC_BLOCAGE_RX.search(titre):
            continue
        age = b.get("age_jours")
        # Preuve = texte COMPLET (action_1_ligne est tronquée en amont avec « … » ;
        # exigence Alex : zéro ellipsis dans les tooltips de la carte).
        preuve = str(b.get("texte_complet") or b.get("action_1_ligne") or "").rstrip("…").strip()
        cells.append(_cell(
            f"blocage : {titre}", "securite", "rouge",
            "blocage sécurité ouvert",
            f"ouvert depuis {age} j" if age is not None else "ouvert",
            "0 blocage sécurité", "var/blocages.json (kanban/PR/décisions)",
            b.get("lien") or "/blocages/", preuve,
        ))
    return cells


def strate_agents(boucles_doc: dict, fleet: dict) -> list[dict]:
    cells = []
    for b in (boucles_doc or {}).get("boucles", []) or []:
        fermeture = str(b.get("fermeture") or "")
        statut = str(b.get("statut") or "")
        if statut == "degrade":
            couleur, valeur = "rouge", f"dégradée ({fermeture or 'fermeture inconnue'})"
        elif fermeture in ("fermee", "fermee_manuellement"):
            couleur, valeur = "vert", fermeture
        elif fermeture == "partielle":
            couleur, valeur = "jaune", f"partielle ({statut or 'statut inconnu'})"
        else:
            couleur, valeur = "gris", f"sans check machine ({fermeture or 'ouverte'})"
        done_check = b.get("done_check") or {}
        cells.append(_cell(
            f"boucle · {b.get('nom') or b.get('id') or '?'}", "agents", couleur,
            "fermeture de boucle", valeur, "fermée (check machine)",
            "var/boucles.json (MANDAT-BOUCLES-060726)",
            "/api/boucles.json", str(done_check.get("detail") or ""),
        ))
    for src in (fleet or {}).get("sources", []) or []:
        status = str(src.get("status") or "").lower()
        if status == "ok":
            couleur = "vert"
        elif status.startswith("todo") or not status:
            couleur = "gris"
        elif "error" in status or "fail" in status:
            couleur = "rouge"
        else:
            couleur = "jaune"
        cells.append(_cell(
            f"flotte · {src.get('label') or src.get('id') or '?'}", "agents", couleur,
            "statut source flotte", status or "jamais interrogé", "ok",
            "var/fleet-status.json", "/clients/",
            str(src.get("heartbeat") or ""),
        ))
    return cells


# ── Assemblage ────────────────────────────────────────────────────────────────

def _strate_kpi(strate_id: str, cells: list[dict]) -> dict:
    n = {"vert": 0, "jaune": 0, "rouge": 0, "gris": 0}
    for c in cells:
        n[c["couleur"]] = n.get(c["couleur"], 0) + 1
    total = len(cells)
    mesure = total - n["gris"]
    labels = {
        "produit": ("briques sans écart vs promesse", "var/chantiers.json"),
        "fonctionnel": ("apps ok sur la flotte", "vps-app-inventory.json"),
        "technique": ("contrôles PASS (sur mesurés)", "omar-top × vps-reports"),
        "securite": ("contrôles/blocages sécurité conformes", "omar-top × vps-reports × blocages"),
        "data": ("contrôles data PASS (sur mesurés)", "omar-top × vps-reports"),
        "agents": ("boucles fermées + flotte ok", "var/boucles.json × fleet-status"),
    }
    label, source = labels.get(strate_id, ("modules conformes", "carte"))
    valeur = f"{n['vert']}/{mesure} conformes"
    if mesure:
        valeur += f" ({round(100 * n['vert'] / mesure)}%)"
    if n["gris"]:
        valeur += f" · {n['gris']} non mesuré(s)"
    return {
        "label": label,
        "valeur": valeur,
        "cible": "100% mesuré, 100% du mesuré conforme",
        "source": source,
        "compteurs": {**n, "total": total, "mesure": mesure},
    }


def collect(write: bool = False, app_inventory: dict | None = None) -> dict:
    """Assemble la carte. `app_inventory` : inventaire frais calculé par build.py
    (sinon fallback sur le snapshot public/api/vps-app-inventory.json du build
    précédent — usage CLI standalone)."""
    generated_at = _now_iso()
    errors: list[str] = []

    controls = load_standards_controls()
    if not controls:
        errors.append("standards_omar_top_absents")
    verdicts, muets = load_vps_reports()
    chantiers = _read_json(CHANTIERS_PATH) or []
    boucles_doc = _read_json(BOUCLES_PATH) or {}
    blocages = _read_json(BLOCAGES_PATH) or {}
    fleet = _read_json(FLEET_STATUS_PATH) or {}
    inventory = app_inventory if isinstance(app_inventory, dict) and app_inventory.get("nodes") \
        else (_read_json(APP_INVENTORY_PATH) or {})
    if not chantiers:
        errors.append("chantiers_absents")
    if not (inventory or {}).get("nodes"):
        errors.append("vps_app_inventory_absent")

    # Répartition des contrôles : data et sécurité réclament leurs items,
    # technique prend le reste des OBS-*/MAINT-*/TOO-*.
    data_ids = [i for i in controls if _DATA_ID_RX.search(i)]
    sec_ids = [i for i in controls if _SEC_ID_RX.search(i) and i not in data_ids]
    tech_ids = [i for i in controls
                if _TECH_ID_RX.match(i) and i not in data_ids and i not in sec_ids]

    cells_technique = _standards_cells("technique", tech_ids, controls, verdicts)
    for node in muets:
        cells_technique.append(_cell(
            f"VPS {node} — rapport absent", "technique", "gris",
            "rapport oa.vps-report/v1", "aucun rapport reçu", "rapport quotidien",
            "inter-vps-inbox", "/clients/", "",
        ))

    strate_cells = {
        "produit": strate_produit(chantiers),
        "fonctionnel": strate_fonctionnel(inventory),
        "technique": cells_technique,
        "securite": _standards_cells("securite", sec_ids, controls, verdicts)
                     + strate_securite_blocages(blocages),
        "data": _standards_cells("data", data_ids, controls, verdicts),
        "agents": strate_agents(boucles_doc, fleet),
    }

    strates = []
    tot = {"vert": 0, "jaune": 0, "rouge": 0, "gris": 0}
    for ordre, (sid, nom) in enumerate(STRATES, start=1):
        cells = strate_cells[sid]
        kpi = _strate_kpi(sid, cells)
        for c in cells:
            tot[c["couleur"]] += 1
        strates.append({"id": sid, "nom": nom, "ordre": ordre, "kpi": kpi, "modules": cells})

    total = sum(tot.values())
    mesurees = total - tot["gris"]
    pct_mesure = round(100 * mesurees / total) if total else 0
    pct_conforme = round(100 * tot["vert"] / mesurees) if mesurees else 0
    carte = {
        "schema": "oa.carte/1",
        "generated_at": generated_at,
        "regle_couleurs": {
            "vert": "mesuré ET conforme (PASS / écart nul / boucle fermée / app ok)",
            "jaune": "partiel ou UNKNOWN mesuré — la mesure existe mais ne conclut pas",
            "rouge": "FAIL / blocage / NO-GO / dégradé",
            "gris": "pas encore mesuré — dette de mesure, jamais un acquis par défaut",
        },
        "kpi_global": {
            "cellules": total,
            "mesurees": mesurees,
            "conformes": tot["vert"],
            "pct_mesure": pct_mesure,
            "pct_conforme_du_mesure": pct_conforme,
            "compteurs": {**tot, "total": total},
            "libelle": f"puzzle mesuré à {pct_mesure} % · conforme à {pct_conforme} % du mesuré",
        },
        "strates": strates,
        "errors": errors,
    }
    if write:
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(json.dumps(carte, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return carte


if __name__ == "__main__":
    payload = collect(write=True)
    g = payload["kpi_global"]
    print(f"carte: {g['cellules']} cellules · {g['libelle']}")
    for s in payload["strates"]:
        print(f"  {s['nom']}: {s['kpi']['valeur']}")
