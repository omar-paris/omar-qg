# Changelog

## V0.8.2 — 2026-06-15

- Audit anti-orphelins Issue↔Kanban↔PR↔Gate : commande read-only `scripts/agent_loop_audit.py`, endpoint `/api/agent-loop-audit.json`, page `/agent-loop/` et tuile QG pour actions à prendre.

## V0.8.1 — 2026-06-15

- mandat:h-omar-night-2026-06-14 — Accueil QG : bloc visible "Dernier résultat livré" + "Décisions / mandats" pour exposer preuves de build et rattachements `mandat:*` / `decision:*`.

## V0.8.0 — 2026-06-14

- Standard 3 QG : isolation client RBAC en build statique Niveau 2 (`/api/client-jab.json` + `/client/jab/`).
- Gate Athena round 2 PASS : correction de la fuite de nom live Hetzner (`ubuntu-4gb-jab`) et blocage defense-in-depth de `specs`/`cost`.
- Vue OmarTop réalignée : mandat opérationnel autonome H-Omar mergé côté OmarTop et visible dans QG (`d3f386e`).
- Discipline opérateur : H-Omar reste orchestrateur ; les missions longues partent en background borné avec rapport, pas en blocage de conversation.
- Baseline Mission #1 Kanban/QG produite : backlog visible, PRs restantes, files `ready/blocked/todo` priorisées.

## V0.7.0 — 2026-06-09

- Nouvelle page `/ops/` : consolidation quotidienne sessions Hermes, sessions Claude/CLI, issues, PRs, merges, builds, coûts tokens, repos dirty et alertes.
- Nouvel endpoint `/api/daily-ledger/index.json` et snapshot daté `/api/daily-ledger/YYYY-MM-DD.json`.
- Ajout `scripts/record_build.py` pour tracer les builds locaux dans `/home/omar/11-Pilotage/ledgers/builds/YYYY-MM-DD.jsonl`.
- Alertes automatiques : repos dirty, absence de builds enregistrés, sessions nombreuses sans PR, PRs créées non mergées.

## V0.6.0 — 2026-06-09

- Nouvelle page Clients & VPS sous Registry : galerie 2 colonnes.
- Flotte Hetzner live : 3 VPS (Omar CORE, Pantheos STUDIO, JAB CLIENT).
- 11 infos par VPS : rôle, owner, IP, type, specs, disque, datacenter, OS, créé, coût, backups, trafic.
- Liens par VPS : Hub local, Hermes UI, monitoring (Glances, Dashy, Console Hetzner).
- Liens "à installer" marqués pour Pantheos et JAB (Hub/HermesUI/Glances à venir).
- Stats flotte : nb VPS, running, coût mensuel total.

## V0.5.0 — 2026-06-09

- Statut API fournisseurs en temps réel : probe live de chaque provider au build.
- OVH (GET /me signé), Telnyx (GET /balance), Hetzner (GET /servers), Infomaniak (GET /profile).
- Lit la clef depuis Vault ; "API OK" / "Clef à ajouter" / "Erreur API" automatiques.
- Dès qu'une clef est ajoutée dans Vault, le statut passe à OK au rebuild suivant.
- Zéro token, zéro intervention : tourne via le cron 30 min existant.
- OVH live data n'est chargée que si son API répond.

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
