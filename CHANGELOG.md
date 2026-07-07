# Changelog

## V0.9.2 — 2026-07-07

- Ajout de `/docs/` : visionneuse Markdown QG pour envoyer à Alex de vrais liens directs lisibles (`/docs/?doc=<slug>`), sans dépendre du `?file=` code-server qui n'ouvre pas l'onglet.
- Publication contrôlée des Markdown de `docs/plans` et `docs/references` vers `public/docs/files/` + index `/api/docs-index.json`.
- Ajout du brief `Fable final — audit autonomie OA en 1h`, prêt à coller dans le Chat VS Code/Fable.

## V0.9.1 — 2026-07-07

- Navigation QG refondue en **5 sections courtes** (`Commandement`, `Production`, `Supervision`, `Standards`, `Journal`) pour éviter l'énorme menu latéral.
- Les anciennes routes restent servies comme **sous-pages contextuelles** de la section active, afin de permettre la revue page-par-page avec Alex sans casser les URLs existantes.
- Préparation durable de la revue Control Tower: conducteur `docs/plans/2026-07-07-qg-revue-page-par-page-control-tower.md` et copie du rapport Google Deepsearch dans `docs/references/2026-07-07-sovereign-multi-agent-architecture-google-deepsearch.md`.

## V0.9.0 — 2026-07-07

- Nouvelle page `/carte/` (2e position de nav, sous le manifeste) — la vision Alex : le puzzle OA entier, une ligne par strate (Produit/Funnel, Fonctionnel/Apps, Technique/Infra, Sécurité, Data, Agents/Boucles), une cellule colorée par module avec KPI et lien source.
- Nouveau collecteur `scripts/collect_carte.py` (schéma `oa.carte/1`, `/api/carte.json`) : mappe standards OmarTop × verdicts vps-report, chantiers PRODUCT-TRUTH, inventaire apps, boucles et blocages sécurité. Règle des couleurs gravée : vert=mesuré conforme, jaune=partiel/UNKNOWN mesuré, rouge=FAIL/blocage, gris=jamais mesuré (dette de mesure, jamais un acquis).
- KPI global à deux chiffres (« puzzle mesuré à X % · conforme à Y % du mesuré ») + KPI par strate ; `var/boucles.json` republié en `/api/boucles.json` ; tests purs du collecteur sur fixtures (zéro réseau, zéro ellipsis dans les tooltips).

## V0.8.5 — 2026-06-30

- QG `/ops/` qualifie désormais le signal Docker : `theoretical_reclaimable_hint` reste visible mais ne devient une action que si des images dangling, containers arrêtés ou volumes orphelins sont prouvés.
- Correction anti-faux positif : le `18 GB reclaimable` Docker n’est plus traité comme gain actionnable quand toutes les grosses images sont référencées par des containers actifs.

## V0.8.4 — 2026-06-30

- Page `/ops/` enrichie avec un bloc read-only `Stockage & sauvegardes` : root VPS, volumes Hetzner, swap, backups Hermes DB, remotes rclone et actions recommandées.
- Nouvel endpoint `/api/ops/storage-summary.json` généré par `scripts/collect_storage.py`, sans secrets ni listing de contenu cloud.
- Portage propre d’une fonctionnalité locale non mergée depuis le checkout QG divergent vers une branche basée sur `origin/main`.

## V0.8.3 — 2026-06-30

- Page `/agent-loop/` enrichie avec les boucles prouvées du registry P4 : PR, cartes Kanban, gates, merge et artefacts issus du run réel AppOmar PR#48.
- Nouvel endpoint `/api/agent-loop-registry.json` généré read-only depuis `scripts/agent_loop_registry.py`, sans requête SQLite directe côté QG, avec seed injectable en test via `OA_AGENT_LOOP_REGISTRY_SEED`.
- Tests de surface et d'API pour garantir que la preuve PR#48 reste visible dans QG.

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
