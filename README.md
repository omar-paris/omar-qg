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

Note de convergence : la cible produit est 5 pages (`/`, `/blocages/`, `/chantiers/`, `/boucles/`, `/ops/`). Les routes legacy restent servies tant que les étapes de fusion/suppression n'ont pas reçu leur gate. `/boucles/` est cible mais non activé dans ce commit car le travail boucles local est explicitement hors périmètre/NO-GO.

## Garde-fou anti-accumulation surfaces

La navigation primaire QG est plafonnée à 5 sections dans `scripts/build.py` (`MAX_PRIMARY_NAV_SECTIONS = 5`). Toute route servie doit passer `validate_surface_governance()` avec un contrat portant décision tracée, owner autorisé (`Alexandre` ou `H-Omar`), rôle, source canonique, fraîcheur, preuve attendue et justification de non-fusion.

Le build publie `/api/qg-surface-governance.json` pour rendre ce contrat vérifiable. Une nouvelle route sans entrée dans `route_surface_contracts()` fait échouer le build/tests au lieu de créer une surface niveau 1 par accumulation.

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
