# OA QG — qg.omar.paris

Registry opérationnel CORE OA.

## Mission

Visualiser les Apps/repos CORE OA : version, Git, changelog, live, statut, dettes.

## V0 routes

```txt
/
/registry/
/changelog/
/api/core-repos.json
```

## Build

```bash
python3 scripts/build.py
```

## Tests

```bash
python3 -m pytest -q
```
