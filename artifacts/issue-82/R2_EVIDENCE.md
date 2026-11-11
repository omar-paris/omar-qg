# R2 verification evidence

- Review input hash verified: `331eb0437ede7b49abf94f442baa0e770687a9456d57279119f290130f3dab4a`.
- Baseline: `34c58a5976da70ec524d93b6b4e97b2fdd884646`.

## TDD

```text
Before R2 production changes:
4 failed, 2 passed

After R2 production changes:
6 passed
```

The failing tests covered legacy URI compatibility, missing/invalid/future timestamps failing closed, the versioned render link, and the anonymous fixture requirement.

## Final checks

```text
uv run --with pytest --with pyyaml python -m pytest tests/test_chantiers_truth.py -q
6 passed

uv run --with pytest --with pyyaml python -m pytest tests/ -q
130 passed

python3 -m py_compile scripts/build.py
git diff --check
```

## Isolated build

```text
QG_USE_TEST_FIXTURES=1 QG_BUILD_OUTPUT_DIR=<isolated-output> python3 scripts/build.py
built qg 26 routes
```

The captured legacy list, v2 contract, and HTML are the redacted files adjacent to this evidence.
