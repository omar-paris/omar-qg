#!/usr/bin/env bash
# Smoke local du sink Kanban oa-observe : aucune mutation Kanban réelle.
set -euo pipefail
ROOT=${ROOT:-/home/omar/23-Offre/actifs/omar-qg}
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
FIXTURE="$TMP/findings.json"
STATE="$TMP/state.json"

cat > "$FIXTURE" <<'JSON'
{
  "findings": [
    {
      "severite": "P1",
      "titre": "Kanban : 2 tâche(s) running > 6h",
      "detail": "Deux workers semblent bloqués depuis plus de 6h.",
      "vps": "VPS-Omar",
      "remediation": "Lister les cartes et débloquer les workers.",
      "detecteur": "kanban_loop"
    }
  ]
}
JSON

cd "$ROOT"
python3 scripts/oa-observe.py --fixture "$FIXTURE" --json > "$TMP/scan.json"
python3 scripts/oa-observe.py --fixture "$FIXTURE" --kanban-dry-run --kanban-state "$STATE" > "$TMP/dry-create.json"
python3 - "$TMP/scan.json" "$TMP/dry-create.json" "$STATE" <<'PY'
import json
import sys
from pathlib import Path
scan = json.loads(Path(sys.argv[1]).read_text())
dry = json.loads(Path(sys.argv[2]).read_text())
key = scan["findings"][0]["idempotency_key"]
assert scan["schema"] == "oa.observe.scan/1"
assert key.startswith("oa-observe:VPS-Omar:kanban_loop:")
assert dry["operations"][0]["action"] == "create"
assert dry["operations"][0]["idempotency_key"] == key
# Prépare un état local actif pour prouver qu'un deuxième passage devient update
# sans dépendre d'une vraie DB Kanban.
Path(sys.argv[3]).write_text(json.dumps({key: {
    "status": "active",
    "task_id": "t_smoke",
    "title": "Kanban : 2 tâche(s) running > 6h",
    "first_seen_at": 1,
    "last_seen_at": 1
}}, indent=2), encoding="utf-8")
PY
python3 scripts/oa-observe.py --fixture "$FIXTURE" --kanban-dry-run --kanban-state "$STATE" > "$TMP/dry-update.json"
python3 scripts/oa-observe.py --fixture <(printf '{"findings": []}') --kanban-dry-run --kanban-state "$STATE" > "$TMP/dry-resolve.json"
python3 - "$TMP/dry-update.json" "$TMP/dry-resolve.json" <<'PY'
import json
import sys
from pathlib import Path
update = json.loads(Path(sys.argv[1]).read_text())
resolve = json.loads(Path(sys.argv[2]).read_text())
assert update["operations"][0]["action"] == "update"
assert update["operations"][0]["task_id"] == "t_smoke"
assert resolve["operations"][0]["action"] == "resolve"
assert resolve["operations"][0]["task_id"] == "t_smoke"
print("SMOKE_OK oa-observe kanban dry-run create/update/resolve")
PY
