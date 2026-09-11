## Scope

- Versionne la source Chantiers et conserve l'archive du 04/07.
- Publie le contrat `oa.chantiers/v2` avec compatibilité `/api/chantiers-legacy.json`.
- Fraîcheur fondée exclusivement sur `source.checked_at`; aucune collecte distante ni publication.

## Evidence

- Base: `34c58a5976da70ec524d93b6b4e97b2fdd884646`
- Artefact H-Athena: `artifacts/issue-82/README.md`
- TDD: rouge 3 échecs, puis vert 4/4.
- Régression isolée: 94 passed.
- Build isolé: `/tmp/omar-qg-issue82-build-20260911` (copie durable dans `artifacts/issue-82/`).

Refs #82

Review gate requis: H-Athena. Aucun merge/deploy demandé.
