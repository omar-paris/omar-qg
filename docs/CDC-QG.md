# CDC du QG (cockpit inter-VPS) — ÉTENDRE l'existant `omar-qg`

Fable, 12/07. Répond à U1/U8 (QG-minimum-viable) et T8 (QG = son propre CDC). **Décision : ÉTENDRE**
`omar-qg` (mature), pas refaire. Le QG est le **cockpit de l'opérateur solo (Alex)** + le **filet de
sécurité de la flotte** (dead-man's-switch, outside-in) — dépendance **DURE** de la prod.

## 0. Décision : ÉTENDRE (fondée sur l'inspection)
`omar-qg` = 89 commits · `build.py` 4900 l. · **RBAC + vues client** · **health_probe** · `alerts.py` ·
`agent_loop_audit` · supervision flotte (`oa-fleet-supervision-v0`, conformité graduée injectée) · front
`qg.omar.paris` · `QG_CONTRACT.md`. Base solide → **on l'étend**, on ne le jette pas. Refaire = gaspillage.

## 1. Ce que le QG fait DÉJÀ (à conserver)
- **Agrège la flotte** : conformité graduée par VPS (ship-own `oa.vps-report/v1` redacted), `fleet-status.json`,
  carte, chantiers, blocages, décisions, boucles, feedback Alex.
- **Vues client filtrées par RBAC** (`build_client_view` + `actor_can_see`) — Tailnet-only.
- **Sondes de santé** (`health_probe`), **alertes** (`alerts.py`, cron 7,37/h), **observe-morning**.
- **API** (`qg_api.py`) + front multi-sections (agent-activity, boucles, builds, carte, clients…).

## 2. Rôle du QG en V4 (les 3 plans, côté flotte)
- **Evidence plane flotte** : reçoit les artefacts montants (ship-own) de chaque VPS — **uniquement
  conformité / daybook / errors / heartbeat** au MVP (**U7 : PAS de CA/trésorerie**).
- **Filet de sécurité (le neuf, bloquant)** : **dead-man's-switch** (un VPS silencieux = alerte, pas
  « vert par défaut ») + **sondes outside-in** (DNS/TLS/auth/`/ready`/âge outbox/dernier backup/version)
  depuis une **3e position**, car un Hub **ne peut jamais se déclarer vert seul** (D10).
- **Observabilité mutualisée (classe B)** : stockage long terme (logs/traces/séries-temps, Langfuse) —
  **au QG, pas par-VPS** (T6). Les VPS n'ont qu'un collecteur léger.
- **Cockpit opérateur** : « voir tous mes clients » — le vrai produit d'Alex.

## 3. QG-MINIMUM-VIABLE (dépendance DURE, bloquante pour la 1re prod)
Trois briques à AJOUTER avant qu'un Hub client parte en prod :
1. **Heartbeat / dead-man's-switch** : chaque VPS ping le QG toutes N min ; **absence = alerte** (loi
   `LAW-HUB-OUTSIDE-IN`). Le silence ne ressemble plus à la santé.
2. **Sondes outside-in** : le QG teste chaque endpoint public du VPS de l'extérieur (indépendant du Hub local).
3. **Log store mutualisé** : réception + rétention des logs/errors shippés (le « pilier logs » — Loki/
   VictoriaLogs, classe B).

## 4. Contrat montant (typé, signé, minimisé — D12)
Chaque flux VPS→QG porte : `stream_type / schema_version / deployment_id / tenant_id / sequence /
payload_hash / data_classification / retention_class / signature`. Transport **mTLS** (ou credential
court) · **anti-rejeu** · **accusé** · **reprise par séquence** · **backpressure/quotas**.
**Redaction/classification par allowlist AU SHIP** (pas « tout le JSON puis redaction ») — un `stderr`
JAB peut contenir un nom de dossier client (D11). Étend le `QG_CONTRACT.md` existant.

## 5. Ce qu'on AJOUTE à `omar-qg` (le gap extend)
| Brique | État omar-qg | À ajouter |
|---|---|---|
| Agrégation conformité flotte | ✅ existe | brancher daybook/errors/heartbeat en flux typé |
| health_probe | ✅ existe | généraliser en **sondes outside-in** systématiques + planifiées |
| dead-man's-switch | ⬜ | heartbeat reçu par VPS + alerte sur silence (`LAW-HUB-OUTSIDE-IN`) |
| log store mutualisé | ⬜ | réception logs shippés + rétention (classe B) |
| contrat montant signé | partiel (`oa.vps-report/v1`) | typer/signer/minimiser (mTLS, séquence, anti-rejeu) |
| redaction au ship | côté Hub | **allowlist au ship** avant egress |
| observabilité long terme | partiel | Langfuse/TSDB/logs mutualisés (classe B) |

## 6. Sécurité du QG (nouvelle concentration inter-clients)
Le QG voit **plusieurs clients** → surface sensible :
- **Observé depuis une 3e position** (le QG a aussi son propre outside-in : « qui garde le gardien »).
- **PRA / réplication** du QG (D13) — s'il tombe, le filet tombe.
- **Données minimisées** (U7) : conformité/ops seulement au MVP ; le CA/trésorerie reste local par VPS.
- RBAC strict (déjà là) : isolation inter-tenant renforcée (leçon fuite JAB).

## 7. Mesuré par OmarTop
Lois : `LAW-HUB-OUTSIDE-IN` (heartbeat+sondes), `LAW-QG-CONTRACT` (flux typé/signé), `LAW-QG-REDACT`
(allowlist au ship), `LAW-QG-DR` (PRA/réplication). Le QG-minimum-viable **vert** = pré-requis de Gate 4/prod.

## 8. Démarche
1. **Étendre** `omar-qg` (branche dédiée) — ne pas casser l'existant (RBAC, vues client).
2. Livrer le **QG-minimum-viable** (§3) → dépendance dure de la 1re prod.
3. Durcir le contrat montant (§4) + la sécurité (§6) avant d'agréger un 2e client réel.
> GO Alex requis (touche la prod client + l'agrégation inter-tenants).
