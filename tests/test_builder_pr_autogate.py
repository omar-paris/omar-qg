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


def test_detects_issue_branch_only_with_builder_marker():
    assert is_builder_pr(pr("feat/issue-35", body="Implemented by oa-builder"))
    assert not is_builder_pr(pr("feat/issue-35", body="human change"))


def test_ignores_unrelated_feature_branch():
    assert not is_builder_pr(pr("feat/local-capability-icons-generator", body="manual"))


def test_gate_body_forbids_auto_merge_and_mentions_review_artifact():
    body = gate_body(pr("builder/agent-ok-pr-smoke-20260614"))
    assert "NE PAS merger" in body
    assert "review_result.json" in body
    assert "H-Omar/default arbitrer" in body
