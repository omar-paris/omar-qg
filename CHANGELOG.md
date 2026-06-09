# Changelog

## V0.4.0 — 2026-06-09

- Catalogue réorganisé par type : Infrastructure, Domaine, Email, Suite, Backup, Téléphonie.
- Option par défaut (★) définie pour chaque type.
- Fournisseurs : Hetzner (VPS), OVH (domaines + email), Infomaniak (kSuite), Telnyx (téléphonie).
- OVH focus : domaines et email pro uniquement, VPS retiré.
- Infomaniak focus : kSuite 1 (défaut) et kSuite 2.
- Telnyx ajouté : numéro local FR + SMS pay-as-you-go, clef Vault confirmée.
- Live OVH : 24 domaines + comptes email actifs affichés au build depuis l'API.
- Statut API par fournisseur visible dans la sidebar partenaires.

## V0.3.0 — 2026-06-09

- UI refonte : sidebar Hub-style (Tailwind + Inter), plus de hero plein écran.
- Accueil et registry fusionnés en une seule page compacte.
- Page Partenaires : Hetzner, OVH, Infomaniak — offres, prix, statut API.
- VPS clients placeholder (connecté API quand les droits OVH seront validés).
- Navigation sidebar : Registry / Partenaires / Changelog.
- Timestamp rebuild dans la sidebar.

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
