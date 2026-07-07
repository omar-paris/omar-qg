#!/usr/bin/env bash
# oa-observe-morning.sh — lance l'observateur puis envoie à Alex un message conversationnel Telegram.
# « Salut Alex, j'ai remarqué ça et ça, voici ce que je propose. » (demande 12/06)
# Cron : 0 6 * * * — voir README-oa-observe.md
set -uo pipefail
QG=/home/omar/23-Offre/actifs/omar-qg
OBS_DIR=/home/omar/11-Pilotage/journal/observateur
HERMES=/home/omar/.local/bin/hermes
TARGET="telegram:Alexandre"
DAY=$(date +%Y-%m-%d)

cd "$QG" || exit 1
# Canal primaire : cartes Hermes Kanban idempotentes. Telegram reste un résumé secondaire.
/usr/bin/python3 scripts/oa-observe.py --kanban >> "$OBS_DIR/cron.log" 2>&1
BRIEF="$OBS_DIR/$DAY.md"
[ -f "$BRIEF" ] || exit 0

# Compose le message à partir du briefing (P0/P1 + section observations)
MSG=$(/usr/bin/python3 - "$BRIEF" <<'PY'
import sys, re
b = open(sys.argv[1], encoding="utf-8").read()
# compte par sévérité depuis la ligne "Bilan"
m = re.search(r"Bilan\s*:\s*(\d+)\s*P0.*?(\d+)\s*P1.*?(\d+)\s*P2", b)
p0, p1, p2 = (m.groups() if m else ("?", "?", "?"))
# titres P0 et P1 (lignes "### [P0]..." / "### [P1]...")
titres = re.findall(r"^###\s*\[(P0|P1)\]\s*(.+?)\s*·", b, re.M)
# section observations & questions
obs = ""
mo = re.search(r"##\s*💬\s*Observations.*?\n(.*)", b, re.S)
if mo:
    obs = mo.group(1).strip()
lines = ["Salut Alex 👋 — briefing flotte du jour."]
if p0 != "0":
    lines.append(f"\n🔴 {p0} point(s) critiques à voir :")
    lines += [f"• {t}" for s, t in titres if s == "P0"]
else:
    lines.append("\n✅ Aucun point critique aujourd'hui.")
p1_titres = [t for s, t in titres if s == "P1"]
if p1_titres:
    lines.append(f"\n🟠 {p1} à surveiller : " + " · ".join(p1_titres[:5]))
if obs:
    lines.append("\n💬 " + obs[:600])
lines.append(f"\nDétail : {sys.argv[1]}")
print("\n".join(lines))
PY
)
printf '%s' "$MSG" | "$HERMES" send -t "$TARGET" >> "$OBS_DIR/cron.log" 2>&1
echo "[$(date -Iseconds)] briefing envoyé à $TARGET" >> "$OBS_DIR/cron.log"
