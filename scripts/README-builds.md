# build-ledger — « Builds du jour » du QG

Génère `public/api/builds.json` : les commits du jour (et des 7 derniers jours)
sur chaque repo `/home/omar/23-Offre/actifs/omar-*`, agrégés par jour et par repo,
plus les déploiements récents détectés (pages QG modifiées sous `public/`).

Alimente :
- la page **`/builds/`** (timeline par jour, groupée par repo, compteurs) ;
- la tuile **« Builds aujourd’hui : N »** sur la home du QG.

## Comment c'est branché

`scripts/build.py` (le générateur maître du QG, déjà en cron `*/30`) importe
`collect_builds()` depuis `build-ledger.py` et écrit `builds.json` à **chaque
rebuild**. Donc tant que le cron `build.py` tourne, `builds.json` est déjà à jour
toutes les 30 min — **aucun cron supplémentaire n'est nécessaire**.

Le cron ci-dessous n'est utile que si on veut rafraîchir `builds.json` **seul**,
plus souvent ou couplé à l'observateur, sans relancer tout le QG.

## Lancer à la main

```bash
python3 scripts/build-ledger.py            # écrit public/api/builds.json
python3 scripts/build-ledger.py --print    # affiche le JSON sans écrire
python3 scripts/build-ledger.py --out /tmp/builds.json
```

## Cron (NON activé — à décider par Alex)

Rafraîchir `builds.json` seul toutes les heures :

```cron
# Builds du jour — régénère public/api/builds.json (NON activé)
0 * * * * /usr/bin/python3 /home/omar/23-Offre/actifs/omar-qg/scripts/build-ledger.py >> /home/omar/23-Offre/actifs/omar-qg/var/builds.log 2>&1
```

Ou couplé au briefing observateur de 6h (une passe quotidienne avant le briefing) :

```cron
# 06h00 — builds.json frais juste avant l'observateur (NON activé)
0 6 * * * /usr/bin/python3 /home/omar/23-Offre/actifs/omar-qg/scripts/build-ledger.py >> /home/omar/23-Offre/actifs/omar-qg/var/builds.log 2>&1
```

> Rappel : `build.py` (cron `*/30`) écrase `public/` à chaque passe. Si tu lances
> `build-ledger.py` seul entre deux rebuilds, sa sortie sera remplacée au prochain
> `build.py` — ce qui est sans conséquence puisque `build.py` régénère le même
> `builds.json`. Les deux sources sont cohérentes.
