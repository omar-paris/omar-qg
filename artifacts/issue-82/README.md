# Issue #82 — artefact Builder pour H-Athena

- Repository: `omar-paris/omar-qg`
- Branche: `fix/issue-82-chantiers-truth`
- Base initiale vérifiée: `34c58a5976da70ec524d93b6b4e97b2fdd884646`
- Artefact build figé (commit de contenu): `eaf395938d018abde053bb187ee8fe5924ebb3ba`
- Commit de synthèse: voir la tête de branche après ce document.
- Portée: contrat de vérité Chantiers uniquement; aucune collecte distante, publication, deploy, restart, cron, ni secret.

## Contrat livré

- Source versionnée: `data/chantiers.json` (`oa.chantiers-source/v1`).
- Archive historique inchangée: `data/chantiers-2026-07-04.json` (copie de l'ancien `var/chantiers.json`, 8 items).
- Projection publique v2: `oa.chantiers/v2`, explicitement versionnée par `schema` et `contract_version: 2`.
- Compatibilité: `/api/chantiers-legacy.json` conserve la liste pour les consommateurs legacy; `/api/chantiers.json` devient le contrat v2.
- Fraîcheur: seulement `fresh|stale|unknown`, calculée à partir de `source.checked_at` + TTL. `built_at` n'est ni lu ni passé au calcul.
- Historique du 04/07: conservé, rendu comme `stale` et avec libellé « Historique ».
- Source manquante/non parsable: contrat v2 `unknown`, items vides; aucune projection publique précédente n'est reprise.
- Champs rendus: source, checked_at, freshness, remaining_gap, owner et prochaine preuve.

## Fichiers changés

- `scripts/build.py`
- `data/chantiers.json`
- `data/chantiers-2026-07-04.json`
- `tests/test_chantiers_truth.py`
- `artifacts/issue-82/chantiers.v2.json`
- `artifacts/issue-82/chantiers.legacy.json`
- `artifacts/issue-82/chantiers.html`
- `artifacts/issue-82/README.md`
- `artifacts/issue-82/PR_BODY.md`

## TDD et vérifications exécutées

1. Rouge (avant implémentation):

```text
uv run --with pytest pytest -q tests/test_chantiers_truth.py
3 failed in 0.31s
AttributeError: normalize_chantiers_contract/load_chantiers_contract absent
```

2. Vert ciblé, temps figé:

```text
uv run --with pytest pytest -q tests/test_chantiers_truth.py
4 passed in 0.18s
```

Les quatre comportements: juillet→stale, date récente→fresh, source missing/non parsable→unknown, parité JSON/rendu→même verdict.

3. Smoke build isolé, sans écrire dans `public/`:

```text
QG_USE_TEST_FIXTURES=1 QG_BUILD_OUTPUT_DIR=/tmp/omar-qg-issue82-build-20260911 python3 scripts/build.py
built qg 26 routes · 6/7 healthy · 155 issues · 8 PRs · ledger 2026-09-11 · 2026-09-11T04:22:43Z
```

4. Suite de régression isolée des modules qui reconstruisent `public/`:

```text
PYTHONPATH=. uv run --with pytest --with pyyaml pytest -q --ignore=tests/test_qg_static.py --ignore=tests/test_delivery_outcomes.py
94 passed in 34.47s
```

Le lancement `uv run --with pytest pytest -q` brut ne collecte pas `scripts` (PYTHONPATH absent). Le lancement avec PYTHONPATH a ensuite signalé PyYAML absent dans l'environnement uv; l'ajout `--with pyyaml` éphémère a rétabli la suite. Ces deux écarts sont préexistants/hors scope #82.

5. Syntaxe et whitespace:

```text
python3 -m py_compile scripts/build.py
git diff --check
exit 0
```

## Preuves de projection/rendu

- JSON exact: `artifacts/issue-82/chantiers.v2.json`
  - `schema: oa.chantiers/v2`
  - `source.checked_at: 2026-07-04T12:00:00Z`
  - `freshness: stale`
  - items avec `historical: true`, `remaining_gap`, `owner`, `next_proof`.
- Compatibilité: `artifacts/issue-82/chantiers.legacy.json`.
- HTML exact: `artifacts/issue-82/chantiers.html`
  - `data-chantiers-freshness="stale"`
  - « Historique — source vérifiée le 2026-07-04T12:00:00Z »
  - avertissement explicite qu'un rebuild ne revalide pas le constat.

## Pour H-Athena

Vérifier l'artefact à ce commit candidat, notamment: absence de dérivation depuis `built_at`, exactitude de la compatibilité v2/legacy et absence de lecture de projection antérieure si la source échoue. Ce document ne formule aucun verdict de review.
