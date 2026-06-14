from scripts.builder_pr_autogate import PullRequest, gate_body, is_builder_pr


def pr(head, body="", title="docs"):
    return PullRequest(
        repo="omar-qg",
        number=36,
        title=title,
        url="https://github.com/omar-paris/omar-qg/pull/36",
        head_ref=head,
        base_ref="main",
        is_draft=True,
        author="alexwill87",
        body=body,
    )


def test_detects_builder_prefix():
    assert is_builder_pr(pr("builder/agent-ok-pr-smoke-20260614"))


def test_detects_issue_branch_only_with_structured_builder_marker():
    assert is_builder_pr(pr("feat/issue-35", body="Generated-by: oa-builder"))
    assert is_builder_pr(pr("feat/issue-35", body="Smoke-check builder vérifié"))
    assert not is_builder_pr(pr("feat/issue-35", body="human change"))


def test_ignores_h_omar_pr_that_mentions_oa_builder():
    assert not is_builder_pr(pr("h-omar/autogate-builder-athena-20260614", body="detect oa-builder body markers"))


def test_ignores_unrelated_feature_branch():
    assert not is_builder_pr(pr("feat/local-capability-icons-generator", body="manual"))


def test_gate_body_forbids_auto_merge_and_mentions_review_artifact():
    body = gate_body(pr("builder/agent-ok-pr-smoke-20260614"))
    assert "NE PAS merger" in body
    assert "review_result.json" in body
    assert "H-Omar/default arbitrer" in body


def test_write_status_artifact(tmp_path):
    from scripts.builder_pr_autogate import write_status
    import json

    out = tmp_path / "builder-pr-autogate.json"
    sample = pr("builder/agent-ok-pr-smoke-20260614")
    write_status(out, status="healthy", repos=["omar-qg"], prs=[sample], cards=["Created t_x"], errors=[])
    payload = json.loads(out.read_text())
    assert payload["status"] == "healthy"
    assert payload["builder_prs_found"] == 1
    assert payload["builder_prs"][0]["url"].endswith("/36")
    assert payload["last_error"] is None


def test_discovery_errors_make_status_degraded(tmp_path, monkeypatch):
    import json
    from scripts import builder_pr_autogate as mod

    def boom(repo_name):
        raise RuntimeError("gh unavailable")

    monkeypatch.setattr(mod, "list_open_prs", boom)
    out = tmp_path / "status.json"
    rc = mod.main(["--repo", "omar-qg", "--dry-run", "--status-output", str(out)])
    payload = json.loads(out.read_text())
    assert rc == 1
    assert payload["status"] == "degraded"
    assert payload["last_error"]
    assert "omar-qg" in payload["last_error"]
