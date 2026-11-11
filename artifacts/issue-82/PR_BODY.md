## R2 scope

- Replaces tracked material with an anonymous one-item historical fixture.
- Fails closed when the source timestamp is missing, invalid, or future-dated.
- Keeps `/api/chantiers.json` as the legacy list and publishes v2 at `/api/chantiers-v2.json`.

## Evidence

- R2 artifact: `artifacts/issue-82/README.md`
- R2 historical remediation plan: `artifacts/issue-82/historical-remediation-plan.md`
- Frozen-time tests, full suite, isolated build, and final-diff redaction scan run on the R2 head.

Review gate required: H-Athena. No merge or release authorization.
