# QG capability eval summary
- schema: oa.capabilities-eval/1
- generated_at: 2026-07-01T21:22:11.743239+00:00
- source_generated_at: 2026-07-01T22:52:49+02:00
- status: fresh (stale=false, age_hours=0.49)
- capabilities_total: 21

## Counts
- installed: 19
- reachable: 10
- integrated: 11
- used: 13
- measured: 4

## Top gaps
1. Langfuse/LiteLLM — Installed and healthy, but not proven as the default trace path for Hermes/Kanban/AppOmar LLM calls.
   - next: oa-vps-operator smoke: one non-secret LiteLLM call with Langfuse trace id and documented callback config.
2. Capability context injection — Registry exists, but missions do not automatically receive filtered relevant capability entries.
   - next: Add mission template field capability_context_ids + small extractor script.
3. QG cockpit — QG/HermesUI reachable but capability adoption is not a first-class widget with stale/fresh status.
   - next: oa-builder surface /api/capabilities-eval.json + compact /ops card.
4. Kanban quality — Kanban is measured by counts but not by capability outcomes/artifact-contract failures.
   - next: oa-qa-officer daily metric: blocked_by_capability, done_without_artifact, review-required aging.
5. Profile hygiene — Stopped legacy h-omar profile exists; board also references historical/nonspawnable assignees.
   - next: Inventory nonspawnable assignees and mark/decommission or alias explicitly.

## Next action
Dispatch/complete parent then run t_752c3d43 first: LiteLLM→Langfuse non-secret trace smoke.

## Agent context contract
Agents doivent demander un champ `capability_context_ids` filtré (3 à 8 ids max) et recevoir uniquement les champs non sensibles autorisés par capacité.
- recommended_initial_ids: langfuse, litellm, kanban, profiles, agent-registry, hermes-default, qg-static-api, qg-hermesui
- allowed_fields: id, name, type, status, owner, known_gaps, how_to_use, proof_command, security_scope, last_checked
