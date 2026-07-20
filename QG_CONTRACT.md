# OA QG Contract — qg.omar.paris

> Date : 2026-07-06. Statut : QG de supervision OA en convergence. QG n'est pas Lab, Hub ni OmarTop : il compte, pointe et renvoie vers les sources.

## Identity

- App ID: `qg`
- Repo/name: `omar-qg`
- Product name: `OA QG`
- Public domain: `qg.omar.paris` (tailnet-only)
- Source repo: `/home/omar/23-Offre/actifs/omar-qg`
- Live target: `/home/omar/23-Offre/actifs/omar-qg-live`

## Mission

Afficher en un cockpit :

- blocages/action Alex et agents ;
- chantiers Now/Next/Later ;
- registry CORE OA avec versions et liens ;
- boucles agents et preuves ;
- ops quotidiennes, repo-health, stockage et fournisseurs.

## Non-goals

- Ne pas remplacer Lab/Plane historique, Hub, OmarTop ou AppOmar.
- Ne pas administrer directement les VPS.
- Ne pas afficher de secrets.
- Ne pas prétendre qu'un snapshot ancien est live.
- Ne pas multiplier les compteurs concurrents pour une même donnée.

## Sources

- Repos locaux sous `/home/omar/23-Offre/actifs/`.
- `var/*.json` produit par les collecteurs QG.
- `/home/omar/11-Pilotage/sujets-actifs/inter-vps-inbox/**/*health*.json` pour les rapports `oa.vps-report/v1` redacted des VPS.
- `/home/omar/.hermes/kanban.db` en lecture seule pour les blocages/boucles.
- GitHub `omar-paris` pour issues, PRs et commits.
- Doctrine CORE OA quand elle existe ; sinon le QG affiche explicitement `non mesuré`.

## Routes actuelles

```txt
/
/blocages/
/chantiers/
/ops/
/manifeste/
/docs/
/objectifs/
/agent-loop/
/clients/
/decisions/
/partenaires/
/builds/
/changelog/
/apps/{landing,app,catalogue,lab,qg,hub,omartop}/
/api/*.json
```

### Push mTLS QG-100

`POST /api/ingest/vps-report` reçoit les enveloppes montantes `oa.vps-report/v1` par stream (`heartbeat`, `verdicts`, `expected-work`, `error-fingerprint`, `oa-cost`). Le QG valide `producer_epoch` + `sequence`, vérifie `payload_hash`, exige une identité transport non spoofable par header HTTP direct, persiste dans une base SQLite dédiée/propre `var/qg-ingest/qg-ingest.sqlite3`, puis seulement après commit répond `oa.qg-ack/v1` avec `accepted_through`, `gaps`, `duplicates`, `quarantined`.

Variables runtime :

- `QG_INGEST_DB` : chemin de la base propre dédiée ;
- `QG_INGEST_REQUIRE_MTLS` : `1` par défaut, `0` uniquement pour smoke local/tests ;
- `QG_INGEST_TLS_CERT`, `QG_INGEST_TLS_KEY`, `QG_INGEST_TLS_CA` : activent un serveur direct HTTPS+mTLS ;
- `QG_INGEST_TRUST_PROXY_HEADERS=1` + `QG_INGEST_PROXY_SHARED_SECRET` : autorisent un reverse-proxy contrôlé à injecter un header d'identité signé (`x-oa-proxy-signature`). Sans signature valide, `x-oa-client-cert-subject` est ignoré et l'appel est rejeté.

## Reporting inter-VPS

### Flotte VPS sur /ops/ (vue multi-VPS)

`/ops/` ouvre sur le bloc **Flotte VPS** (API : `/api/ops/vps-fleet.json`, schéma `oa.vps-fleet-status/1`) :

- ligne globale « N VPS rapportent · M en dérive · K muet(s) » ;
- un bloc par VPS attendu (`omar`, `jab`, `pantheos`) : maturité en grand (X PASS / Y FAIL + %), liste intégrale des standards FAIL (item_id + preuve redacted, zéro ellipsis), compteur apps par kind, next_action ownerisée, horodatage ;
- rapport absent ou stale (> 36 h) = bloc ambre avec outbox attendue + owner transport (`jab` → cc-jab, `pantheos` → h-aurel) — un VPS muet est une alerte (doctrine H-Omar) ;
- `oa-master` est un alias santé du même VPS que `omar` : jamais compté comme 4e nœud ;
- pied de bloc : « SAV : non instrumenté — aucun flux SAV n'existe encore » (honnêteté, décision Alex).

La home porte la tuile « x/y VPS rapportent · m standard(s) FAIL » qui pointe vers `/ops/`.

### Blockers multi-VPS sur /blocages/

`collect_blocages.py` agrège les `blockers[]` des rapports non-omar avec `origine=<node>` (type `vps`), dédupliqués contre les entrées locales — les blockers d'omar.json PROVIENNENT de blocages.json et ne sont jamais doublés. Un blocker remote qui duplique une entrée locale annote celle-ci (`aussi_signale_par`). Le payload expose `vps_blockers` (total/uniques/dédupliqués par nœud) et la page montre la section « Multi-VPS » avec badge d'origine.

### Inventaire applicatif/versionné par VPS

Le QG publie `/api/vps-app-inventory.json` et rend le bloc **Inventaire apps/version par VPS** dans `/clients/`.

Source acceptée : rapports `oa.vps-report/v1` redacted reçus depuis les agents Hermes locaux.

Chaque rapport peut porter `installed_apps[]` avec :

```json
{
  "app_id": "hermes",
  "name": "Hermes Agent",
  "installed": true,
  "version_installed": "x.y.z ou unknown",
  "version_expected": "policy-current",
  "status": "ok|outdated|missing|unknown|blocked",
  "source": "command|package|service|file|manual|report",
  "evidence": "preuve courte redacted",
  "last_checked_at": "ISO timestamp"
}
```

Applications minimales suivies par VPS : `hermes`, `omarhub`, `tailscale`, `reverse-proxy`, `inter-vps-reporter`.

Règles :

- `unknown` vaut mieux qu'une version inventée.
- Aucun secret, token, log brut, contenu client/familial dans l'API QG.
- Si `installed_apps` manque, le QG infère seulement des statuts prudents depuis `services/security/resources`, sinon `unknown`.

## Architecture cible

Cible produit après gates de fusion : 5 pages.

```txt
/
/blocages/
/chantiers/
/boucles/
/ops/
```

Les pages legacy restent accessibles jusqu'aux étapes 6-8 du plan de convergence. Toute suppression/fusion de page nécessite une review séparée. La route `/boucles/` reste une cible tant que le chantier boucles séparé n'est pas validé ; ce commit ne l'active pas.

## Rebuild automatique et publication

### Boucle feedback Alex depuis /blocages/

Les réponses inline `POST /api/blocages/answer` passent aussi dans `scripts/collect_feedback_alex.py` en best-effort. Le collecteur détecte les signaux faibles (`???`, ton négatif, lien/action impossible, erreur/cassé), rédige un extrait court redacted et déduplique via `var/feedback-alex-seen.json`.

- Défaut sûr: `OA_FEEDBACK_ALEX_MODE=dry-run` (ou variable absente) écrit seulement `var/feedback-alex-local.log`, sans notification.
- Désactivation: `OA_FEEDBACK_ALEX_MODE=off`.
- Activation création locale: `OA_FEEDBACK_ALEX_MODE=create` crée une carte Kanban triage `[FEEDBACK-ALEX]` avec `--assignee default`, `--created-by oa-secretaire` et `--idempotency-key feedback-alex:*`.
- Vérification: consulter le log local, puis le dashboard Kanban en triage; aucune donnée sensible brute ni @groupe automatique.

Rebuild local :

```bash
python3 scripts/build.py
```

Publication contrôlée :

```bash
python3 scripts/build.py
rsync -a --delete public/ ../omar-qg-live/
```

Contrat : `public/` est un artefact généré. Le build doit pouvoir le recréer ; le live est synchronisé par `rsync --delete` pour éviter les routes fantômes.

## Fraîcheur honnête

- `/blocages/`, `/ops/`, repo-health et registry : collecteurs vivants au build.
- `/objectifs/` : snapshot figé depuis le 14/06 tant que `var/objectifs.json` n'est pas réactivé.
- `/agent-loop/` : audit anti-orphelins figé depuis le 15/06 si `checked_at` reste au 2026-06-15.
- Chaque page doit exposer son API ou son horodatage source quand disponible.

## Gates

- Avant commit : `python3 -m pytest -q` vert.
- Avant publication : build local vert + `rsync -a --delete public/ ../omar-qg-live/` + smoke HTTP des 5 routes cibles.
- Review-gate Athena obligatoire avant fusion/release durable.

## Version

Voir `VERSION`.
