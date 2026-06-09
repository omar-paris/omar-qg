# Changelog

## V0.2.0 — 2026-06-09

- Données live : GitHub API issues et PRs ouverts par repo (closes #2).
- Health probe HTTP réel par domaine — remplace `live` hardcodé (closes #3).
- Affichage enrichi : colonnes Health, Issues/PRs, timestamp "Mis à jour" (closes #4).
- Swap atomique du dossier `public/` au rebuild (zéro downtime Caddy).
- `built_at` ISO8601 dans `core-repos.json` et dans le header HTML.
- 7 tests — dont 3 nouveaux couvrant les champs live.

## V0.1.0 — 2026-06-08

- Création de `qg.omar.paris` V0 registry.
- Ajout dashboard versions/états repos CORE OA.
- Routes : `/`, `/registry/`, `/changelog/`, `/api/core-repos.json`.
