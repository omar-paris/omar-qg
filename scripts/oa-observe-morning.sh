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

# Compose un résumé borné. Le formatter interdit les verdicts globaux depuis ce scan partiel.
MSG=$(/usr/bin/python3 scripts/format_oa_observe_brief.py "$BRIEF")
printf '%s' "$MSG" | "$HERMES" send -t "$TARGET" >> "$OBS_DIR/cron.log" 2>&1
echo "[$(date -Iseconds)] briefing envoyé à $TARGET" >> "$OBS_DIR/cron.log"
