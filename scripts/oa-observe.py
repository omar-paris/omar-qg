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
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

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
            "/var/log/oadmin-backup.log",
            "/home/omar/4-Infra/logs/pull-backup-jab.log",
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
BLOAT_WARN = 500 * 1024**2     # 500 Mo  -> P1
BLOAT_CRIT = 2 * 1024**3       # 2 Go    -> P0
SESS_WARN = 1_000              # P1
SESS_CRIT = 10_000            # P0
SESS_RATE_WARN = 200          # sessions créées dans la dernière heure -> P1
RAM_AVAIL_CRIT = 400          # Mo available -> P0
SWAP_PCT_WARN = 80            # % swap utilisé -> P1
BACKUP_WARN_H = 36            # h sans backup OK -> P1
KANBAN_RUNNING_H = 6          # tâche running > 6h -> P1
REPO_IDLE_DAYS = 5           # commit le plus récent > 5j + 0 issue -> P2
REPO_DIRTY_H = 24            # fichiers non commités depuis > 24h -> P1
CERT_EXPIRY_DAYS = 14        # cert expirant dans < 14j -> P1
DEFAULT_TIMEOUT = 30
SSH_OPTS = ["-o", "ConnectTimeout=10", "-o", "BatchMode=yes"]

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
def det_file_bloat(t: dict) -> list[Finding]:
    """Fichiers de DONNÉES > 500 Mo dans les répertoires agents/apps.
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
        gb = size / 1024**3
        if size >= BLOAT_CRIT:
            sev = "P0"
        else:
            sev = "P1"
        out.append(Finding(
            sev, f"Fichier volumineux : {os.path.basename(path)} ({gb:.1f} Go)",
            f"{path} pèse {gb:.2f} Go. Un fichier de données qui gonfle ainsi est "
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


def det_ram_swap(t: dict) -> list[Finding]:
    """available < 400 Mo = P0 ; swap > 80% = P1. (leçon OOM 9-10 juin)"""
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
            out.append(Finding(
                "P1", f"Swap saturé : {pct}% ({swap_used}/{swap_total} Mo)",
                f"Le swap est utilisé à {pct}%. Au-delà, la machine rame et le "
                f"risque OOM grimpe — précurseur classique d'incident.",
                t["name"],
                "Vérifier la pression mémoire ; un service fuit-il ? Envisager un "
                "redémarrage propre du process le plus gourmand.",
                "ram_swap"))
    return out


def det_backup_stale(t: dict) -> list[Finding]:
    """Dernière ligne status=OK dans les logs de backup. >36h = P1 ; absent = P0."""
    out: list[Finding] = []
    logs = t.get("backup_logs", [])
    if not logs:
        return out
    found_any = False
    freshest_age = None
    for log in logs:
        rc, o = run_on(
            t, f"[ -f {shlex.quote(log)} ] && grep -a 'status=OK' {shlex.quote(log)} "
               f"| tail -1 || echo __ABSENT__", timeout=20)
        if rc != 0 or o == "__ABSENT__" or not o:
            continue
        found_any = True
        # Cherche un timestamp ISO en tête de ligne : [2026-06-11T03:40:04+00:00]
        m = re.search(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})", o)
        if m:
            try:
                ts = time.mktime(time.strptime(f"{m.group(1)} {m.group(2)}",
                                               "%Y-%m-%d %H:%M:%S"))
                age = (time.time() - ts) / 3600
                freshest_age = age if freshest_age is None else min(freshest_age, age)
            except Exception:  # noqa: BLE001
                pass
    if not found_any:
        out.append(Finding(
            "P0", "Aucun backup OK trouvé",
            f"Aucune ligne status=OK dans les logs de backup déclarés "
            f"({', '.join(logs)}). Soit le backup ne tourne pas, soit il échoue "
            f"silencieusement — angle mort dangereux.",
            t["name"],
            "Vérifier le cron/timer de backup et lancer un backup manuel de contrôle.",
            "backup_stale"))
    elif freshest_age is not None and freshest_age > BACKUP_WARN_H:
        out.append(Finding(
            "P1", f"Backup ancien : dernier OK il y a {freshest_age:.0f}h",
            f"Le backup OK le plus récent date de {freshest_age:.0f}h "
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


def det_repo_idle(t: dict) -> list[Finding]:
    """Mode amélioration des apps. Local uniquement (repos sur VPS-Omar).
    - app sans commit > 5j ET 0 issue ouverte = pas en mode amélioration (P2)
    - fichiers non commités > 0 depuis > 24h = risque de perte (P1)"""
    out: list[Finding] = []
    if t["mode"] != "local":
        return out
    base = Path("/home/omar/23-Offre/actifs")
    if not base.exists():
        return out
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
        dirty = [l for l in git(["status", "--porcelain"]).splitlines() if l.strip()]
        # commits non poussés
        unpushed = git(["log", "--oneline", "@{u}..HEAD"]) if git(
            ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"]) else ""
        n_unpushed = len([l for l in unpushed.splitlines() if l.strip()])
        # issues GitHub ouvertes
        n_issues = None
        gh = subprocess.run(["gh", "issue", "list", "--repo-dir", str(repo),
                             "--json", "number", "-L", "100"],
                            capture_output=True, text=True, timeout=25) \
            if False else None  # gh n'a pas --repo-dir ; on appelle depuis le repo
        try:
            r = subprocess.run(["gh", "issue", "list", "--json", "number", "-L", "100"],
                               cwd=str(repo), capture_output=True, text=True, timeout=25)
            if r.returncode == 0 and r.stdout.strip():
                n_issues = len(json.loads(r.stdout))
        except Exception:  # noqa: BLE001
            n_issues = None

        # P1 — fichiers non commités depuis > 24h (risque de perte)
        if dirty:
            # âge approximé par le fichier modifié le plus ancien parmi les dirty
            oldest = now
            for l in dirty:
                fp = repo / l[3:].strip().strip('"')
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

        # P2 — pas en mode amélioration
        if days is not None and days > REPO_IDLE_DAYS and (n_issues == 0 or n_issues is None):
            iss = "0 issue ouverte" if n_issues == 0 else "issues GitHub illisibles"
            out.append(Finding(
                "P2", f"{name} : pas en mode amélioration ({days:.0f}j sans commit)",
                f"{name} : dernier commit il y a {days:.0f} jours et {iss}. L'app "
                f"semble en pause — ni évolution récente, ni backlog identifié.",
                t["name"],
                f"Décider : ouvrir 1-2 issues d'amélioration, ou acter que l'app est figée.",
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
    findings.sort(key=lambda f: (f.order(), f.vps))
    return findings, notes


def render_briefing(findings: list[Finding], obs: list[Observation],
                    notes: list[str]) -> str:
    today = time.strftime("%Y-%m-%d")
    p0 = [f for f in findings if f.severite == "P0"]
    p1 = [f for f in findings if f.severite == "P1"]
    p2 = [f for f in findings if f.severite == "P2"]
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
    args = ap.parse_args()

    only = [s.strip() for s in args.only.split(",") if s.strip()] or None
    if only:
        unknown = [d for d in only if d not in DETECTORS]
        if unknown:
            print(f"détecteurs inconnus : {unknown}. "
                  f"Disponibles : {', '.join(DETECTORS)}", file=sys.stderr)
            return 2

    findings, notes = scan(only)
    obs = build_observations(findings)

    if args.json:
        print(json.dumps({"findings": [asdict(f) for f in findings],
                          "observations": [asdict(o) for o in obs],
                          "notes": notes}, ensure_ascii=False, indent=2))
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
