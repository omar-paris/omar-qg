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
python3 scripts/oa-observe.py --json           # dump JSON structuré (debug/API)
python3 scripts/oa-observe.py --kanban-dry-run # plan create/update/resolve sans mutation
python3 scripts/oa-observe.py --kanban         # sink primaire : cartes Kanban idempotentes
```

Idempotent et ré-exécutable : le briefing du jour est ré-écrit à chaque passage.
Si rien de grave (0 P0/P1) le briefing le dit clairement et donne quand même 2-3
observations.

## Sink Kanban primaire

Agora est archivé comme ancien canal d'exécution : `oa-observe` transforme
désormais les findings persistants en cartes Hermes Kanban, avec une clé stable :

```txt
oa-observe:<target>:<detector>:<fingerprint>
```

- `--json` expose des findings structurés (`schema: oa.observe.finding/1`) avec
  `fingerprint` et `idempotency_key` ;
- `--kanban-dry-run` affiche les opérations prévues (`create`, `update`,
  `resolve`) sans créer de carte ni écrire l'état local ;
- `--kanban` appelle `hermes kanban create --idempotency-key ... --json` pour
  créer ou retrouver la carte existante sans doublon ;
- l'état local `var/oa-observe-kanban-state.json` permet de reconnaître les
  alertes déjà vues et de clôturer une carte quand le finding disparaît ;
- à la résolution, le protocole est : commentaire `oa-observe` sur la carte puis
  `hermes kanban complete` avec un résumé de clôture automatique.

Smoke builder :

```bash
cd /home/omar/23-Offre/actifs/omar-qg
python3 -m pytest tests/test_oa_observe_kanban.py -q
bash scripts/smoke-oa-observe-kanban.sh
```

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

### Option B — poster le résumé dans les canaux existants (secondaire)

Le tool écrit le briefing et peut créer/mettre à jour les cartes Kanban. Pour
pousser aussi un résumé conversationnel, brancher sur les mécanismes existants :

1. **Telegram** (comme `alerts.py`) — réutiliser
   `~/omar-alex-vps/scripts/send-telegram.sh` :
   ```bash
   SUMMARY=$(python3 scripts/oa-observe.py | tail -n +1)
   ~/omar-alex-vps/scripts/send-telegram.sh "🔭 Observateur flotte :\n$SUMMARY"
   ```

2. **Ancien flux Agora / boîte de décisions** — à archiver/désactiver sans
   suppression dangereuse. Ne plus l'utiliser comme canal primaire pour les
   alertes persistantes `oa-observe` ; Kanban est la source d'action.

3. **Digest h-omar** — le digest quotidien de h-omar peut simplement `cat` le
   briefing du jour (`~/11-Pilotage/journal/observateur/$(date +%F).md`) et
   l'inclure comme contexte, sans remplacer les cartes Kanban.

**Recommandation** : activer le scan quotidien via `scripts/oa-observe-morning.sh`
qui appelle `oa-observe.py --kanban`, puis garder Telegram comme notification
secondaire une fois la qualité des findings calibrée sur quelques jours.

## Garanties

- **Lecture seule** sur les VPS observés. Seule écriture : le briefing, sur
  VPS-Omar. Toutes les requêtes SQLite sont en `mode=ro` / `-readonly`.
- **stdlib uniquement** (pas de pip). Timeouts sur chaque commande et chaque SSH.
- Défensif : un détecteur qui échoue est noté dans « ⚙️ Notes de scan » et
  n'interrompt pas les autres.
