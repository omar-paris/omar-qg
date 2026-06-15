import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_audit_detects_agent_ok_issue_without_kanban_card():
    from scripts.agent_loop_audit import audit_agent_loop

    report = audit_agent_loop(
        issues=[{"repo": "omar-qg", "number": 13, "title": "P0 sécurité", "url": "https://github.com/omar-paris/omar-qg/issues/13"}],
        prs=[],
        tasks=[],
        now_ts=1_800_000_000,
    )

    assert report["summary"]["issues_without_card"] == 1
    orphan = report["issues_without_card"][0]
    assert orphan["repo"] == "omar-qg"
    assert orphan["expected_key"] == "agentok-omar-qg-13"
    assert orphan["action"] == "create_builder_card"


def test_audit_counts_existing_agentok_card_as_linked():
    from scripts.agent_loop_audit import audit_agent_loop

    report = audit_agent_loop(
        issues=[{"repo": "omar-qg", "number": 13, "title": "P0 sécurité", "url": "u"}],
        prs=[],
        tasks=[{"id": "t_build", "idempotency_key": "agentok-omar-qg-13", "status": "done", "assignee": "oa-builder"}],
        now_ts=1_800_000_000,
    )

    assert report["issues_without_card"] == []


def test_audit_detects_open_pr_without_gate_unless_decision_required():
    from scripts.agent_loop_audit import audit_agent_loop

    report = audit_agent_loop(
        issues=[],
        prs=[
            {"repo": "omar-qg", "number": 37, "title": "Builder PR", "url": "https://github.com/omar-paris/omar-qg/pull/37", "body": "Refs #13"},
            {"repo": "omar-hub", "number": 56, "title": "Decision needed", "url": "https://github.com/omar-paris/omar-hub/pull/56", "body": "decision_required: attente Alex"},
            {
                "repo": "omar-hub",
                "number": 34,
                "title": "Decision needed in comments",
                "url": "https://github.com/omar-paris/omar-hub/pull/34",
                "body": "Refs #34",
                "comments": [{"body": "decision_required: attente Alex"}],
            },
        ],
        tasks=[],
        now_ts=1_800_000_000,
    )

    assert report["summary"]["prs_without_gate"] == 1
    assert report["prs_without_gate"][0]["expected_key"] == "builder-pr-gate:omar-qg:37"
    assert report["prs_without_gate"][0]["action"] == "create_athena_gate_card"


def test_collect_open_prs_preserves_github_comment_bodies(monkeypatch):
    from scripts import agent_loop_audit

    def fake_run(cmd, *, timeout=90, check=False):
        assert "number,title,url,body,comments" in cmd
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps([
                {
                    "number": 34,
                    "title": "Decision in thread",
                    "url": "https://github.com/omar-paris/omar-hub/pull/34",
                    "body": "body only",
                    "comments": [{"body": "decision_required: attente Alex"}],
                }
            ]),
            stderr="",
        )

    monkeypatch.setattr(agent_loop_audit, "run", fake_run)
    errors = []
    prs = agent_loop_audit.collect_open_prs(["omar-hub"], errors)

    assert errors == []
    assert prs[0]["comments"] == "decision_required: attente Alex"
    assert agent_loop_audit.audit_agent_loop(issues=[], prs=prs, tasks=[], now_ts=1_800_000_000)["prs_without_gate"] == []


def test_audit_detects_review_required_builder_card_without_athena_gate():
    from scripts.agent_loop_audit import audit_agent_loop

    tasks = [
        {
            "id": "t_builder",
            "title": "build: omar-qg#13",
            "assignee": "oa-builder",
            "status": "blocked",
            "body": "PR: https://github.com/omar-paris/omar-qg/pull/37",
            "comments": "review-required handoff",
        }
    ]
    report = audit_agent_loop(issues=[], prs=[], tasks=tasks, now_ts=1_800_000_000)

    assert report["summary"]["builder_cards_without_gate"] == 1
    assert report["builder_cards_without_gate"][0]["card_id"] == "t_builder"
    assert report["builder_cards_without_gate"][0]["expected_key"] == "builder-pr-gate:omar-qg:37"


def test_audit_ignores_review_required_builder_card_with_gate():
    from scripts.agent_loop_audit import audit_agent_loop

    tasks = [
        {
            "id": "t_builder",
            "title": "build: omar-qg#13",
            "assignee": "oa-builder",
            "status": "blocked",
            "body": "PR: https://github.com/omar-paris/omar-qg/pull/37",
            "comments": "review-required handoff",
        },
        {"id": "t_gate", "assignee": "oa-athena", "status": "ready", "idempotency_key": "builder-pr-gate:omar-qg:37"},
    ]
    report = audit_agent_loop(issues=[], prs=[], tasks=tasks, now_ts=1_800_000_000)

    assert report["builder_cards_without_gate"] == []


def test_audit_detects_blocked_without_owner_or_next_action_and_stale_scheduled():
    from scripts.agent_loop_audit import audit_agent_loop

    tasks = [
        {"id": "t_blocked_bad", "title": "stuck", "status": "blocked", "assignee": "oa-builder", "body": "blocked: attente", "comments": "cause: flou"},
        {"id": "t_blocked_ok", "title": "blocked", "status": "blocked", "assignee": "oa-builder", "body": "owner: h-omar\nnext_action: trancher A/B"},
        {"id": "t_sched_old", "title": "scheduled 2026-01-01", "status": "scheduled", "assignee": "hm-focus", "body": "raison: vieux"},
        {"id": "t_sched_future", "title": "scheduled 2030-01-01", "status": "scheduled", "assignee": "hm-focus", "body": "next_action: attendre"},
    ]
    report = audit_agent_loop(issues=[], prs=[], tasks=tasks, now_ts=1_800_000_000)

    assert [x["card_id"] for x in report["blocked_without_next_action"]] == ["t_blocked_bad"]
    assert [x["card_id"] for x in report["stale_scheduled"]] == ["t_sched_old"]


def test_cli_writes_public_agent_loop_audit_json_from_fixtures(tmp_path):
    fixtures = tmp_path / "fixtures.json"
    out = tmp_path / "agent-loop-audit.json"
    fixtures.write_text(json.dumps({
        "issues": [{"repo": "omar-qg", "number": 13, "title": "P0", "url": "issue-url"}],
        "prs": [{"repo": "omar-qg", "number": 37, "title": "PR", "url": "pr-url", "body": "Refs #13"}],
        "tasks": [],
        "now_ts": 1_800_000_000,
    }), encoding="utf-8")

    cp = subprocess.run(
        ["python3", "scripts/agent_loop_audit.py", "--fixture", str(fixtures), "--output", str(out)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert "agent-loop-audit" in cp.stdout
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema"] == "oa.agent-loop-audit/1"
    assert payload["summary"]["total_orphans"] == 2


def test_qg_renders_agent_loop_page_and_home_tile_without_mutating_public():
    from scripts.build import page_agent_loop_audit, page_registry

    seed = {
        "schema": "oa.agent-loop-audit/1",
        "status": "degraded",
        "checked_at": "2026-06-15T00:00:00+00:00",
        "summary": {"total_orphans": 1, "issues_without_card": 1, "prs_without_gate": 0, "builder_cards_without_gate": 0, "blocked_without_next_action": 0, "stale_scheduled": 0},
        "issues_without_card": [{"repo": "omar-qg", "number": 13, "title": "P0", "url": "u", "expected_key": "agentok-omar-qg-13", "action": "create_builder_card"}],
        "prs_without_gate": [],
        "builder_cards_without_gate": [],
        "blocked_without_next_action": [],
        "stale_scheduled": [],
        "errors": [],
    }

    page = page_agent_loop_audit(seed)
    home = page_registry(
        {
            "items": [],
            "counts": {
                "total": 0,
                "healthy": 0,
                "degraded": 0,
                "down": 0,
                "unknown": 0,
                "open_issues_total": 0,
                "open_prs_total": 0,
                "core": 0,
            },
        },
        agent_loop_audit=seed,
    )

    assert "Audit anti-orphelins" in page
    assert "Issue agent-ok sans carte" in page
    assert "agentok-omar-qg-13" in page
    assert 'href="/agent-loop/"' in home
