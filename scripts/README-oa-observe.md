# oa-observe — observateur proactif de la flotte OA

> Le système qui aurait attrapé l'incident du 11/06 : un worker Hermes a créé
> ~142 000 sessions parasites sur le VPS-JAB pendant 3 semaines (base passée à
> 3 Go) sans que personne ne le voie. **Objectif : Alex n'a plus à lancer les
> inputs — le système remonte les anomalies et des observations tout seul.**

## Ce que ça fait

Scanne la flotte (VPS-Omar + VPS-JAB, extensible) en **100 % lecture seule**,
exécute une dizaine de détecteurs, et écrit un **briefing lisible** (pas un dump)
dans `~/11-Pilotage/journal/observateur/YYYY-MM-DD.md` :

- une section **🔴 À regarder** triée par sévérité (P0 → P1 → P2), chaque finding
  en langage humain + remédiation + VPS ;
- une section **💬 Observations & questions pour Alex** qui ouvre une vraie
  conversation (« omar-qg a N fichiers non commités — à sauver ou générés ? »).

Un résumé court est aussi imprimé sur stdout (compteurs + titres P0).

## Détecteurs

| Détecteur | Ce qu'il attrape | Sévérité |
|---|---|---|
| `file_bloat` | fichier de données > 500 Mo (data, pas node_modules) | P1, P0 si > 2 Go |
| `session_explosion` | sessions Hermes par profil + taux/heure | P1 > 1 000, P0 > 10 000 |
| `kanban_loop` | tâche kanban `running` depuis > 6 h | P1 |
| `ram_swap` | RAM available < 400 Mo / swap > 80 % | P0 / P1 |
| `backup_stale` | dernier `status=OK` > 36 h, ou aucun | P1 / P0 |
| `failed_units` | `systemctl --failed` (system + user) | P1 |
| `orphan_procs` | zombies + claude/native-binary orphelins | P2, P1 si > 5 |
| `secret_exposure` | secrets world-readable + `vault.json` servi | P0 |
| `repo_idle` | app sans commit > 5 j & 0 issue ; dirty > 24 h ; commits non poussés | P2 / P1 |
| `cert_expiry` | cert Caddy expirant < 14 j (best-effort) | P1 / P0 |

`session_explosion` est le détecteur cœur : c'est lui qui aurait sonné le 11/06.
En local il lit les `state.db` via le module **python `sqlite3` en mode read-only**
(le binaire `sqlite3` n'est pas installé sur VPS-Omar) ; en SSH il utilise le
binaire `sqlite3 -readonly`.

## Usage

```bash
cd /home/omar/23-Offre/actifs/omar-qg
python3 scripts/oa-observe.py                 # scan complet + briefing + résumé
python3 scripts/oa-observe.py --stdout-only    # pas d'écriture fichier
python3 scripts/oa-observe.py --only file_bloat,ram_swap
python3 scripts/oa-observe.py --json           # dump JSON (debug)
```

Idempotent et ré-exécutable : le briefing du jour est ré-écrit à chaque passage.
Si rien de grave (0 P0/P1) le briefing le dit clairement et donne quand même 2-3
observations.

## Ajouter un VPS

Une seule ligne dans `TARGETS` en tête de `oa-observe.py` :

```python
{"name": "VPS-Pantheos", "mode": "ssh", "host": "pantheos",
 "homes": ["/home/aurel"], "backup_logs": ["/var/log/oa-backup-daily.log"]},
```

- `mode` : `local` (commandes directes) ou `ssh` (préfixe `ssh <host> '...'`).
- `host` : alias SSH (lecture seule, root OK). Doit être joignable en `BatchMode`.
- Un VPS muet (timeout) devient lui-même un finding P1 « injoignable », il ne
  bloque pas le scan (timeouts partout).

## Cron quotidien (PRÉPARÉ, NON ACTIVÉ — à brancher par Alex)

Le scan est conçu pour tourner chaque matin à 06h00. **Rien n'est activé** : à
toi de décider. Deux options de branchement (non mutuellement exclusives) :

### Option A — crontab système simple (le plus direct)

```cron
# /etc/cron.d/oa-observe  (ou `crontab -e` côté omar)
0 6 * * * omar cd /home/omar/23-Offre/actifs/omar-qg && \
  /usr/bin/python3 scripts/oa-observe.py >> /home/omar/11-Pilotage/journal/observateur/cron.log 2>&1
```

### Option B — poster le résumé dans les canaux existants

Le tool n'écrit volontairement que le briefing. Pour pousser le résumé, brancher
sur les mécanismes déjà en place dans omar-qg :

1. **Telegram** (comme `alerts.py`) — réutiliser
   `~/omar-alex-vps/scripts/send-telegram.sh` :
   ```bash
   SUMMARY=$(python3 scripts/oa-observe.py | tail -n +1)
   ~/omar-alex-vps/scripts/send-telegram.sh "🔭 Observateur flotte :\n$SUMMARY"
   ```

2. **Boîte de décisions** (`scripts/oa_ask.py`, qg#27) — pour transformer un P0
   récurrent en question tranchable par Alex :
   ```bash
   python3 scripts/oa_ask.py --group observateur \
     --open "google_token.json world-readable depuis le scan du matin — chmod 600 ?" \
     --context "Détecté par oa-observe (secret_exposure)" --par oa-observe
   ```

3. **Digest h-omar** — le digest quotidien de h-omar peut simplement `cat` le
   briefing du jour (`~/11-Pilotage/journal/observateur/$(date +%F).md`) et
   l'inclure dans son bilan Agora.

**Recommandation** : activer d'abord l'option A (le briefing fichier suffit à
sortir du « Alex remarque à la main »), puis brancher l'option B-1 (Telegram du
résumé P0/P1) une fois la qualité des findings calibrée sur quelques jours.

## Garanties

- **Lecture seule** sur les VPS observés. Seule écriture : le briefing, sur
  VPS-Omar. Toutes les requêtes SQLite sont en `mode=ro` / `-readonly`.
- **stdlib uniquement** (pas de pip). Timeouts sur chaque commande et chaque SSH.
- Défensif : un détecteur qui échoue est noté dans « ⚙️ Notes de scan » et
  n'interrompt pas les autres.
