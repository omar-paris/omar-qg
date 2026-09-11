# Issue #82 — artefact R2 redacted

- Branch: `fix/issue-82-chantiers-truth`
- Baseline: `34c58a5976da70ec524d93b6b4e97b2fdd884646`
- Scope: R2 fixes F1-F3 only. No merge, deploy, restart, cron, or remote collection.

## R2 contract

- Tracked data is a one-item anonymous historical fixture with no tenant, person, internal path, or operational assertion.
- `checked_at` missing, invalid, or later than the frozen evaluation time fails closed to `unknown`, with empty `items` and non-empty `errors`.
- `/api/chantiers.json` remains the legacy JSON list.
- `/api/chantiers-v2.json` publishes `oa.chantiers/v2`.
- The HTML renders the v2 verdict and links both endpoints.

## Evidence

- Targeted frozen-time tests: 6 passed.
- Isolated build output is copied in this directory:
  - `chantiers.legacy.json`
  - `chantiers.v2.json`
  - `chantiers.html`
  - `R2_EVIDENCE.md`
  - `historical-remediation-plan.md`
- Full regression and final diff scans are recorded after the R2 commit.

## Historical remediation status

An earlier public commit contains material now removed from the final base-to-head diff. Git history remains publicly reachable. This R2 does not rewrite, purge, delete, close, change visibility, or otherwise alter historical refs. Any historical remediation requires an explicit human-authorized incident procedure.
