# OA QG Contract — qg.omar.paris

> Date : 2026-06-08. Statut : V0 registry. QG n'est pas Lab, Hub ni OmarTop. QG synthétise l'état CORE OA et renvoie vers les sources.

## Identity

- App ID: `qg`
- Repo/name: `omar-qg`
- Product name: `OA QG`
- Public domain: `qg.omar.paris`
- Scope: CORE OA registry + read-only links to VPS Hermes OA.

## Mission V0

Afficher en une page :

- Apps CORE OA ;
- repos GitHub ;
- versions ;
- changelog ;
- live status ;
- source de vérité ;
- next action.

## Non-goals V0

- Ne pas remplacer Plane/Lab.
- Ne pas recopier Hub/OmarTop.
- Ne pas administrer directement les VPS.
- Ne pas afficher de secrets.

## Sources

- `/home/omar/11-Pilotage/doctrine/oa-operating-manifest/CORE-VPS-APPS-MAP-20260608.md`
- repos locaux sous `/home/omar/23-Offre/actifs/`
- surfaces publiques OA.

## Routes V0

```txt
/
/registry/
/changelog/
/api/core-repos.json
```

## Rebuild automatique

Crontab `omar` — toutes les 30 min :

```
*/30 * * * * /usr/bin/python3 /home/omar/23-Offre/actifs/omar-qg/scripts/build.py >> /home/omar/23-Offre/actifs/omar-qg/var/rebuild.log 2>&1
```

Logs : `tail -f var/rebuild.log`
Rebuild manuel : `python3 scripts/build.py`

## Version

`V0.2.0`
