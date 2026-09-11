# Historical remediation plan — authorization required

## Current state

- The final R2 diff removes the previously tracked operational material and replaces it with an anonymous minimal fixture.
- Earlier public commits remain reachable in Git history.
- This document does not perform any purge, rewrite, ref deletion, issue closure, or visibility change.

## Human-authorized next steps only

1. Classify the historical exposure and determine whether legal, client, or security notification is required.
2. Decide whether a repository-history rewrite is proportionate and authorized.
3. If authorized, execute a separately reviewed incident runbook that preserves evidence, coordinates collaborators, rewrites references safely, and verifies hosting/cache behavior.
4. Record the decision and outcome in the incident system.

No automatic action is permitted from this plan.
