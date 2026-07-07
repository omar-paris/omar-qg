#!/usr/bin/env python3
"""Collecteur local-only des feedbacks Alex depuis /blocages/.

But: transformer les réponses inline à signal faible (ex: "???", ton négatif,
demande de lien/action impossible) en carte Kanban de triage [FEEDBACK-ALEX],
sans notification de groupe et avec déduplication locale.

Modes:
  - OA_FEEDBACK_ALEX_MODE=off     : désactivé
  - OA_FEEDBACK_ALEX_MODE=dry-run : défaut, écrit seulement var/feedback-alex-local.log
  - OA_FEEDBACK_ALEX_MODE=create  : crée une carte Kanban triage locale

Ce module ne logge jamais de corps brut non borné: l'extrait est redacted et tronqué.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VAR = ROOT / "var"
LOG = VAR / "feedback-alex-local.log"
STATE = VAR / "feedback-alex-seen.json"
HERMES = os.environ.get("HERMES_BIN", "/home/omar/.local/bin/hermes")
MODE = os.environ.get("OA_FEEDBACK_ALEX_MODE", "dry-run").strip().lower() or "dry-run"
ASSIGNEE = os.environ.get("OA_FEEDBACK_ALEX_ASSIGNEE", "default").strip() or "default"

SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9_-]{10,}|ghp_[A-Za-z0-9]{10,}|github_pat_[A-Za-z0-9_]{10,}"
    r"|xox[a-z]-[A-Za-z0-9-]{10,}|AKIA[A-Z0-9]{12,}|eyJ[A-Za-z0-9_-]{20,}"
    r"|(?i:(?:token|secret|password|passwd|api[_-]?key|bearer)\s*[=:]\s*)[^\s'\"]{6,})"
)
TASK_RE = re.compile(r"\bt_[0-9a-f]{8}\b")
ISSUE_RE = re.compile(r"\b[a-z0-9-]+#\d+\b", re.I)

SIGNAL_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("question_marks", re.compile(r"\?\?\?")),
    ("negative_tone", re.compile(r"\b(nul|inutile|absurde|n'importe quoi|ça sert à rien|ca sert a rien|pas clair|incompréhensible|incomprehensible|je comprends pas|je ne comprends pas)\b", re.I)),
    ("broken_or_impossible", re.compile(r"\b(impossible|bloqué|bloque|ça bloque|ca bloque|marche pas|ne marche pas|fonctionne pas|bug|erreur|cassé|casse)\b", re.I)),
    ("missing_link_or_action", re.compile(r"\b(où est le lien|ou est le lien|quel lien|pas de lien|lien manquant|je fais quoi|quoi faire|quelle action|action impossible)\b", re.I)),
]

NEUTRAL_ONLY_RE = re.compile(r"^(fait|ok|okay|merci|vu|done|traité|traite|c'est fait)(\s*[.!…]*)?$", re.I)


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def redact(text: str) -> str:
    return SECRET_RE.sub("[REDIGE]", text or "")


def excerpt(text: str, limit: int = 220) -> str:
    line = " ".join(redact(str(text or "")).split())
    return line[: limit - 1] + "…" if len(line) > limit else line


def detect_feedback(answer: str) -> list[str]:
    text = str(answer or "").strip()
    if not text or NEUTRAL_ONLY_RE.match(text):
        return []
    return [name for name, pattern in SIGNAL_RULES if pattern.search(text)]


def _load_seen() -> dict[str, Any]:
    try:
        data = json.loads(STATE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_seen(seen: dict[str, Any]) -> None:
    VAR.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(seen, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def fingerprint(ref: str, answer: str, source: str) -> str:
    norm = " ".join(str(answer or "").lower().split())
    raw = json.dumps({"ref": ref, "answer": norm, "source": source}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _link_for(ref: str) -> str:
    if TASK_RE.fullmatch(ref or ""):
        return f"https://hermes.omar.paris/kanban?task={ref}"
    if ISSUE_RE.fullmatch(ref or ""):
        return f"https://github.com/search?q=org%3Aomar-paris+{ref}&type=issues"
    return "/blocages/"


def build_card(ref: str, answer: str, reasons: list[str], source: str) -> tuple[str, str, str]:
    short = excerpt(answer, 180)
    key = fingerprint(ref, answer, source)
    title = f"[FEEDBACK-ALEX] /blocages friction sur {ref or 'ref-inconnue'}"
    link = _link_for(ref)
    body = "\n".join([
        "Source: réponse inline /blocages captée en local-only.",
        f"Horodatage: {now_iso()}",
        f"Référence concernée: {ref or 'non renseignée'}",
        f"Lien utile: {link}",
        f"Signal détecté: {', '.join(reasons)}",
        f"Extrait court redacted: \"{short}\"",
        "",
        "Owner recommandé: H-Omar/default pour trier; oa-builder si correction UI/QG; oa-secretaire si le collecteur ou le flux /blocages est en cause.",
        "",
        "DoD:",
        "- Identifier pourquoi la réponse Alex indique une friction réelle ou une action impossible.",
        "- Corriger la source (lien, libellé, owner, action demandée, ou carte Kanban) ou fermer comme non-actionnable avec justification.",
        "- Vérifier que /blocages/ ne redemande pas la même action confuse.",
        "",
        "Garde-fous: carte triage locale uniquement; pas de notification groupe automatique; ne pas recopier de contenu sensible brut.",
    ])
    return title, body, f"feedback-alex:{key}"


def _append_log(event: dict[str, Any]) -> None:
    VAR.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def maybe_collect(ref: str, answer: str, source: str = "qg_api:/api/blocages/answer", mode: str | None = None) -> dict[str, Any]:
    mode = (mode or MODE).strip().lower() or "dry-run"
    ref = str(ref or "").strip()
    reasons = detect_feedback(answer)
    base = {"schema": "oa.feedback-alex/1", "created_at": now_iso(), "mode": mode, "ref": ref, "source": source, "reasons": reasons, "excerpt": excerpt(answer)}
    if mode == "off":
        return {**base, "action": "disabled"}
    if not reasons:
        return {**base, "action": "ignored"}

    key = fingerprint(ref, answer, source)
    seen = _load_seen()
    if key in seen:
        event = {**base, "action": "duplicate", "dedupe_key": key, "existing": seen[key]}
        _append_log(event)
        return event

    title, body, idempotency_key = build_card(ref, answer, reasons, source)
    event = {**base, "action": "dry_run", "dedupe_key": key, "title": title, "body_preview": excerpt(body, 1200), "idempotency_key": idempotency_key}

    if mode == "create":
        cmd = [
            HERMES, "kanban", "create", title,
            "--assignee", ASSIGNEE,
            "--triage",
            "--idempotency-key", idempotency_key,
            "--created-by", "oa-secretaire",
            "--body", body,
            "--json",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        event["action"] = "created" if proc.returncode == 0 else "create_failed"
        event["returncode"] = proc.returncode
        if proc.stdout.strip():
            try:
                event["kanban"] = json.loads(proc.stdout)
            except Exception:
                event["stdout"] = proc.stdout.strip()[:500]
        if proc.stderr.strip():
            event["stderr"] = proc.stderr.strip()[:500]
    elif mode != "dry-run":
        event["action"] = "invalid_mode"

    if event["action"] in {"dry_run", "created"}:
        seen[key] = {"at": event["created_at"], "action": event["action"], "title": title, "ref": ref}
        if isinstance(event.get("kanban"), dict):
            seen[key]["task_id"] = event["kanban"].get("id") or event["kanban"].get("task_id")
        _save_seen(seen)
    _append_log(event)
    return event


def main() -> None:
    parser = argparse.ArgumentParser(description="Collecte local-only des feedbacks Alex depuis /blocages/.")
    parser.add_argument("--ref", required=True)
    parser.add_argument("--answer", required=True)
    parser.add_argument("--source", default="cli")
    parser.add_argument("--mode", default=None, choices=["off", "dry-run", "create"])
    args = parser.parse_args()
    print(json.dumps(maybe_collect(args.ref, args.answer, args.source, args.mode), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
