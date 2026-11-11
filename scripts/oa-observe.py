#!/usr/bin/env python3
"""oa-observe — observateur PROACTIF de la flotte OA.

Pourquoi : le 11 juin, un worker Hermes a créé ~142 000 sessions parasites sur
le VPS-JAB pendant 3 semaines (base passée à 3 Go) sans que personne ne le voie ;
c'est Alex qui a fini par le remarquer à la main. Cet outil est le système qui
aurait dû l'attraper : il scanne la flotte tous les jours, remonte les anomalies
ET des observations intéressantes, et écrit un briefing lisible — Alex n'a plus à
lancer les inputs.

Principes :
- 100% LECTURE SEULE sur les VPS observés. La seule écriture est le rapport de
  sortie, sur le VPS-Omar (journal/observateur/).
- Python 3, stdlib uniquement (pas de pip). SSH via subprocess `ssh <host> '...'`.
- Timeouts partout : un VPS muet ne doit jamais bloquer le scan.
- Idempotent, ré-exécutable. Ajouter un VPS = une ligne dans TARGETS.

Usage :
  python3 oa-observe.py                 # scan complet, écrit le briefing + résumé stdout
  python3 oa-observe.py --stdout-only    # pas d'écriture fichier, juste le résumé
  python3 oa-observe.py --only file_bloat,ram_swap   # sous-ensemble de détecteurs
  python3 oa-observe.py --json           # dump JSON des findings (debug)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

try:
    from swap_pressure import classify_swap_pressure, is_real_swap_pressure
except ModuleNotFoundError:  # import par tests depuis la racine du dépôt
    from scripts.swap_pressure import classify_swap_pressure, is_real_swap_pressure

# --------------------------------------------------------------------------- #
# CIBLES DE LA FLOTTE — ajouter un VPS = ajouter une entrée ici.
# mode "local"  : commandes exécutées directement (VPS hôte = VPS-Omar)
# mode "ssh"    : commandes préfixées par `ssh <host> '...'` (lecture seule, root OK)
# homes         : comptes système hébergeant des agents/apps sur ce VPS
# --------------------------------------------------------------------------- #
TARGETS = [
    {
        "name": "VPS-Omar",
        "mode": "local",
        "host": None,
        "homes": ["/home/omar"],
        "backup_logs": [
            {"path": "/var/log/oadmin-backup.log", "scope": "primary", "label": "legacy oadmin"},
            {
                "path": "/home/omar/23-Offre/actifs/omar-top/state/compliance/omar/backup.log",
                "scope": "primary",
                "label": "Omar T1 manifest",
            },
            {
                "path": "/home/omar/4-Infra/logs/pull-backup-jab.log",
                "scope": "client",
                "label": "JAB pull",
            },
        ],
    },
    {
        "name": "VPS-JAB",
        "mode": "ssh",
        "host": "jab",
        "homes": ["/home/edilia", "/home/oa-admin"],
        "backup_logs": ["/var/log/oa-backup-daily.log"],
    },
    # Exemple pour un futur VPS :
    # {"name": "VPS-Pantheos", "mode": "ssh", "host": "pantheos",
    #  "homes": ["/home/aurel"], "backup_logs": ["/var/log/oa-backup-daily.log"]},
]

# Seuils (centralisés pour ajustement facile)
BLOAT_WARN = 500 * 1024**2     # 500 Mo  -> P1 générique
# Hermes state.db embarque l'historique + FTS/trigram: après cleanup sain du
# 2026-07-03, la baseline VPS-Omar est ~407 MiB. On garde une marge non
# destructrice (~1.9x baseline) avant d'alerter, sans masquer le seuil P0 2 GiB
# hérité de l'incident 3 Go du 11/06.
HERMES_STATE_DB_BLOAT_WARN = 768 * 1024**2  # 768 MiB -> P1 spécifique state.db
BLOAT_CRIT = 2 * 1024**3       # 2 Go    -> P0
SESS_WARN = 1_000              # P1
SESS_CRIT = 10_000            # P0
SESS_RATE_WARN = 200          # sessions créées dans la dernière heure -> P1
RAM_AVAIL_CRIT = 400          # Mo available -> P0
SWAP_PCT_WARN = 80            # % swap utilisé, à qualifier par pression -> P1
BACKUP_WARN_H = 36            # h sans backup OK -> P1
KANBAN_RUNNING_H = 6          # tâche running > 6h -> P1
REPO_IDLE_DAYS = 5           # commit le plus récent > 5j + 0 issue -> P2
REPO_DIRTY_H = 24            # fichiers non commités depuis > 24h -> P1
CERT_EXPIRY_DAYS = 14        # cert expirant dans < 14j -> P1
DEFAULT_TIMEOUT = 30
SSH_OPTS = ["-o", "ConnectTimeout=10", "-o", "BatchMode=yes"]
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KANBAN_STATE = ROOT / "var" / "oa-observe-kanban-state.json"
# Registre d'intention par repo (gitignoré via .gitignore:8 `var/`). Il porte la
# décision humaine « ce repo est idle parce qu'il est FIGÉ volontairement » et
# permet de distinguer un gel décidé d'un abandon. Voir carte t_d1d22bf2.
DEFAULT_REPO_INTENT = ROOT / "var" / "repo-intent.json"
REPO_INTENT_SCHEMA = "oa.repo-intent/1"
# Sévérités qui deviennent des cartes Kanban. Les notices INFO restent dans le
# briefing (une carte `ready` serait dispatchée à un worker pour rien).
KANBAN_SYNCED_SEVERITIES = ("P0", "P1", "P2")
# Racine des checkouts d'apps inspectés par det_repo_idle (surchargeable en test).
REPOS_BASE = Path("/home/omar/23-Offre/actifs")
HERMES = Path.home() / ".local/bin/hermes"

# Notes de scan alimentées par les détecteurs (ex: diagnostic d'un `gh` en
# échec). Vidées au début de chaque scan() puis fusionnées dans les notes.
SCAN_NOTES: list[str] = []

# Répertoires exclus de la bloat : dépendances build (node_modules/venv) ET
# copies volontaires (backups, snapshots, incidents) qui dupliquent une base
# saine — on ne veut alerter que sur la base VIVANTE qui gonfle.
EXCLUDE_BLOAT_DIRS = ("node_modules", "venv", ".venv", "site-packages",
                      "__pycache__", ".git", "image_cache", "audio_cache",
                      "backups", "state-snapshots", "incidents", "forensics",
                      "_archived")


# --------------------------------------------------------------------------- #
@dataclass
class Finding:
    severite: str           # "P0" | "P1" | "P2"
    titre: str
    detail: str
    vps: str
    remediation: str
    detecteur: str = ""

    def order(self) -> int:
        return {"P0": 0, "P1": 1, "P2": 2}.get(self.severite, 3)


@dataclass
class Observation:
    """Phrase qui ouvre une conversation avec Alex (pas une alarme)."""
    texte: str
    vps: str = ""


# --------------------------------------------------------------------------- #
# STRUCTURATION + SINK KANBAN
# --------------------------------------------------------------------------- #
def _slug_part(value: str) -> str:
    """Segment sûr pour idempotency_key Hermes (lisible, stable, sans espaces)."""
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    return slug.strip("-") or "unknown"


def finding_fingerprint(f: Finding) -> str:
    """Empreinte stable du finding, avec normalisation limitée au swap.

    Les mesures de ``ram_swap`` varient pendant un même incident. Les autres
    détecteurs peuvent signaler plusieurs incidents simultanés, donc leur titre
    et détail restent dans l'empreinte pour préserver une carte par incident.

    Exception ``repo_idle`` : le titre porte des mesures qui bougent toutes
    seules (nombre de jours sans commit, nombre de fichiers sales). Les inclure
    dans l'empreinte créait une carte NOUVELLE chaque jour pour le même repo —
    c'est la cause racine des doublons constatés avant la pause du 2026-09-24.
    On ancre donc l'empreinte sur le nom du repo (préfixe du titre), ce qui
    garde une carte par repo et par sévérité, stable dans le temps.
    """
    payload = {
        "severite": f.severite,
        "vps": f.vps,
        "detecteur": f.detecteur or "unknown",
    }
    if f.detecteur == "repo_idle":
        # titre = "<repo> : <mesure volatile>"
        payload["scope"] = f.titre.split(" : ", 1)[0].strip() or "unknown"
    elif f.detecteur != "ram_swap":
        payload["titre"] = f.titre
        payload["detail"] = f.detail
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def finding_idempotency_key(f: Finding) -> str:
    return "oa-observe:{target}:{detector}:{fingerprint}".format(
        target=_slug_part(f.vps),
        detector=_slug_part(f.detecteur or "unknown"),
        fingerprint=finding_fingerprint(f),
    )


def structured_finding(f: Finding) -> dict:
    payload = asdict(f)
    payload["schema"] = "oa.observe.finding/1"
    payload["fingerprint"] = finding_fingerprint(f)
    payload["idempotency_key"] = finding_idempotency_key(f)
    return payload


def _card_title(f: Finding) -> str:
    return f"[OBS][{f.severite}] {f.vps} — {f.titre}"[:120]


def _card_body(f: Finding, *, key: str, now_ts: int) -> str:
    return "\n".join([
        "Alerte persistante créée par oa-observe.",
        "",
        f"idempotency_key: {key}",
        f"detector: {f.detecteur or 'unknown'}",
        f"target: {f.vps}",
        f"severity: {f.severite}",
        f"first_seen_or_updated_at: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now_ts))}",
        "",
        "## Détail",
        f.detail,
        "",
        "## Remédiation proposée",
        f.remediation,
        "",
        "## Protocole résolution",
        "Quand oa-observe ne revoit plus cette alerte, il commente la carte puis la clôture automatiquement.",
    ])


def load_kanban_state(path: Path = DEFAULT_KANBAN_STATE) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def save_kanban_state(state: dict, path: Path = DEFAULT_KANBAN_STATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def load_repo_intent(path: Path | str | None = None) -> dict[str, dict]:
    """Charge le registre d'intention par repo (schéma ``oa.repo-intent/1``).

    Retourne ``{slug: entrée}``. Fichier absent, illisible ou schéma inconnu =>
    ``{}`` : le scan retombe alors sur le comportement historique (aucun repo
    n'est considéré comme figé par défaut). Un registre cassé ne doit jamais
    faire taire une alerte.
    """
    p = Path(path) if path else DEFAULT_REPO_INTENT
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    if not isinstance(payload, dict):
        return {}
    schema = payload.get("schema")
    if schema and schema != REPO_INTENT_SCHEMA:
        SCAN_NOTES.append(
            f"registre d'intention ignoré : schéma {schema!r} != {REPO_INTENT_SCHEMA!r} ({p})")
        return {}
    repos = payload.get("repos")
    if not isinstance(repos, dict):
        return {}
    return {str(k): v for k, v in repos.items() if isinstance(v, dict)}


def repo_intent_of(name: str, registry: dict[str, dict] | None = None) -> str:
    """Intention déclarée pour un repo : ``frozen``, ``active`` ou ``""``."""
    entry = (registry or {}).get(name) or {}
    return str(entry.get("intent") or "").strip().lower()


_OPEN_BOARD_STATUSES_EXCLUDED = {"done", "archived"}
_IDEMPOTENCY_RE = re.compile(r"^idempotency_key:\s*(\S+)\s*$", re.MULTILINE)


def _idempotency_key_from_body(body: str) -> str | None:
    m = _IDEMPOTENCY_RE.search(body or "")
    return m.group(1) if m else None


def list_observe_board_cards(runner=subprocess.run, *,
                             statuses: tuple[str, ...] = ()) -> list[dict]:
    """Liste les cartes Kanban ENCORE OUVERTES créées par oa-observe.

    Source de vérité de la réconciliation : le board, pas le fichier d'état
    local. La clé d'idempotence n'est pas exposée par `kanban list --json`, on
    la relit donc dans le corps de la carte (elle y est écrite par
    ``_card_body``). Toute erreur => liste vide (dégradation propre).
    """
    cmd = [str(HERMES), "kanban", "list", "--json"]
    try:
        cp = runner(cmd, capture_output=True, text=True, timeout=60)
    except Exception:  # noqa: BLE001
        return []
    if getattr(cp, "returncode", 1) != 0:
        return []
    try:
        tasks = json.loads(getattr(cp, "stdout", "") or "[]")
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(tasks, list):
        return []
    out: list[dict] = []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        if t.get("created_by") != "oa-observe":
            continue
        status = str(t.get("status") or "")
        if status in _OPEN_BOARD_STATUSES_EXCLUDED:
            continue
        if statuses and status not in statuses:
            continue
        key = _idempotency_key_from_body(str(t.get("body") or ""))
        out.append({
            "task_id": t.get("id"),
            "idempotency_key": key,
            "title": t.get("title"),
            "status": status,
        })
    return out


def _key_detector(key: str) -> str:
    """Détecteur porté par une clé d'idempotence ``oa-observe:<vps>:<det>:<fp>``."""
    parts = str(key or "").split(":")
    return parts[2] if len(parts) >= 4 else ""


def plan_kanban_sync(findings: list[Finding], previous: dict | None = None,
                     now_ts: int | None = None,
                     board_cards: list[dict] | None = None,
                     scanned_detectors: set[str] | None = None) -> tuple[list[dict], dict]:
    """Planifie create/update/resolve sans toucher au Kanban.

    ``previous`` (fichier d'état local) n'est qu'un CACHE. ``board_cards`` est
    la liste des cartes oa-observe encore ouvertes sur le board : toute carte
    dont la clé n'apparaît plus dans les findings courants est un candidat
    ``resolve``, même si le fichier d'état est vide, perdu ou restauré. Sans
    cette réconciliation, une carte dont la clé est absente du state restait
    ouverte indéfiniment (cas des cartes OBS `repo_idle`).

    ``scanned_detectors`` borne la réconciliation aux détecteurs réellement
    exécutés : un scan partiel (``--only repo_idle``) ne doit JAMAIS clore les
    cartes des détecteurs qu'il n'a pas mesurés (sinon un scan ciblé fermerait
    tout le reste du board). ``None`` = tous les détecteurs.
    """
    previous = previous or {}
    now_ts = int(now_ts or time.time())
    state = dict(previous)
    plan: list[dict] = []
    active_keys: set[str] = set()
    for f in findings:
        # Seuls les findings actionnables deviennent des cartes. Les notices
        # informatives (ex: `repo_intent_frozen` en INFO) restent dans le
        # briefing : une carte `ready` serait dispatchée à un worker pour rien.
        if f.severite not in KANBAN_SYNCED_SEVERITIES:
            continue
        key = finding_idempotency_key(f)
        active_keys.add(key)
        prev = previous.get(key, {}) if isinstance(previous.get(key), dict) else {}
        action = "update" if prev.get("status") == "active" else "create"
        plan.append({
            "action": action,
            "idempotency_key": key,
            "task_id": prev.get("task_id"),
            "title": _card_title(f),
            "finding": structured_finding(f),
        })
        state[key] = {
            "status": "active",
            "task_id": prev.get("task_id"),
            "title": f.titre,
            "target": f.vps,
            "detector": f.detecteur or "unknown",
            "severity": f.severite,
            "first_seen_at": prev.get("first_seen_at", now_ts),
            "last_seen_at": now_ts,
        }

    # Le board peut connaître le task_id que le state a perdu : on le récupère
    # pour que les resolve suivants puissent cibler la carte.
    def _in_scope(key: str) -> bool:
        if scanned_detectors is None:
            return True
        det = _key_detector(key)
        return not det or det in scanned_detectors

    board_by_key: dict[str, dict] = {}
    for card in board_cards or []:
        key = card.get("idempotency_key")
        if not key or not card.get("task_id"):
            continue
        if not _in_scope(key):
            continue
        board_by_key.setdefault(key, card)
        if key in state and isinstance(state[key], dict) and not state[key].get("task_id"):
            state[key]["task_id"] = card["task_id"]
        if key in active_keys:
            for op in plan:
                if op["idempotency_key"] == key and not op.get("task_id"):
                    op["task_id"] = card["task_id"]

    already_planned: set[str] = set()
    for key, prev in previous.items():
        if key in active_keys or not isinstance(prev, dict) or prev.get("status") != "active":
            continue
        if not _in_scope(key):
            continue
        plan.append({
            "action": "resolve",
            "idempotency_key": key,
            "task_id": prev.get("task_id") or (board_by_key.get(key) or {}).get("task_id"),
            "title": prev.get("title", key),
        })
        already_planned.add(key)
        resolved = dict(prev)
        resolved["status"] = "resolved"
        resolved["resolved_at"] = now_ts
        state[key] = resolved

    # Réconciliation board : cartes ouvertes dont la clé n'est plus un finding.
    for key, card in board_by_key.items():
        if key in active_keys or key in already_planned:
            continue
        plan.append({
            "action": "resolve",
            "idempotency_key": key,
            "task_id": card.get("task_id"),
            "title": card.get("title", key),
            "source": "board",
        })
        already_planned.add(key)
        resolved = dict(previous.get(key) or {})
        resolved.update({
            "status": "resolved",
            "resolved_at": now_ts,
            "task_id": card.get("task_id"),
            "title": card.get("title", key),
            "detector": (previous.get(key) or {}).get("detector", "unknown"),
        })
        state[key] = resolved

    return plan, state


def _parse_task_id(stdout: str) -> str | None:
    text = (stdout or "").strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
        for k in ("task_id", "id"):
            if payload.get(k):
                return str(payload[k])
        if isinstance(payload.get("task"), dict) and payload["task"].get("id"):
            return str(payload["task"]["id"])
    except Exception:  # noqa: BLE001
        pass
    m = re.search(r"\bt_[0-9a-fA-F]+\b", text)
    return m.group(0) if m else None


def apply_kanban_plan(plan: list[dict], state: dict, findings_by_key: dict[str, Finding],
                      *, dry_run: bool = False, assignee: str = "default",
                      priority: int = 85, runner=subprocess.run) -> tuple[list[dict], dict]:
    results: list[dict] = []
    for op in plan:
        if dry_run:
            results.append({k: op.get(k) for k in
                            ("action", "idempotency_key", "task_id", "title", "source")})
            continue
        action = op["action"]
        key = op["idempotency_key"]
        if action in {"create", "update"}:
            finding = findings_by_key[key]
            cmd = [str(HERMES), "kanban", "create", _card_title(finding),
                   "--assignee", assignee, "--priority", str(priority),
                   "--idempotency-key", key, "--body",
                   _card_body(finding, key=key, now_ts=int(time.time())),
                   "--created-by", "oa-observe", "--json"]
            cp = runner(cmd, capture_output=True, text=True, timeout=30)
            task_id = _parse_task_id(getattr(cp, "stdout", "")) or op.get("task_id")
            if task_id:
                state.setdefault(key, {})["task_id"] = task_id
            results.append({"action": action, "idempotency_key": key, "task_id": task_id,
                            "returncode": getattr(cp, "returncode", None)})
        elif action == "resolve" and op.get("task_id"):
            comment = ("oa-observe ne retrouve plus cette alerte au dernier scan; "
                       "clôture automatique selon protocole de résolution.")
            c1 = runner([str(HERMES), "kanban", "comment", op["task_id"], comment,
                         "--author", "oa-observe"], capture_output=True, text=True, timeout=30)
            c2 = runner([str(HERMES), "kanban", "complete", op["task_id"],
                         "--summary", f"Résolu automatiquement par oa-observe: {op.get('title', key)}"],
                        capture_output=True, text=True, timeout=30)
            results.append({"action": action, "idempotency_key": key, "task_id": op["task_id"],
                            "returncode": max(getattr(c1, "returncode", 0), getattr(c2, "returncode", 0))})
    return results, state


def load_fixture(path: Path) -> tuple[list[Finding], list[str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    findings = [Finding(**item) for item in payload.get("findings", [])]
    notes = [str(n) for n in payload.get("notes", [])]
    return findings, notes


# --------------------------------------------------------------------------- #
# Exécution de commandes (local ou ssh), toujours read-only, toujours timeoutée.
# --------------------------------------------------------------------------- #
def run_on(target: dict, command: str, timeout: int = DEFAULT_TIMEOUT) -> tuple[int, str]:
    """Exécute `command` (string shell) sur la cible. Retourne (rc, stdout).

    rc=-1 signale une erreur d'exécution (timeout, ssh down...). On ne lève
    jamais : un VPS muet doit dégrader proprement, pas faire planter le scan.
    """
    if target["mode"] == "local":
        argv = ["bash", "-lc", command]
    else:
        argv = ["ssh", *SSH_OPTS, target["host"], command]
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "").strip()
    except subprocess.TimeoutExpired:
        return -1, "__TIMEOUT__"
    except Exception as e:  # noqa: BLE001
        return -1, f"__ERR__ {e}"


def reachable(target: dict) -> bool:
    rc, _ = run_on(target, "echo ok", timeout=12)
    return rc == 0


def sqlite_query(target: dict, db: str, sql: str,
                 timeout: int = 25) -> tuple[bool, list[str]]:
    """Exécute une requête SQLite en LECTURE SEULE sur la cible.

    Pour un VPS local, on privilégie le module stdlib `sqlite3` (mode=ro), car
    le binaire sqlite3 n'est pas toujours installé (c'est le cas du VPS-Omar).
    Pour un VPS distant, on passe par le binaire sqlite3 -readonly via ssh.
    Retourne (ok, lignes_de_resultat). ok=False => base illisible/sqlite absent.
    """
    if target["mode"] == "local":
        try:
            import sqlite3  # stdlib, toujours dispo
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=timeout)
            try:
                rows = []
                for stmt in [s for s in sql.split(";") if s.strip()]:
                    cur = con.execute(stmt)
                    rows += [str(r[0]) if len(r) == 1 else "\t".join(map(str, r))
                             for r in cur.fetchall()]
                return True, rows
            finally:
                con.close()
        except Exception:  # noqa: BLE001  (table absente, base corrompue, lock...)
            return False, []
    # distant : binaire sqlite3
    rc, o = run_on(target, f"command -v sqlite3 >/dev/null 2>&1 && "
                           f"sqlite3 -readonly {shlex.quote(db)} {shlex.quote(sql)} "
                           f"|| echo __NOSQLITE__", timeout=timeout)
    if rc != 0 or "__NOSQLITE__" in o:
        return False, []
    return True, [l for l in o.splitlines() if l.strip()]


# --------------------------------------------------------------------------- #
# DÉTECTEURS — chacun prend (target) et retourne List[Finding].
# Ils sont défensifs : toute sortie inattendue = pas de finding (pas de crash).
# --------------------------------------------------------------------------- #
def bloat_warn_threshold(path: str) -> int:
    """Seuil P1 par fichier: générique 500 MiB, Hermes state.db 768 MiB.

    La base Hermes state.db est une base vivante avec historique + index FTS;
    elle peut dépasser 500 MiB sans fuite. Le seuil spécifique évite les faux
    positifs après cleanup sain, tout en gardant le P0 global à 2 GiB.
    """
    return HERMES_STATE_DB_BLOAT_WARN if path.endswith("/.hermes/state.db") else BLOAT_WARN


def det_file_bloat(t: dict) -> list[Finding]:
    """Fichiers de DONNÉES au-dessus de leur seuil dans les répertoires agents/apps.
    Exclut node_modules/venv/.git (dépendances build, pas une fuite)."""
    out: list[Finding] = []
    excl = " ".join(f"-not -path '*/{d}/*'" for d in EXCLUDE_BLOAT_DIRS)
    scan_roots = []
    for h in t["homes"]:
        scan_roots += [f"{h}/.hermes", f"{h}/oa-crm", f"{h}/oa-admin"]
    roots = " ".join(shlex.quote(r) for r in scan_roots)
    # -size en blocs de 512o : 500Mo = 1024000 blocs ; on liste taille en octets
    cmd = (f"for r in {roots}; do [ -d \"$r\" ] && "
           f"find \"$r\" -maxdepth 4 -type f -size +500M {excl} "
           f"-printf '%s\\t%p\\n' 2>/dev/null; done | sort -rn | head -40")
    rc, o = run_on(t, cmd, timeout=90)
    if rc != 0 or not o:
        return out
    for line in o.splitlines():
        try:
            size_s, path = line.split("\t", 1)
            size = int(size_s)
        except ValueError:
            continue
        threshold = bloat_warn_threshold(path)
        if size < threshold:
            continue
        gb = size / 1024**3
        if size >= BLOAT_CRIT:
            sev = "P0"
        else:
            sev = "P1"
        threshold_mib = threshold / 1024**2
        out.append(Finding(
            sev, f"Fichier volumineux : {os.path.basename(path)} ({gb:.1f} Go)",
            f"{path} pèse {gb:.2f} Go (seuil P1 {threshold_mib:.0f} MiB). "
            f"Un fichier de données qui gonfle ainsi est "
            f"souvent le signe d'une fuite (sessions, logs, dump non purgé) — "
            f"comme la base passée à 3 Go le 11/06.",
            t["name"],
            f"Inspecter {path} : si c'est une base, compter les lignes/sessions ; "
            f"si c'est un log, vérifier la rotation. Ne pas supprimer sans diagnostic.",
            "file_bloat"))
    return out


def det_session_explosion(t: dict) -> list[Finding]:
    """Pour chaque state.db de profil Hermes : nb de sessions + taux/dernière heure.
    C'est le détecteur qui aurait attrapé l'incident des 142 000 sessions."""
    out: list[Finding] = []
    # Localiser les state.db (profils + racine .hermes)
    homes = " ".join(shlex.quote(h) for h in t["homes"])
    cmd = (f"for h in {homes}; do "
           f"find \"$h/.hermes\" -maxdepth 3 -name state.db -not -path '*/backups/*' "
           f"-not -path '*/state-snapshots/*' -not -path '*/incidents/*' 2>/dev/null; done")
    rc, o = run_on(t, cmd, timeout=40)
    if rc != 0 or not o:
        return out
    now = time.time()
    for db in o.splitlines():
        db = db.strip()
        if not db:
            continue
        # Lecture READ-ONLY (module python en local, binaire sqlite3 en ssh).
        sql = (f"SELECT count(*) FROM sessions;"
               f"SELECT count(*) FROM sessions WHERE started_at > {now - 3600:.0f}")
        ok, rows = sqlite_query(t, db, sql, timeout=30)
        total = rate = None
        if ok:
            nums = [int(x) for x in rows if x.strip().lstrip("-").isdigit()]
            if len(nums) >= 1:
                total = nums[0]
            if len(nums) >= 2:
                rate = nums[1]
        if total is None:
            # sqlite3 absent côté cible : on signale en P2 informatif plutôt que rien
            out.append(Finding(
                "P2", f"Sessions illisibles : {db}",
                "sqlite3 indisponible sur la cible — impossible de compter les "
                "sessions de ce profil (angle mort du détecteur d'explosion).",
                t["name"],
                "Installer sqlite3 sur la cible, ou lire la base via le module "
                "python sqlite3 en lecture seule.",
                "session_explosion"))
            continue
        prof = Path(db).parent.name
        if total >= SESS_CRIT:
            out.append(Finding(
                "P0", f"Explosion de sessions : {prof} ({total:,})".replace(",", " "),
                f"Le profil {prof} ({db}) compte {total} sessions. Au-delà de "
                f"{SESS_CRIT} c'est quasi certainement un worker en boucle qui "
                f"crée des sessions parasites — exactement le scénario du 11/06.",
                t["name"],
                f"Identifier le worker qui crée ces sessions (logs gateway), "
                f"l'arrêter, purger la base après backup. Vérifier le déclencheur.",
                "session_explosion"))
        elif total >= SESS_WARN:
            out.append(Finding(
                "P1", f"Sessions nombreuses : {prof} ({total})",
                f"{prof} a {total} sessions (seuil de vigilance {SESS_WARN}). "
                f"Pas critique mais à surveiller : croissance anormale ?",
                t["name"],
                f"Vérifier le taux de création et la rétention configurée du profil.",
                "session_explosion"))
        if rate is not None and rate >= SESS_RATE_WARN:
            out.append(Finding(
                "P1", f"Taux de sessions élevé : {prof} (+{rate}/h)",
                f"{prof} a créé {rate} sessions dans la dernière heure. Un taux "
                f"soutenu de ce niveau atteint des dizaines de milliers en quelques "
                f"jours (le 11/06 : 142 000 en 3 semaines).",
                t["name"],
                "Vérifier en urgence le worker/cron responsable avant que la base ne gonfle.",
                "session_explosion"))
    return out


def det_kanban_loop(t: dict) -> list[Finding]:
    """Tâches kanban Hermes en statut running depuis > 6h (boucle probable)."""
    out: list[Finding] = []
    homes = " ".join(shlex.quote(h) for h in t["homes"])
    cmd = (f"for h in {homes}; do "
           f"for db in \"$h/.hermes/kanban.db\" \"$h/.hermes/kanban/kanban.db\"; do "
           f"[ -f \"$db\" ] && echo \"$db\"; done; done")
    rc, o = run_on(t, cmd, timeout=30)
    if rc != 0 or not o:
        return out
    seen = set()
    for db in o.splitlines():
        db = db.strip()
        if not db or db in seen:
            continue
        seen.add(db)
        cutoff = time.time() - KANBAN_RUNNING_H * 3600
        # Schéma kanban OA : status='running', horodatage = last_heartbeat_at
        # (fallback started_at). Une tâche running dont le dernier heartbeat est
        # ancien = worker bloqué/en boucle.
        sql = (
            "SELECT count(*) FROM tasks WHERE status='running' "
            f"AND coalesce(last_heartbeat_at, started_at, 0) < {cutoff:.0f}")
        ok, rows = sqlite_query(t, db, sql, timeout=25)
        if not ok or not rows or not rows[0].strip().isdigit():
            continue
        n = int(rows[0].strip())
        if n > 0:
            out.append(Finding(
                "P1", f"Kanban : {n} tâche(s) running > {KANBAN_RUNNING_H}h",
                f"{n} tâche(s) sont en statut running depuis plus de "
                f"{KANBAN_RUNNING_H}h dans {db} — souvent un agent bloqué/en boucle "
                f"qui ne libère jamais la carte.",
                t["name"],
                "Lister les cartes (hermes kanban list), identifier l'agent bloqué, "
                "le débloquer ou réassigner.",
                "kanban_loop"))
    return out


def _ram_swap_pressure(t: dict, available_mb: int | None) -> dict:
    """Mesure les signaux du contrat unique de pression swap réelle."""
    rc, output = run_on(t, "cat /proc/pressure/memory; vmstat -w 1 3", timeout=20)
    if rc != 0 or not output:
        output = ""
    return classify_swap_pressure(available_mb, output, output)


def det_ram_swap(t: dict) -> list[Finding]:
    """Préserve P0 RAM ; P1 swap seulement si pression, activité ou RAM basse."""
    out: list[Finding] = []
    rc, o = run_on(t, "free -m", timeout=15)
    if rc != 0 or not o:
        return out
    avail = swap_total = swap_used = None
    for line in o.splitlines():
        p = line.split()
        if line.startswith("Mem:") and len(p) >= 7:
            avail = int(p[6])
        if line.startswith("Swap:") and len(p) >= 3:
            swap_total = int(p[1])
            swap_used = int(p[2])
    if avail is not None and avail < RAM_AVAIL_CRIT:
        out.append(Finding(
            "P0", f"RAM critique : {avail} Mo disponibles",
            f"Mémoire disponible {avail} Mo (< {RAM_AVAIL_CRIT}). Risque d'OOM "
            f"imminent (le gateway Hermes a déjà été tué par l'OOM-killer les 9-10/06).",
            t["name"],
            "Identifier le process le plus gourmand (ps aux --sort=-rss | head), "
            "vérifier le swap, redémarrer le service fautif si besoin.",
            "ram_swap"))
    if swap_total and swap_used is not None:
        pct = round(100 * swap_used / swap_total)
        if pct > SWAP_PCT_WARN:
            pressure = _ram_swap_pressure(t, avail)
            if not is_real_swap_pressure(pressure):
                return out
            signals = []
            if pressure["low_available"]:
                signals.append(f"RAM disponible basse ({avail} Mo < 1024 Mo)")
            if pressure["memory_pressure"]:
                signals.append(f"PSI mémoire avg10={pressure['psi_avg10']:.2f}%")
            if pressure["sustained_swap_out"]:
                signals.append(
                    f"swap-out soutenu ({pressure['swap_out_kbps']} KiB/s sur 2 échantillons)"
                )
            out.append(Finding(
                "P1", f"Swap sous pression : {pct}% ({swap_used}/{swap_total} Mo)",
                f"Le swap est utilisé à {pct}% et le signal est qualifié par "
                + "; ".join(signals) + ".",
                t["name"],
                "Vérifier les processus consommateurs et la pression mémoire ; "
                "ne pas vider le swap pour masquer la métrique.",
                "ram_swap"))
    return out


def _backup_log_spec(raw: str | dict) -> dict:
    """Normalise une entrée backup_logs historique (str) ou typée (dict)."""
    if isinstance(raw, dict):
        spec = dict(raw)
    else:
        spec = {"path": str(raw)}
    spec.setdefault("scope", "primary")
    spec.setdefault("label", Path(str(spec["path"])).name)
    return spec


def _parse_backup_ts(value: str | None) -> float | None:
    if not value:
        return None
    value = value.strip().strip("[]")
    try:
        iso = value.replace("Z", "+00:00")
        return datetime.fromisoformat(iso).timestamp()
    except ValueError:
        pass
    m = re.search(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})", value)
    if not m:
        return None
    try:
        return time.mktime(time.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M:%S"))
    except Exception:  # noqa: BLE001
        return None


def _line_backup_ts(line: str) -> float | None:
    m = re.search(r"\[?((?:\d{4}-\d{2}-\d{2})[T ][^\]\s]+)", line)
    return _parse_backup_ts(m.group(1)) if m else None


def _iter_json_objects(text: str):
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(text):
        while idx < len(text) and text[idx].isspace():
            idx += 1
        if idx >= len(text):
            break
        try:
            obj, end = decoder.raw_decode(text, idx)
        except json.JSONDecodeError:
            idx += 1
            continue
        yield obj
        idx = end


def _backup_ok_timestamps(text: str) -> list[float]:
    stamps: list[float] = []
    for line in text.splitlines():
        if "status=OK" in line or re.search(r"\bDB\b.*\bOK\b", line):
            ts = _line_backup_ts(line)
            if ts is not None:
                stamps.append(ts)
    for obj in _iter_json_objects(text):
        if not isinstance(obj, dict) or obj.get("all_integrity_ok") is not True:
            continue
        ts = _parse_backup_ts(str(obj.get("ts") or ""))
        if ts is not None:
            stamps.append(ts)
    return stamps


def _backup_failure_timestamps(text: str) -> list[float]:
    stamps: list[float] = []
    for line in text.splitlines():
        m = re.search(r"status=([^\s]+)", line)
        if not m or m.group(1) == "OK":
            continue
        ts = _line_backup_ts(line)
        if ts is not None:
            stamps.append(ts)
    return stamps


def det_backup_stale(t: dict) -> list[Finding]:
    """Backup OK frais: status=OK, legacy DB ... OK, ou manifest all_integrity_ok."""
    out: list[Finding] = []
    logs = [_backup_log_spec(log) for log in t.get("backup_logs", [])]
    if not logs:
        return out

    primary_paths = [str(log["path"]) for log in logs if log.get("scope") != "client"]
    primary_found = False
    primary_freshest_age = None
    client_issues: list[tuple[dict, str]] = []

    for log in logs:
        path = str(log["path"])
        rc, o = run_on(
            t,
            f"[ -f {shlex.quote(path)} ] && tail -c 65536 {shlex.quote(path)} || echo __ABSENT__",
            timeout=20,
        )
        if rc != 0 or o == "__ABSENT__" or not o:
            if log.get("scope") == "client":
                client_issues.append((log, "log absent ou illisible"))
            continue

        ok_stamps = _backup_ok_timestamps(o)
        failure_stamps = _backup_failure_timestamps(o)
        freshest_ok = max(ok_stamps) if ok_stamps else None
        freshest_failure = max(failure_stamps) if failure_stamps else None
        age = (time.time() - freshest_ok) / 3600 if freshest_ok is not None else None

        if log.get("scope") == "client":
            if freshest_ok is None:
                client_issues.append((log, "aucun status=OK"))
            elif age is not None and age > BACKUP_WARN_H:
                client_issues.append((log, f"dernier OK il y a {age:.0f}h"))
            elif freshest_failure is not None and freshest_failure > freshest_ok:
                client_issues.append((log, "échec plus récent que le dernier OK"))
            continue

        if freshest_ok is None:
            continue
        primary_found = True
        if age is not None:
            primary_freshest_age = age if primary_freshest_age is None else min(primary_freshest_age, age)

    for log, reason in client_issues:
        out.append(Finding(
            "P1", f"Backup client {log['label']} sans OK frais",
            f"Le contrôle client {log['label']} ({log['path']}) signale: {reason}. "
            "Le backup primaire peut être sain, mais la réplication/pull client doit rester visible.",
            t["name"],
            "Vérifier le job de pull client et relancer le transfert si nécessaire.",
            "backup_stale"))

    if not primary_found:
        out.append(Finding(
            "P0", "Aucun backup OK trouvé",
            f"Aucun backup primaire OK détecté dans les logs/manifestes déclarés "
            f"({', '.join(primary_paths)}). Formats acceptés: status=OK, DB ... OK, "
            "manifest JSON all_integrity_ok=true. Soit le backup ne tourne pas, "
            "soit il échoue silencieusement — angle mort dangereux.",
            t["name"],
            "Vérifier le cron/timer de backup et lancer un backup manuel de contrôle.",
            "backup_stale"))
    elif primary_freshest_age is not None and primary_freshest_age > BACKUP_WARN_H:
        out.append(Finding(
            "P1", f"Backup ancien : dernier OK il y a {primary_freshest_age:.0f}h",
            f"Le backup OK primaire le plus récent date de {primary_freshest_age:.0f}h "
            f"(seuil {BACKUP_WARN_H}h). Le job s'est peut-être arrêté.",
            t["name"],
            "Vérifier le timer de backup et relancer manuellement.",
            "backup_stale"))
    return out


def det_failed_units(t: dict) -> list[Finding]:
    """systemctl --failed (system) + (--user pour les comptes agents)."""
    out: list[Finding] = []
    # system
    rc, o = run_on(t, "systemctl --failed --no-legend --plain 2>/dev/null", 20)
    if rc == 0 and o:
        for line in o.splitlines():
            unit = line.split()[0] if line.split() else line
            if not unit or unit.startswith("0 "):
                continue
            out.append(Finding(
                "P1", f"Unité systemd en échec : {unit}",
                f"L'unité système {unit} est en état failed sur {t['name']}.",
                t["name"],
                f"systemctl status {unit} ; journalctl -u {unit} -n 50 pour diagnostiquer.",
                "failed_units"))
    # user (edilia notamment, côté JAB) — on tente pour chaque home connu
    for h in t["homes"]:
        user = Path(h).name
        cmd = (f"systemctl --user --failed --no-legend --plain "
               f"--machine={user}@.host 2>/dev/null")
        rc2, o2 = run_on(t, cmd, 20)
        if rc2 == 0 and o2:
            for line in o2.splitlines():
                unit = line.split()[0] if line.split() else line
                if not unit:
                    continue
                out.append(Finding(
                    "P1", f"Unité user en échec : {unit} ({user})",
                    f"L'unité user {unit} (compte {user}) est failed.",
                    t["name"],
                    f"systemctl --user -M {user}@ status {unit} pour diagnostiquer.",
                    "failed_units"))
    return out


def det_orphan_procs(t: dict) -> list[Finding]:
    """Zombies (<defunct>) + anciens process claude/native-binary orphelins (ppid=1)."""
    out: list[Finding] = []
    rc, o = run_on(t, "ps -eo pid,ppid,etimes,stat,comm 2>/dev/null", 20)
    if rc != 0 or not o:
        return out
    zombies = 0
    orphans = []
    for line in o.splitlines()[1:]:
        p = line.split(None, 4)
        if len(p) < 5:
            continue
        pid, ppid, etimes, stat_, comm = p
        if "Z" in stat_:
            zombies += 1
        # orphelin claude/native-binary : reparenté à init (ppid=1) et vieux (>1h)
        if (ppid == "1" and etimes.isdigit() and int(etimes) > 3600
                and re.search(r"claude|native-binary", comm, re.I)):
            orphans.append((comm, int(etimes)))
    if zombies:
        sev = "P1" if zombies > 5 else "P2"
        out.append(Finding(
            sev, f"{zombies} process zombie(s)",
            f"{zombies} process <defunct> (zombies) sur {t['name']}. Souvent un "
            f"parent qui ne reap pas ses enfants — symptôme de gateway/worker malade.",
            t["name"],
            "Identifier le parent (ps -eo pid,ppid,stat | grep Z) et le redémarrer.",
            "orphan_procs"))
    if orphans:
        sev = "P1" if len(orphans) > 5 else "P2"
        ex = ", ".join(f"{c}({s//60}min)" for c, s in orphans[:4])
        out.append(Finding(
            sev, f"{len(orphans)} process claude/agent orphelin(s)",
            f"{len(orphans)} process agent reparentés à init et anciens : {ex}. "
            f"Restes d'un gateway tué (cf OOM 9-10/06) qui n'ont pas été nettoyés.",
            t["name"],
            "Vérifier qu'ils ne consomment pas de RAM ; les tuer si confirmés orphelins.",
            "orphan_procs"))
    return out


def det_secret_exposure(t: dict) -> list[Finding]:
    """Fichiers de secrets world-readable. Cible STRICTE pour éviter les
    faux positifs (les tests nommés *token*.py ne sont pas des secrets)."""
    out: list[Finding] = []
    homes = " ".join(shlex.quote(h) for h in t["homes"])
    # On ne retient que les vrais porteurs de secrets, on exclut tests/ & node_modules/
    cmd = (
        f"for h in {homes}; do find \"$h\" -maxdepth 4 -type f -perm -o+r "
        f"\\( -name '*.env' -o -name '*token*.json' -o -name 'keys.txt' "
        f"-o -name '*secret*.json' -o -name '*.pem' \\) "
        f"-not -path '*/tests/*' -not -path '*/node_modules/*' "
        f"-not -path '*/site-packages/*' -not -name '*.py' "
        f"-printf '%m %p\\n' 2>/dev/null; done | head -40")
    rc, o = run_on(t, cmd, timeout=40)
    if rc == 0 and o:
        for line in o.splitlines():
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            mode, path = parts
            out.append(Finding(
                "P0", f"Secret world-readable : {os.path.basename(path)}",
                f"{path} est lisible par tous (perm {mode}). Tout process/user de "
                f"la machine peut lire ce fichier de secrets.",
                t["name"],
                f"chmod 600 {path} (et 700 sur le répertoire parent si besoin).",
                "secret_exposure"))
    # Endpoint /api/vault.json qui exposerait l'inventaire des secrets (correctif 11/06)
    # On vérifie localement le repo QG : le fichier ne doit plus exister/être servi.
    if t["mode"] == "local":
        vault = Path("/home/omar/23-Offre/actifs/omar-qg/public/api/vault.json")
        if vault.exists():
            out.append(Finding(
                "P0", "vault.json présent dans public/api",
                "public/api/vault.json existe et serait servi publiquement — il "
                "publie l'inventaire des secrets hors-Vault (chemins SSH, .env, "
                "username GitHub). C'est précisément la fuite corrigée le 11/06.",
                t["name"],
                "Supprimer public/api/vault.json du build et purger le cache servi.",
                "secret_exposure"))
    return out


def _gh_open_issues(repo: Path) -> tuple[int | None, int, str]:
    """Nombre d'issues ouvertes du repo, ou ``None`` si la mesure est impossible.

    Un ``None`` signifie « je ne sais pas », jamais « zéro ». Retourne aussi le
    returncode et le début de stderr pour que l'échec soit diagnosticable dans
    la sortie du scan (avant ce correctif, ils étaient jetés : l'échec était
    invisible et invérifiable).
    """
    try:
        r = subprocess.run(
            ["gh", "issue", "list", "--state", "open", "--json", "number", "-L", "100"],
            cwd=str(repo), capture_output=True, text=True, timeout=25)
    except Exception as e:  # noqa: BLE001
        return None, -1, f"{type(e).__name__}: {e}"
    err = (r.stderr or "").strip()
    if r.returncode != 0:
        return None, r.returncode, err
    out = (r.stdout or "").strip()
    if not out:
        return None, r.returncode, err or "stdout vide"
    try:
        payload = json.loads(out)
    except Exception as e:  # noqa: BLE001
        return None, r.returncode, f"JSON invalide: {e}"
    if not isinstance(payload, list):
        return None, r.returncode, "JSON inattendu (pas une liste)"
    return len(payload), r.returncode, err


def det_repo_idle(t: dict) -> list[Finding]:
    """Mode amélioration des apps. Local uniquement (repos sur VPS-Omar).
    - app sans commit > 5j ET 0 issue ouverte = pas en mode amélioration (P2)
    - fichiers non commités > 0 depuis > 24h = risque de perte (P1)
    - issues GitHub illisibles (échec gh) = gh_unreadable (P2), jamais repo_idle
    - repo déclaré `frozen` dans var/repo-intent.json = pas de repo_idle (P2)"""
    out: list[Finding] = []
    if t["mode"] != "local":
        return out
    base = REPOS_BASE
    if not base.exists():
        return out
    registry = load_repo_intent()
    now = time.time()
    for repo in sorted(base.glob("omar-*")):
        if not (repo / ".git").is_dir():
            continue
        name = repo.name

        def git(args, _r=repo):
            try:
                return subprocess.run(["git", "-C", str(_r), *args],
                                      capture_output=True, text=True,
                                      timeout=20).stdout.strip()
            except Exception:  # noqa: BLE001
                return ""

        last = git(["log", "-1", "--format=%ct"])
        days = (now - int(last)) / 86400 if last.isdigit() else None

        # Porcelain SANS strip() : le préfixe XY compte deux caractères, et un
        # strip() supprime l'espace de " M fichier" — le chemin extrait devenait
        # alors "p.py" (faux), donc l'âge du fichier sale n'était jamais mesuré
        # et le P1 « non commité depuis > 24h » ne sortait jamais pour une
        # modification (seuls les "??" passaient par chance).
        def git_raw(args, _r=repo):
            try:
                return subprocess.run(["git", "-C", str(_r), *args],
                                      capture_output=True, text=True,
                                      timeout=20).stdout
            except Exception:  # noqa: BLE001
                return ""

        dirty = [l for l in git_raw(["status", "--porcelain"]).splitlines() if l.strip()]
        # commits non poussés
        unpushed = git(["log", "--oneline", "@{u}..HEAD"]) if git(
            ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"]) else ""
        n_unpushed = len([l for l in unpushed.splitlines() if l.strip()])
        # issues GitHub ouvertes — un échec gh n'est JAMAIS « 0 issue »
        n_issues, gh_rc, gh_err = _gh_open_issues(repo)

        # P1 — fichiers non commités depuis > 24h (risque de perte)
        if dirty:
            # âge approximé par le fichier modifié le plus ancien parmi les dirty
            oldest = now
            for l in dirty:
                rel = l[3:].strip().strip('"')
                if " -> " in rel:  # renommage : "R  ancien -> nouveau"
                    rel = rel.split(" -> ", 1)[1].strip().strip('"')
                fp = repo / rel
                try:
                    oldest = min(oldest, fp.stat().st_mtime)
                except Exception:  # noqa: BLE001
                    pass
            age_h = (now - oldest) / 3600
            if age_h > REPO_DIRTY_H:
                out.append(Finding(
                    "P1", f"{name} : {len(dirty)} fichier(s) non commité(s) depuis {age_h:.0f}h",
                    f"{name} a {len(dirty)} fichier(s) modifiés non commités, le plus "
                    f"ancien depuis {age_h:.0f}h. Risque de perte si le VPS tombe — "
                    f"du travail en cours non sauvegardé en git.",
                    t["name"],
                    f"cd {repo} && git status ; committer (ou stash/clean si générés).",
                    "repo_idle"))

        intent = repo_intent_of(name, registry)

        # P2 — issues GitHub illisibles : « je ne sais pas » n'est pas « 0 issue »
        if n_issues is None:
            SCAN_NOTES.append(
                f"gh issue list a échoué sur {name} (rc={gh_rc}) : "
                f"{gh_err[:200] or 'sans stderr'}")
            out.append(Finding(
                "P2", f"{name} : issues GitHub illisibles",
                f"{name} : impossible de lire les issues ouvertes via gh "
                f"(returncode {gh_rc}). Le backlog est INCONNU — ce n'est pas "
                f"« pas de backlog ».",
                t["name"],
                "Vérifier `gh auth status` et l'accès réseau à github.com, "
                "puis relancer oa-observe.",
                "gh_unreadable"))

        if intent == "frozen":
            entry = registry.get(name) or {}
            decided = f"{entry.get('decided_by') or 'n/a'} le {entry.get('decided_at') or 'n/a'}"
            card = f", carte {entry['card']}" if entry.get("card") else ""
            reopen = str(entry.get("reopen_condition") or "non définie").rstrip(". ")
            out.append(Finding(
                "INFO", f"{name} : figé volontairement",
                f"{name} est déclaré `frozen` dans le registre d'intention "
                f"(décision {decided}{card}). Aucun `repo_idle` n'est émis pour "
                f"ce repo. Condition de réouverture : {reopen}.",
                t["name"],
                "Aucune action : gel décidé. Réévaluer seulement si la "
                "condition de réouverture est remplie.",
                "repo_intent_frozen"))
        elif days is not None and days > REPO_IDLE_DAYS and n_issues == 0:
            out.append(Finding(
                "P2", f"{name} : pas en mode amélioration ({days:.0f}j sans commit)",
                f"{name} : dernier commit il y a {days:.0f} jours et 0 issue "
                f"ouverte. L'app semble en pause — ni évolution récente, ni "
                f"backlog identifié.",
                t["name"],
                "Décider : ouvrir 1-2 issues d'amélioration, ou acter que l'app "
                "est figée (var/repo-intent.json).",
                "repo_idle"))

        # P2 — commits non poussés (risque moindre mais à signaler)
        if n_unpushed > 0:
            out.append(Finding(
                "P2", f"{name} : {n_unpushed} commit(s) non poussé(s)",
                f"{name} a {n_unpushed} commit(s) locaux non poussés vers le remote.",
                t["name"],
                f"cd {repo} && git push (après relecture).",
                "repo_idle"))
    return out


def det_cert_expiry(t: dict) -> list[Finding]:
    """Certs Caddy expirant dans < 14j (bonus, local uniquement, best-effort)."""
    out: list[Finding] = []
    if t["mode"] != "local":
        return out
    # Emplacement standard des certs Caddy (data dir)
    cmd = ("find /home/omar/.local/share/caddy /var/lib/caddy ~/.caddy "
           "-name '*.crt' 2>/dev/null | head -40")
    rc, o = run_on(t, cmd, timeout=25)
    if rc != 0 or not o:
        return out
    for crt in o.splitlines():
        crt = crt.strip()
        if not crt:
            continue
        rc2, o2 = run_on(
            t, f"openssl x509 -enddate -noout -in {shlex.quote(crt)} 2>/dev/null", 15)
        if rc2 != 0 or "notAfter=" not in o2:
            continue
        try:
            exp = o2.split("notAfter=", 1)[1].strip()
            ts = time.mktime(time.strptime(exp, "%b %d %H:%M:%S %Y %Z"))
            days = (ts - time.time()) / 86400
        except Exception:  # noqa: BLE001
            continue
        if days < CERT_EXPIRY_DAYS:
            sev = "P1" if days > 2 else "P0"
            out.append(Finding(
                sev, f"Cert expire dans {days:.0f}j : {os.path.basename(crt)}",
                f"Le certificat {crt} expire dans {days:.0f} jours.",
                t["name"],
                "Vérifier que Caddy renouvelle bien (ACME/internal) ; forcer si bloqué.",
                "cert_expiry"))
    return out


DETECTORS = {
    "file_bloat": det_file_bloat,
    "session_explosion": det_session_explosion,
    "kanban_loop": det_kanban_loop,
    "ram_swap": det_ram_swap,
    "backup_stale": det_backup_stale,
    "failed_units": det_failed_units,
    "orphan_procs": det_orphan_procs,
    "secret_exposure": det_secret_exposure,
    "repo_idle": det_repo_idle,
    "cert_expiry": det_cert_expiry,
}


# --------------------------------------------------------------------------- #
# OBSERVATIONS — phrases qui ouvrent une conversation (dérivées des findings).
# --------------------------------------------------------------------------- #
def build_observations(findings: list[Finding]) -> list[Observation]:
    obs: list[Observation] = []
    by_det: dict[str, list[Finding]] = {}
    for f in findings:
        by_det.setdefault(f.detecteur, []).append(f)

    # Repos dirty -> question travail en cours / généré
    dirty = [f for f in by_det.get("repo_idle", []) if "non commité" in f.titre]
    for f in dirty:
        m = re.search(r"(\S+) : (\d+) fichier", f.titre)
        if m:
            obs.append(Observation(
                f"{m.group(1)} a {m.group(2)} fichiers non commités depuis un moment — "
                f"c'est du travail en cours à sauver, ou des fichiers générés qu'on peut "
                f"ignorer (gitignore) ?", f.vps))

    # Apps en pause
    idle = [f for f in by_det.get("repo_idle", []) if "mode amélioration" in f.titre]
    if idle:
        names = ", ".join(re.match(r"(\S+)", f.titre).group(1) for f in idle if re.match(r"(\S+)", f.titre))
        obs.append(Observation(
            f"{len(idle)} app(s) n'ont pas bougé depuis plusieurs jours ({names}) et "
            f"n'ont pas d'issue ouverte — mode amélioration en pause volontaire, ou "
            f"juste personne ne s'en occupe ?"))

    # Sessions / bloat -> rappel incident
    if by_det.get("session_explosion") or by_det.get("file_bloat"):
        obs.append(Observation(
            "Des volumes anormaux remontent (sessions ou fichiers) — exactement la "
            "famille de l'incident du 11/06. Veux-tu que je creuse lequel en priorité ?"))

    # Swap sous pression
    swap = [f for f in by_det.get("ram_swap", []) if "Swap" in f.titre]
    if swap:
        obs.append(Observation(
            "Le swap est sous pression sur "
            + ", ".join(sorted({f.vps for f in swap}))
            + " — ça tient pour l'instant, mais c'est le terrain d'un futur OOM. "
              "On regarde quel service consomme ?"))

    return obs


# --------------------------------------------------------------------------- #
# SCAN + RAPPORT
# --------------------------------------------------------------------------- #
def scan(only: list[str] | None = None) -> tuple[list[Finding], list[str]]:
    findings: list[Finding] = []
    notes: list[str] = []
    SCAN_NOTES.clear()
    dets = DETECTORS if not only else {k: v for k, v in DETECTORS.items() if k in only}
    for t in TARGETS:
        if not reachable(t):
            notes.append(f"{t['name']} injoignable (timeout/ssh) — non scanné.")
            findings.append(Finding(
                "P1", f"{t['name']} injoignable",
                f"Impossible de joindre {t['name']} (ssh/local timeout). Un VPS muet "
                f"est lui-même une anomalie : panne, réseau, ou hôte éteint.",
                t["name"],
                "Vérifier la connectivité (ssh, tailscale) et l'état du VPS.",
                "reachability"))
            continue
        for dname, fn in dets.items():
            try:
                findings += fn(t)
            except Exception as e:  # noqa: BLE001
                notes.append(f"détecteur {dname} a échoué sur {t['name']} : {e}")
    # diagnostics remontés par les détecteurs (ex: gh en échec) — visibles
    for n in SCAN_NOTES:
        if n not in notes:
            notes.append(n)
    findings.sort(key=lambda f: (f.order(), f.vps))
    return findings, notes


def render_briefing(findings: list[Finding], obs: list[Observation],
                    notes: list[str]) -> str:
    today = time.strftime("%Y-%m-%d")
    p0 = [f for f in findings if f.severite == "P0"]
    p1 = [f for f in findings if f.severite == "P1"]
    p2 = [f for f in findings if f.severite == "P2"]
    info = [f for f in findings if f.severite == "INFO"]
    L = [f"# Observateur de flotte OA — {today}", ""]
    L.append(f"_Scan automatique de {len(TARGETS)} cible(s) : "
             + ", ".join(t["name"] for t in TARGETS) + "._")
    L.append(f"_Bilan : {len(p0)} P0 · {len(p1)} P1 · {len(p2)} P2._")
    L.append("")

    if not p0 and not p1:
        L.append("## RAS")
        L.append("")
        L.append("Rien de grave aujourd'hui : aucun P0 ni P1. "
                 "Voici quand même les observations ci-dessous.")
        L.append("")

    if p0 or p1 or p2:
        L.append("## 🔴 À regarder")
        L.append("")
        for f in p0 + p1 + p2:
            L.append(f"### [{f.severite}] {f.titre}  ·  _{f.vps}_")
            L.append("")
            L.append(f"{f.detail}")
            L.append("")
            L.append(f"**Remédiation** — {f.remediation}")
            L.append("")

    if info:
        L.append("## 🧊 Repos figés volontairement (informatif)")
        L.append("")
        for f in info:
            L.append(f"- **{f.titre}** — {f.detail}")
        L.append("")

    L.append("## 💬 Observations & questions pour Alex")
    L.append("")
    if obs:
        for o in obs:
            tag = f" _({o.vps})_" if o.vps else ""
            L.append(f"- {o.texte}{tag}")
    else:
        L.append("- Flotte calme : pas d'observation particulière à ouvrir aujourd'hui.")
    L.append("")

    if notes:
        L.append("## ⚙️ Notes de scan (angles morts / erreurs)")
        L.append("")
        for n in notes:
            L.append(f"- {n}")
        L.append("")

    L.append("---")
    L.append(f"_Généré par oa-observe.py le {time.strftime('%Y-%m-%d %H:%M:%S')} "
             f"(lecture seule)._")
    return "\n".join(L)


def print_summary(findings: list[Finding]) -> None:
    p0 = [f for f in findings if f.severite == "P0"]
    p1 = [f for f in findings if f.severite == "P1"]
    p2 = [f for f in findings if f.severite == "P2"]
    print(f"oa-observe : {len(p0)} P0 · {len(p1)} P1 · {len(p2)} P2")
    if p0:
        print("P0 :")
        for f in p0:
            print(f"  🔴 [{f.vps}] {f.titre}")
    elif p1:
        print("Aucun P0. P1 :")
        for f in p1:
            print(f"  🟠 [{f.vps}] {f.titre}")
    else:
        print("RAS (aucun P0/P1).")


def main() -> int:
    ap = argparse.ArgumentParser(description="Observateur proactif de la flotte OA")
    ap.add_argument("--stdout-only", action="store_true",
                    help="ne pas écrire le fichier de briefing")
    ap.add_argument("--only", default="",
                    help="détecteurs à exécuter (CSV), ex: file_bloat,ram_swap")
    ap.add_argument("--json", action="store_true", help="dump JSON des findings")
    ap.add_argument("--out-dir",
                    default="/home/omar/11-Pilotage/journal/observateur",
                    help="répertoire de sortie des briefings")
    ap.add_argument("--fixture", help="fixture JSON de findings pour tests/smoke (ne scanne pas la flotte)")
    ap.add_argument("--kanban", action="store_true", help="synchronise les findings vers Hermes Kanban")
    ap.add_argument("--kanban-dry-run", action="store_true",
                    help="affiche le plan create/update/resolve sans mutation Kanban ni état local")
    ap.add_argument("--kanban-state", default=str(DEFAULT_KANBAN_STATE),
                    help="fichier état local oa-observe -> Kanban")
    ap.add_argument("--kanban-assignee", default="default", help="assignee des cartes Kanban créées")
    ap.add_argument("--kanban-priority", type=int, default=85, help="priorité des cartes Kanban créées")
    ap.add_argument("--no-board-reconcile", action="store_true",
                    help="désactive la réconciliation avec les cartes encore ouvertes du board")
    args = ap.parse_args()

    only = [s.strip() for s in args.only.split(",") if s.strip()] or None
    if only:
        unknown = [d for d in only if d not in DETECTORS]
        if unknown:
            print(f"détecteurs inconnus : {unknown}. "
                  f"Disponibles : {', '.join(DETECTORS)}", file=sys.stderr)
            return 2

    if args.fixture:
        findings, notes = load_fixture(Path(args.fixture))
    else:
        findings, notes = scan(only)
    obs = build_observations(findings)

    kanban_result = None
    if args.kanban or args.kanban_dry_run:
        state_path = Path(args.kanban_state)
        previous = load_kanban_state(state_path)
        # Détecteurs réellement mesurés : borne la réconciliation. Un scan
        # partiel ne doit pas clore les cartes des détecteurs non exécutés.
        scanned_detectors = set(only) if only else set(DETECTORS)
        board_cards: list[dict] = []
        board_reconcile = not args.no_board_reconcile and not args.fixture
        if board_reconcile:
            board_cards = list_observe_board_cards()
        plan, next_state = plan_kanban_sync(
            findings, previous, board_cards=board_cards,
            scanned_detectors=scanned_detectors)
        by_key = {finding_idempotency_key(f): f for f in findings}
        results, next_state = apply_kanban_plan(
            plan, next_state, by_key, dry_run=args.kanban_dry_run,
            assignee=args.kanban_assignee, priority=args.kanban_priority)
        kanban_result = {
            "schema": "oa.observe.kanban-sync/1",
            "dry_run": bool(args.kanban_dry_run),
            "state_path": str(state_path),
            "board_reconcile": board_reconcile,
            "board_open_cards": len(board_cards),
            "operations": results,
        }
        failures = [r for r in results if r.get("returncode") not in (None, 0)]
        if failures:
            kanban_result["status"] = "error"
            kanban_result["failures"] = failures
        else:
            kanban_result["status"] = "ok"
        if args.kanban and not args.kanban_dry_run and not failures:
            save_kanban_state(next_state, state_path)

    if args.json:
        payload = {"schema": "oa.observe.scan/1",
                   "findings": [structured_finding(f) for f in findings],
                   "observations": [asdict(o) for o in obs],
                   "notes": notes}
        if kanban_result is not None:
            payload["kanban"] = kanban_result
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        if kanban_result and kanban_result.get("status") == "error":
            return 1
        return 0

    if kanban_result is not None:
        print(json.dumps(kanban_result, ensure_ascii=False, indent=2))
        if kanban_result.get("status") == "error":
            return 1
        if args.kanban_dry_run:
            return 0

    briefing = render_briefing(findings, obs, notes)
    if not args.stdout_only:
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{time.strftime('%Y-%m-%d')}.md"
        out_path.write_text(briefing, encoding="utf-8")
        print(f"briefing écrit : {out_path}")
    print_summary(findings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
