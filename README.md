# OA QG — qg.omar.paris

QG opérationnel OA : le cockpit compte, pointe et renvoie vers les sources de vérité. Il ne doit pas dupliquer durablement les décisions, les preuves, les repos ou les apps.

## Mission

Visualiser l'état des apps/repos CORE OA et des boucles de pilotage : blocages, chantiers, santé repo, ops, versions, liens GitHub/domaines et preuves utiles.

## Routes actuelles

Routes servies aujourd'hui par `scripts/build.py` :

```txt
/
/blocages/
/chantiers/
/ops/
/manifeste/
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

## Ingest QG-100

L'API runtime `scripts/qg_api.py` expose aussi `POST /api/ingest/vps-report` pour les pushs inter-VPS `oa.vps-report/v1`:

- validation stricte de l'enveloppe `schema_name=oa.vps-report`, `schema_version=1`, `producer_epoch`, `sequence`, `payload_hash` ;
- preuve transport obligatoire par défaut (`QG_INGEST_REQUIRE_MTLS=1`) ;
- le mode direct accepte uniquement un certificat client réel présenté sur la socket TLS Python (`QG_INGEST_TLS_CERT`, `QG_INGEST_TLS_KEY`, `QG_INGEST_TLS_CA`) ;
- le mode reverse-proxy n'accepte un header d'identité (`x-oa-client-cert-subject`) que si `QG_INGEST_TRUST_PROXY_HEADERS=1` et si le proxy ajoute `x-oa-proxy-signature=sha256:<hmac>` avec `QG_INGEST_PROXY_SHARED_SECRET` ; un header HTTP direct non signé reste rejeté ;
- persistance durable dans une base SQLite propre dédiée (`QG_INGEST_DB`, défaut `var/qg-ingest/qg-ingest.sqlite3`) ;
- réponse après commit au contrat `oa.qg-ack/v1` avec `accepted_through`, `gaps`, `duplicates`, `quarantined`.

Smoke local sans cert réel (tests uniquement) : `QG_INGEST_REQUIRE_MTLS=0 QG_INGEST_DB=/tmp/qg-ingest.sqlite3 python3 scripts/qg_api.py`.

Note de convergence : la cible produit est 5 pages (`/`, `/blocages/`, `/chantiers/`, `/boucles/`, `/ops/`). Les routes legacy restent servies tant que les étapes de fusion/suppression n'ont pas reçu leur gate. `/boucles/` est cible mais non activé dans ce commit car le travail boucles local est explicitement hors périmètre/NO-GO.

## Build local

```bash
python3 scripts/build.py
```

Le build reconstruit `public/` depuis les collecteurs et `var/*.json`. `public/` est un artefact généré : ne pas l'éditer à la main.

## Publication live

La publication QG se fait par reconstruction puis synchronisation vers le répertoire live :

```bash
python3 scripts/build.py
rsync -a --delete public/ ../omar-qg-live/
```

Le site est servi depuis `/home/omar/23-Offre/actifs/omar-qg-live` (tailnet-only via Caddy). La tâche cron historique reconstruit régulièrement le QG ; la publication contrôlée utilise `rsync --delete` pour éviter les pages fantômes.

## Données et fraîcheur

- Sources runtime : `var/*.json`, Kanban DB, GitHub, repos locaux et collecteurs read-only.
- Snapshots historiques identifiés : `/objectifs/` est figé depuis le 14/06 ; `/agent-loop/` est figé depuis le 15/06 tant que son audit n'est pas recronifié.
- Les compteurs de blocage doivent venir de `collect_blocages.py` / `var/blocages.json` pour éviter le double comptage.

## Tests

```bash
python3 -m pytest -q
```

## Smoke PR autonome

Chemin minimal builder : branche dédiée, note README non-risque, `python3 -m pytest -q`, commit, push, puis draft PR liée à l'issue.
