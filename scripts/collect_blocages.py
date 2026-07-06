#!/usr/bin/env python3
"""Collecteur blocages QG — « Ce qui bloque — et qui débloque ».

Agrège en read-only les 4 familles de blocages (demande Alex 06/07, Fable rescue) :
  1. Décisions QG ouvertes (var/decisions.json)
  2. Cartes Kanban blocked qui attendent un humain (kanban.db, mode=ro)
  3. Blocages sudo (cartes 'sudo' + GO list CHANTIER2-APPLIED-040726.md, best effort)
  4. PRs : gates Athena NO-GO dont la source attend un rework + PRs GitHub ouvertes >7 j

DÉDUPLICATION (le point d'Alex — « parfois redondants ») :
  - décision ouverte liée à une carte (blocked_ref) → UNE entrée, la décision gagne,
    la carte est référencée dedans ;
  - carte source d'un gate NO-GO → UNE entrée type=pr (le rework), pas deux ;
  - PR GitHub déjà couverte par un gate NO-GO → l'entrée PR porte le verdict.

Sortie : var/blocages.json (schéma oa.blocages/1). Aucun secret : raisons rédigées.
Jamais bloquant : chaque source échoue en silence (liste errors) — le build QG survit.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sqlite3
import subprocess
import time
import urllib.parse
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VAR = ROOT / "var"
OUT = VAR / "blocages.json"
SCHEMA = "oa.blocages/1"
KANBAN_DB = Path(os.environ.get("OA_KANBAN_DB", "/home/omar/.hermes/kanban.db"))
GO_LIST_FILE = Path(os.environ.get(
    "OA_GO_LIST_FILE",
    "/home/omar/11-Pilotage/sujets-actifs/fable-4d-system-rescue/CHANTIER2-APPLIED-040726.md",
))
GO_LIST_DATE = "2026-07-04"  # date du fichier (040726) — âge best effort
GH_ORG = "omar-paris"
GH_REPOS = ["omar-qg", "omar-top", "omar-hub", "omar-app", "omar-catalogue", "omi-bridge", "oa-crm"]
STALE_PR_DAYS = 7
GH_TIMEOUT_S = 15          # par repo
GH_BUDGET_S = 60           # global — au-delà on arrête d'interroger GitHub

ACTION_ALEX_RE = re.compile(r"ACTION ALEX\s*\((\d+)\s*min\)\s*:?\s*", re.IGNORECASE)
COUT_MIN_RE = re.compile(r"co[uû]t\s*:?\s*~?(\d+)\s*min", re.IGNORECASE)
TASK_ID_RE = re.compile(r"\bt_[0-9a-f]{8}\b")
GATE_SOURCE_RE = re.compile(r"\(from (t_[0-9a-f]+)\)")
GATE_PR_RE = re.compile(r"\b(omar-[a-z]+|oa-[a-z-]+|omi-bridge)\b[^\n]{0,40}?PR\s*#?(\d+)", re.IGNORECASE)
# Rédaction : tokens/clés/blobs — jamais de secret dans le JSON publié.
SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9_-]{10,}|ghp_[A-Za-z0-9]{10,}|github_pat_[A-Za-z0-9_]{10,}"
    r"|xox[a-z]-[A-Za-z0-9-]{10,}|AKIA[A-Z0-9]{12,}|eyJ[A-Za-z0-9_-]{20,}"
    r"|(?i:(?:token|secret|password|passwd|api[_-]?key|bearer)\s*[=:]\s*)[^\s'\"]{6,})"
)
RESOLVED_MARKERS = ("✅", "sans objet", "supprimé", "résolu", "décommissionné")


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso(v: dt.datetime) -> str:
    return v.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def safe(exc: BaseException) -> str:
    return f"{exc.__class__.__name__}: {str(exc)[:140]}"


def redact(text: str) -> str:
    return SECRET_RE.sub("[REDIGE]", text or "")


def one_line(text: str, limit: int = 180) -> str:
    line = " ".join(redact(str(text or "")).split())
    return line[: limit - 1] + "…" if len(line) > limit else line


def age_days(then: dt.datetime | None, now: dt.datetime) -> int:
    if then is None:
        return 0
    return max(0, int((now - then).total_seconds() // 86400))


def parse_iso(v: Any) -> dt.datetime | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit()):
        try:
            return dt.datetime.fromtimestamp(float(v), tz=dt.timezone.utc)
        except Exception:
            return None
    try:
        d = dt.datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
    except Exception:
        return None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def entry(eid: str, qui: str, etype: str, titre: str, age: int, action: str,
          lien: str = "", effort_min: int | None = None, source: str = "", refs: list[str] | None = None) -> dict:
    return {
        "id": eid,
        "qui_debloque": qui,          # alex | h-omar | agent | externe
        "type": etype,                # decision | carte | sudo | pr
        "titre": one_line(titre, 140),
        "age_jours": age,
        "action_1_ligne": one_line(action),
        "lien": lien,
        "effort_min": effort_min,
        "source": source,
        "refs": refs or [],
    }


# ── 1. Décisions QG ouvertes ─────────────────────────────────────────────────

def collect_decisions(now: dt.datetime, errors: list[str]) -> tuple[list[dict], set[str]]:
    """Retourne (entrées, ids de cartes kanban couvertes par une décision)."""
    entries: list[dict] = []
    covered_cards: set[str] = set()
    try:
        decisions = json.loads((VAR / "decisions.json").read_text(encoding="utf-8"))
        if not isinstance(decisions, list):
            raise ValueError("decisions.json: liste attendue")
    except Exception as exc:
        errors.append("decisions_unavailable: " + safe(exc))
        return entries, covered_cards
    for d in decisions:
        if not isinstance(d, dict) or (d.get("statut") or "").lower() != "ouverte":
            continue
        ref = str(d.get("blocked_ref") or "").strip()
        refs = []
        if ref:
            covered_cards.add(ref)
            refs.append(ref)
        effort = None
        m = COUT_MIN_RE.search(str(d.get("contexte") or ""))
        if m:
            effort = int(m.group(1))
        options = [str(o) for o in (d.get("options") or []) if o]
        action = "Répondre sur /decisions/"
        if options:
            action += " — options : " + " / ".join(options)
        if ref:
            action += f" (débloque la carte {ref})"
        entries.append(entry(
            f"decision:{d.get('id')}", "alex", "decision",
            str(d.get("texte") or "Décision sans texte"),
            age_days(parse_iso(d.get("posee_le")), now),
            action, "/decisions/", effort, "var/decisions.json", refs,
        ))
    return entries, covered_cards


# ── 2+3. Kanban blocked + gates NO-GO + sudo (une seule connexion ro) ────────

def _kanban_connect() -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{urllib.parse.quote(str(KANBAN_DB))}?mode=ro", uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    return con


def collect_kanban(now: dt.datetime, covered_cards: set[str], errors: list[str]) -> tuple[list[dict], list[dict], set[str]]:
    """Retourne (entrées cartes/sudo, entrées rework NO-GO, refs PR GitHub couvertes 'repo#num')."""
    card_entries: list[dict] = []
    rework_entries: list[dict] = []
    nogo_prs: set[str] = set()
    if not KANBAN_DB.exists():
        errors.append("kanban_db_missing: " + str(KANBAN_DB))
        return card_entries, rework_entries, nogo_prs
    try:
        con = _kanban_connect()
    except Exception as exc:
        errors.append("kanban_unavailable: " + safe(exc))
        return card_entries, rework_entries, nogo_prs
    try:
        blocked = con.execute(
            "SELECT id, title, assignee, block_kind, created_at, result FROM tasks "
            "WHERE status='blocked' AND (assignee='alex' OR block_kind IN ('needs_input','capability'))"
        ).fetchall()
        comments: dict[str, list[str]] = {}
        for r in con.execute(
            "SELECT task_id, body FROM task_comments WHERE task_id IN (%s) ORDER BY id"
            % ",".join("?" * len(blocked)), [r["id"] for r in blocked]
        ) if blocked else []:
            comments.setdefault(r["task_id"], []).append(str(r["body"] or ""))

        # Gates NO-GO → la source (rework) est LE blocage ; on dédoublonne les cartes sources.
        gates = con.execute(
            "SELECT id, title, result, completed_at FROM tasks "
            "WHERE result LIKE 'VERDICT: NO-GO%' ORDER BY completed_at DESC"
        ).fetchall()
        rework_sources: dict[str, sqlite3.Row] = {}
        for g in gates:
            for repo, num in GATE_PR_RE.findall(g["title"] or ""):
                nogo_prs.add(f"{repo.lower()}#{num}")
            m = GATE_SOURCE_RE.search(g["title"] or "")
            if m and m.group(1) not in rework_sources:
                rework_sources[m.group(1)] = g
        for src_id, gate in rework_sources.items():
            src = con.execute(
                "SELECT id, title, status, assignee, created_at FROM tasks WHERE id=?", (src_id,)
            ).fetchone()
            if src is None or src["status"] not in ("blocked", "todo", "in_progress", "scheduled"):
                continue  # la source a été retravaillée/fermée : plus un blocage
            if src_id in covered_cards:
                continue  # une décision QG couvre déjà cette carte
            verdict = one_line(str(gate["result"] or "")[len("VERDICT: NO-GO"):].lstrip(" —-"), 140)
            rework_entries.append(entry(
                f"pr:rework:{src_id}", "agent", "pr",
                str(src["title"] or src_id),
                age_days(parse_iso(src["created_at"]), now),
                f"Rework demandé par gate Athena {gate['id']} (NO-GO) : {verdict}",
                "https://hermes.omar.paris/", None, "kanban.db", [src_id, str(gate["id"])],
            ))
        rework_ids = set(rework_sources)

        for r in blocked:
            tid = str(r["id"])
            if tid in covered_cards or (tid in rework_ids and any(e["refs"][0] == tid for e in rework_entries)):
                continue  # dédup : décision QG ou rework NO-GO déjà listés
            title = str(r["title"] or tid)
            result = str(r["result"] or "")
            body_all = " ".join([title, result] + comments.get(tid, []))
            effort = None
            action = ""
            for c in reversed(comments.get(tid, [])):
                m = ACTION_ALEX_RE.search(c)
                if m:
                    effort = int(m.group(1))
                    action = c[m.end():]
                    break
            is_sudo = "sudo" in body_all.lower()
            if r["assignee"] == "alex" or effort is not None or is_sudo:
                qui = "alex"
            elif r["block_kind"] == "capability":
                qui = "h-omar"
            else:
                qui = "h-omar"  # needs_input sans action Alex explicite → arbitrage H-Omar
            if not action:
                raison = one_line(result, 120) or "carte bloquée sans raison renseignée"
                action = f"Débloquer ({r['block_kind'] or 'blocked'}) : {raison}"
            card_entries.append(entry(
                f"carte:{tid}", qui, "sudo" if is_sudo else "carte", title,
                age_days(parse_iso(r["created_at"]), now),
                action, "https://hermes.omar.paris/", effort, "kanban.db", [tid],
            ))
    except Exception as exc:
        errors.append("kanban_query_failed: " + safe(exc))
    finally:
        con.close()
    return card_entries, rework_entries, nogo_prs


def _kanban_done_ids(ids: set[str]) -> set[str]:
    """Cartes citées déjà terminées/archivées — pour filtrer la GO list."""
    if not ids or not KANBAN_DB.exists():
        return set()
    try:
        con = _kanban_connect()
        try:
            rows = con.execute(
                "SELECT id FROM tasks WHERE id IN (%s) AND status IN ('done','archived','cancelled')"
                % ",".join("?" * len(ids)), sorted(ids)
            ).fetchall()
            return {r["id"] for r in rows}
        finally:
            con.close()
    except Exception:
        return set()


# ── 3bis. GO list sudo/infra (CHANTIER2, parse léger best effort) ────────────

def collect_go_list(now: dt.datetime, existing_refs: set[str], errors: list[str]) -> list[dict]:
    entries: list[dict] = []
    try:
        text = GO_LIST_FILE.read_text(encoding="utf-8")
    except Exception as exc:
        errors.append("go_list_unavailable: " + safe(exc))
        return entries
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith("##") and "go list" in l.lower()), None)
    if start is None:
        errors.append("go_list_section_missing")
        return entries
    bullets: list[str] = []
    for l in lines[start + 1:]:
        if l.startswith("##") or l.startswith("```"):
            break
        if l.strip().startswith("- "):
            bullets.append(l.strip()[2:].strip())
    rest_of_doc = "\n".join(lines[start + 1:])
    cited = {t for b in bullets for t in TASK_ID_RE.findall(b)}
    done_ids = _kanban_done_ids(cited)
    age = age_days(parse_iso(GO_LIST_DATE + "T00:00:00Z"), now)
    for i, b in enumerate(bullets, 1):
        b_ids = TASK_ID_RE.findall(b)
        if b_ids and all(t in done_ids for t in b_ids):
            continue  # la carte citée est terminée — item réglé
        if b_ids and any(t in existing_refs for t in b_ids):
            continue  # déjà porté par une décision/carte listée
        m = re.match(r"\*\*(.+?)\*\*", b)
        titre = m.group(1) if m else b[:100]
        # Marqué réglé plus loin dans le doc (ex: open-webui décommissionné) → on saute.
        key = (m.group(1).split("(")[0].strip() if m else titre).strip(" *:").lower()
        key_token = next((w for w in re.split(r"[^a-z0-9_\-]+", key) if len(w) >= 8), "")
        if key_token and any(
            key_token in l.lower() and any(mark in l for mark in RESOLVED_MARKERS)
            for l in rest_of_doc.splitlines()
        ):
            continue
        entries.append(entry(
            f"sudo:golist:{i}", "alex", "sudo", titre, age,
            "GO list CHANTIER2 (04/07) : " + re.sub(r"\*\*", "", b),
            "", None, GO_LIST_FILE.name, b_ids,
        ))
    return entries


# ── 4. PRs GitHub ouvertes > 7 jours ─────────────────────────────────────────

def collect_stale_prs(now: dt.datetime, nogo_prs: set[str], errors: list[str]) -> list[dict]:
    entries: list[dict] = []
    started = time.monotonic()
    for repo in GH_REPOS:
        if time.monotonic() - started > GH_BUDGET_S:
            errors.append("gh_budget_exhausted: repos restants ignorés")
            break
        try:
            proc = subprocess.run(
                ["gh", "pr", "list", "--repo", f"{GH_ORG}/{repo}", "--state", "open",
                 "--json", "number,title,createdAt,url", "--limit", "30"],
                capture_output=True, text=True, timeout=GH_TIMEOUT_S,
            )
            if proc.returncode != 0:
                raise RuntimeError((proc.stderr or "gh error").strip()[:80])
            prs = json.loads(proc.stdout or "[]")
        except Exception as exc:
            errors.append(f"gh_pr_list_failed:{repo}: " + safe(exc))
            continue
        for pr in prs:
            created = parse_iso(pr.get("createdAt"))
            age = age_days(created, now)
            if age <= STALE_PR_DAYS:
                continue
            key = f"{repo}#{pr.get('number')}"
            action = f"PR ouverte depuis {age} j — reviewer puis merger ou fermer"
            if key in nogo_prs:
                action = f"PR ouverte depuis {age} j — gate Athena NO-GO : rework agent avant merge"
            entries.append(entry(
                f"pr:{key}", "agent" if key in nogo_prs else "alex", "pr",
                f"{key} — {pr.get('title') or ''}", age, action,
                str(pr.get("url") or ""), None, "github", [key],
            ))
    return entries


# ── Agrégation ────────────────────────────────────────────────────────────────

def collect(write: bool = True) -> dict:
    now = now_utc()
    errors: list[str] = []
    decision_entries, covered_cards = collect_decisions(now, errors)
    card_entries, rework_entries, nogo_prs = collect_kanban(now, covered_cards, errors)
    existing_refs = {ref for e in decision_entries + card_entries + rework_entries for ref in e["refs"]}
    go_entries = collect_go_list(now, existing_refs, errors)
    pr_entries = collect_stale_prs(now, nogo_prs, errors)

    blocages = decision_entries + card_entries + go_entries + rework_entries + pr_entries
    qui_rank = {"alex": 0, "h-omar": 1, "agent": 2, "externe": 3}
    blocages.sort(key=lambda e: (qui_rank.get(e["qui_debloque"], 9), -e["age_jours"]))

    pour_alex = [e for e in blocages if e["qui_debloque"] == "alex"]
    par_type: dict[str, int] = {}
    for e in blocages:
        par_type[e["type"]] = par_type.get(e["type"], 0) + 1
    payload = {
        "schema": SCHEMA,
        "generated_at": iso(now),
        "definition": "Un blocage = quelque chose qui n'avance plus tant qu'un humain/agent précis n'agit pas. Dédupliqué décisions↔cartes↔gates↔PRs.",
        "compteurs": {
            "total": len(blocages),
            "pour_alex": len(pour_alex),
            "effort_min_alex": sum(e["effort_min"] or 0 for e in pour_alex),
            "par_type": par_type,
            "par_qui": {q: sum(1 for e in blocages if e["qui_debloque"] == q) for q in qui_rank if any(e["qui_debloque"] == q for e in blocages)},
        },
        "blocages": blocages,
        "errors": errors,
    }
    if write:
        VAR.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> None:
    payload = collect(write=True)
    c = payload["compteurs"]
    print(f"blocages: {c['total']} total · {c['pour_alex']} pour Alex (~{c['effort_min_alex']} min) · "
          f"types {c['par_type']} · {len(payload['errors'])} erreur(s) → {OUT.relative_to(ROOT)}")
    for err in payload["errors"]:
        print("  warn:", err)


if __name__ == "__main__":
    main()
