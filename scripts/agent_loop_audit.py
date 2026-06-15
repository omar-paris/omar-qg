#!/usr/bin/env python3
"""Read-only audit Issue ↔ Kanban ↔ PR ↔ Athena gate.

This command only reads GitHub and the Hermes Kanban SQLite database, then writes a
JSON report for QG. It never creates cards, comments, labels, PRs, or decisions.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

DEFAULT_REPOS = ["omar-app", "omar-landing", "omar-hub", "omar-qg", "omar-top", "omar-catalogue"]
ROOT = Path(__file__).resolve().parents[1]
KANBAN_DB = Path("/home/omar/.hermes/kanban.db")
GH = "/usr/bin/gh"

PR_URL_RE = re.compile(r"github\.com/omar-paris/(?P<repo>[-\w]+)/pull/(?P<number>\d+)", re.I)
DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}(?::\d{2})?))?")
OWNER_RE = re.compile(r"\b(owner|responsable|assignee|assigné|assigned_to)\s*[:=]\s*\S+", re.I)
NEXT_ACTION_RE = re.compile(r"\b(next[_ -]?action|prochaine action|action suivante)\s*[:=]\s*\S+", re.I)


def run(cmd: list[str], *, timeout: int = 90, check: bool = False) -> subprocess.CompletedProcess[str]:
    cp = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and cp.returncode != 0:
        raise RuntimeError(f"command failed ({cp.returncode}): {' '.join(cmd)}\n{cp.stderr.strip()}")
    return cp


def _text(*parts: Any) -> str:
    return "\n".join(str(p or "") for p in parts)


def _task_text(task: dict[str, Any]) -> str:
    return _text(task.get("title"), task.get("body"), task.get("result"), task.get("comments"))


def _keys(tasks: Iterable[dict[str, Any]]) -> set[str]:
    return {str(t.get("idempotency_key")) for t in tasks if t.get("idempotency_key")}


def _status(task: dict[str, Any]) -> str:
    return str(task.get("status") or "").lower()


def _is_archived(task: dict[str, Any]) -> bool:
    return _status(task) in {"archived", "cancelled", "canceled"}


def _comment_text(comments: Any) -> str:
    if isinstance(comments, list):
        parts: list[str] = []
        for comment in comments:
            if isinstance(comment, dict):
                parts.append(str(comment.get("body") or ""))
            else:
                parts.append(str(comment or ""))
        return "\n".join(parts)
    return str(comments or "")


def _has_decision_required(pr: dict[str, Any]) -> bool:
    return "decision_required" in _text(pr.get("body"), _comment_text(pr.get("comments"))).lower()


def _first_pr_ref(text: str) -> tuple[str, int] | None:
    m = PR_URL_RE.search(text or "")
    if not m:
        return None
    return m.group("repo"), int(m.group("number"))


def _scheduled_epoch(task: dict[str, Any]) -> int | None:
    text = _task_text(task)
    m = DATE_RE.search(text)
    if not m:
        return None
    value = m.group(1) + ("T" + m.group(2) if m.group(2) else "T00:00:00")
    try:
        return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp())
    except ValueError:
        return None


def _blocked_has_owner_and_next_action(task: dict[str, Any]) -> bool:
    text = _task_text(task)
    return bool(OWNER_RE.search(text) and NEXT_ACTION_RE.search(text))


def audit_agent_loop(
    *,
    issues: list[dict[str, Any]],
    prs: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    now_ts: int | None = None,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    """Return QG anti-orphans report from already-collected read-only inputs."""
    now_ts = int(now_ts or time.time())
    errors = list(errors or [])
    active_tasks = [t for t in tasks if not _is_archived(t)]
    keys = _keys(active_tasks)

    issues_without_card: list[dict[str, Any]] = []
    for issue in issues:
        repo = str(issue.get("repo") or "")
        number = int(issue.get("number") or 0)
        expected_key = f"agentok-{repo}-{number}"
        if expected_key not in keys:
            issues_without_card.append({
                "repo": repo,
                "number": number,
                "title": issue.get("title") or "",
                "url": issue.get("url") or "",
                "expected_key": expected_key,
                "action": "create_builder_card",
            })

    prs_without_gate: list[dict[str, Any]] = []
    for pr in prs:
        repo = str(pr.get("repo") or "")
        number = int(pr.get("number") or 0)
        expected_key = f"builder-pr-gate:{repo}:{number}"
        if expected_key not in keys and not _has_decision_required(pr):
            prs_without_gate.append({
                "repo": repo,
                "number": number,
                "title": pr.get("title") or "",
                "url": pr.get("url") or "",
                "expected_key": expected_key,
                "action": "create_athena_gate_card",
            })

    builder_cards_without_gate: list[dict[str, Any]] = []
    for task in active_tasks:
        if str(task.get("assignee") or "") != "oa-builder" or _status(task) != "blocked":
            continue
        text = _task_text(task)
        if "review-required" not in text.lower():
            continue
        pr_ref = _first_pr_ref(text)
        expected_key = f"builder-pr-gate:{pr_ref[0]}:{pr_ref[1]}" if pr_ref else None
        if not expected_key or expected_key not in keys:
            builder_cards_without_gate.append({
                "card_id": task.get("id") or "",
                "title": task.get("title") or "",
                "pr": {"repo": pr_ref[0], "number": pr_ref[1]} if pr_ref else None,
                "expected_key": expected_key,
                "action": "create_athena_gate_card",
            })

    blocked_without_next_action: list[dict[str, Any]] = []
    for task in active_tasks:
        if _status(task) == "blocked" and not _blocked_has_owner_and_next_action(task):
            blocked_without_next_action.append({
                "card_id": task.get("id") or "",
                "title": task.get("title") or "",
                "assignee": task.get("assignee") or "",
                "action": "add_owner_and_next_action",
            })

    stale_scheduled: list[dict[str, Any]] = []
    for task in active_tasks:
        if _status(task) != "scheduled":
            continue
        scheduled_epoch = _scheduled_epoch(task)
        if scheduled_epoch is None or scheduled_epoch < now_ts:
            stale_scheduled.append({
                "card_id": task.get("id") or "",
                "title": task.get("title") or "",
                "assignee": task.get("assignee") or "",
                "scheduled_epoch": scheduled_epoch,
                "action": "refresh_or_archive_schedule",
            })

    summary = {
        "issues_without_card": len(issues_without_card),
        "prs_without_gate": len(prs_without_gate),
        "builder_cards_without_gate": len(builder_cards_without_gate),
        "blocked_without_next_action": len(blocked_without_next_action),
        "stale_scheduled": len(stale_scheduled),
    }
    summary["total_orphans"] = sum(summary.values())
    return {
        "schema": "oa.agent-loop-audit/1",
        "status": "healthy" if summary["total_orphans"] == 0 and not errors else "degraded",
        "checked_at": datetime.fromtimestamp(now_ts, tz=timezone.utc).isoformat(),
        "source": "scripts/agent_loop_audit.py",
        "summary": summary,
        "issues_without_card": issues_without_card,
        "prs_without_gate": prs_without_gate,
        "builder_cards_without_gate": builder_cards_without_gate,
        "blocked_without_next_action": blocked_without_next_action,
        "stale_scheduled": stale_scheduled,
        "errors": errors,
    }


def collect_agent_ok_issues(repos: Iterable[str], errors: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for repo in repos:
        cp = run([GH, "issue", "list", "-R", f"omar-paris/{repo}", "--label", "agent-ok", "--state", "open", "--limit", "100", "--json", "number,title,url"], timeout=90)
        if cp.returncode != 0:
            errors.append(f"github issues {repo}: {cp.stderr.strip() or cp.stdout.strip()}")
            continue
        for item in json.loads(cp.stdout or "[]"):
            out.append({"repo": repo, "number": item.get("number"), "title": item.get("title"), "url": item.get("url")})
    return out


def collect_open_prs(repos: Iterable[str], errors: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for repo in repos:
        cp = run([GH, "pr", "list", "-R", f"omar-paris/{repo}", "--state", "open", "--limit", "100", "--json", "number,title,url,body,comments"], timeout=90)
        if cp.returncode != 0:
            errors.append(f"github prs {repo}: {cp.stderr.strip() or cp.stdout.strip()}")
            continue
        for item in json.loads(cp.stdout or "[]"):
            out.append({
                "repo": repo,
                "number": item.get("number"),
                "title": item.get("title"),
                "url": item.get("url"),
                "body": item.get("body") or "",
                "comments": _comment_text(item.get("comments")),
            })
    return out


def collect_kanban_tasks(db_path: Path = KANBAN_DB) -> list[dict[str, Any]]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    comments: dict[str, list[str]] = {}
    try:
        for row in con.execute("select task_id, body from task_comments order by created_at"):
            comments.setdefault(row["task_id"], []).append(row["body"] or "")
    except sqlite3.Error:
        comments = {}
    rows = con.execute(
        "select id,title,body,assignee,status,result,idempotency_key,created_at,completed_at from tasks"
    ).fetchall()
    return [dict(row) | {"comments": "\n".join(comments.get(row["id"], []))} for row in rows]


def _load_fixture(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], int | None, list[str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return (
        list(payload.get("issues") or []),
        list(payload.get("prs") or []),
        list(payload.get("tasks") or []),
        payload.get("now_ts"),
        list(payload.get("errors") or []),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", action="append", dest="repos", help="Repo OA à scanner (répétable). Défaut: repos CORE.")
    parser.add_argument("--kanban-db", default=str(KANBAN_DB), help="Chemin SQLite Kanban en lecture seule.")
    parser.add_argument("--output", default="public/api/agent-loop-audit.json", help="Chemin JSON de sortie.")
    parser.add_argument("--fixture", help="Fixture JSON pour tests/unités, évite GitHub/Kanban live.")
    args = parser.parse_args(argv)

    if args.fixture:
        issues, prs, tasks, now_ts, errors = _load_fixture(Path(args.fixture))
    else:
        errors: list[str] = []
        repos = args.repos or DEFAULT_REPOS
        issues = collect_agent_ok_issues(repos, errors)
        prs = collect_open_prs(repos, errors)
        try:
            tasks = collect_kanban_tasks(Path(args.kanban_db))
        except Exception as exc:
            tasks = []
            errors.append(f"kanban db: {exc}")
        now_ts = None

    report = audit_agent_loop(issues=issues, prs=prs, tasks=tasks, now_ts=now_ts, errors=errors)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    s = report["summary"]
    print(
        "agent-loop-audit "
        f"status={report['status']} total_orphans={s['total_orphans']} "
        f"issues_without_card={s['issues_without_card']} prs_without_gate={s['prs_without_gate']} "
        f"builder_cards_without_gate={s['builder_cards_without_gate']} "
        f"blocked_without_next_action={s['blocked_without_next_action']} stale_scheduled={s['stale_scheduled']} "
        f"output={out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
