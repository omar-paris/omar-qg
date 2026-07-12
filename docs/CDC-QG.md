# CDC du QG V1 — cockpit inter-VPS + filet de sécurité de la flotte

Fable, 12/07 (réécrit post-round 5). **Pourquoi le QG existe → `omar-hub/docs/MANIFESTE.md` :** c'est
**le filet de sécurité** — *« quelqu'un veille quand l'artisan n'est pas devant l'écran »*. Dépendance
**DURE** de la 1ʳᵉ prod. Contrats : `omar-top/contracts/` (`oa.vps-report/v1`, `oa.qg-ack/v1`).

## 0. La correction du round 3/5 : DEUX choses, pas une

Le QG n'est pas « un cockpit qu'on étend un peu ». C'est **deux composants de natures différentes**, qui
**ne partagent pas la même base** :

| | **(A) La console** (organique) | **(B) Le safety-core** (neuf, isolé) |
|---|---|---|
| Rôle | « voir tous mes clients » — le produit d'Alex | juger si la flotte va bien, déclencher l'incident |
| Base | `omar-qg` existant (mature, 89 commits) | **base propre, jamais lue par le front** |
| Nature | riche, évolutif, requêtes lourdes OK | minimal, déterministe, chemin critique |
| On fait | **on ÉTEND** | **on CONSTRUIT** |

**Pourquoi les séparer (le cas concret round 3)** : un dev suit l'ancien CDC → ingère les heartbeats dans
la base de la console → le front lance une requête lourde sur cette même base → l'ingestion prend du
retard → 20 VPS deviennent « silencieux » → **20 incidents fictifs**. Le couplage console↔ingestion est
exactement ce que le safety-core isolé élimine. **Règle : le front ne lit jamais la base du safety-core ;
le safety-core ne dépend jamais de la charge de la console.**

## 1. La console (A) — ce que `omar-qg` fait DÉJÀ (à conserver)

`omar-qg` = 89 commits · `build.py` 4900 l. · **RBAC + vues client** (`build_client_view`, `actor_can_see`) ·
`health_probe` · `alerts.py` · `agent_loop_audit` · supervision flotte (`oa-fleet-supervision-v0`) · front
`qg.omar.paris` · `QG_CONTRACT.md`. Agrège la flotte (conformité graduée par VPS, carte, chantiers,
blocages, décisions, feedback Alex). **On l'étend, on ne le jette pas.**

## 2. Le safety-core (B) — les services (nouveaux, identifiables)

Chacun = un processus nommé, avec compte Unix/conteneur, base possédée, readiness, SLO, restart policy,
migration, backup, permissions. **Aucune lecture directe de table par le front.**

| Service | Rôle | Base propre |
|---|---|---|
| `qg-ingest` | reçoit les flux montants (push mTLS), persiste durablement, émet l'ACK | ingest store |
| `qg-safety-core` | évalue l'état de chaque VPS (heartbeat + travail-attendu + verdicts) → décide l'incident | safety store |
| `qg-alert-router` | route l'alerte multi-canal, teste la livraison, applique le flap-damping | — |
| `qg-console` | la console existante (A) — lecture seule sur des vues projetées, jamais sur le safety store | omar-qg |
| `qg-evidence-store` | rétention long terme (logs/traces/séries, classe B) — **séparé du chemin critique** | evidence store |
| `external-witness` | hors domaine de panne — garde le gardien (§6) | ailleurs |

### 2.1 La machine d'incident (déterministe)
États : `sain → suspect → incident → résolu`. Transitions sur **signaux multiples corrélés** (pas un seul
raté). **Flap-damping** : N cycles avant de déclarer/lever (pas d'incident qui clignote). **Corrélation de
causes communes** : une perte Tailnet / une migration de version qui touche 20 VPS = **1 incident
corrélé**, pas 20. **Test de livraison d'alerte** : le canal d'alerte est vérifié périodiquement (une
alerte non livrée ne protège personne). **Escalade** : opérateur → 2ᵉ répondant (lien G3 continuité humaine).

### 2.2 Shadow mode (obligatoire avant de faire foi)
Toute nouvelle version de l'évaluateur tourne **en parallèle de l'ancienne** (shadow) et on compare les
verdicts **avant** de la laisser déclencher des incidents réels. Pas de bascule à l'aveugle.

## 3. Le dead-man's-switch + le travail-attendu (le cœur du filet)

Un Hub **ne peut jamais se déclarer vert seul** (D10). Le safety-core juge de l'extérieur :

- **Heartbeat** : chaque VPS pousse un ping toutes N min. **Silence = ROUGE immédiat**, prévalant sur
  toute donnée locale (le silence n'est jamais neutre). `LAW-QG-HEARTBEAT`.
- **Sondes outside-in** : le QG teste les endpoints publics du VPS **comme un client le ferait**
  (DNS/TLS/auth/`/ready`), indépendamment du Hub local.
- **Signaux de travail-attendu** (heartbeat + `/ready` ne prouvent PAS que le travail est fait) : dernier
  backup, **dernier test de restauration**, dernier cycle agent utile, âge de l'outbox, token métier
  valide, dernier test d'un canal, fraîcheur de la conformité. Un VPS « up » qui n'a pas de backup
  restaurable depuis 6 j n'est **pas** vert. `LAW-QG-EXPECTED-WORK`.

## 4. Le flux montant (push-only, contrat `oa.vps-report/v1`)

**Sens unique : le VPS initie une connexion sortante mTLS vers `qg-ingest`.** Le **QG ne se connecte
jamais au VPS** et ne détient **aucun credential d'administration VPS**. *(Cas de sécurité : un compte QG
compromis + un pull QG→VPS = pivot vers toute la flotte ; en push sortant seul, au pire on perturbe/lit
les flux autorisés, aucun chemin d'entrée vers la flotte.)*

- Champs : `deployment_id` (dérivé du **certificat mTLS**, jamais du payload) · `stream_id` ·
  **`producer_epoch`** (détecte les resets) · **`sequence`** (monotone par stream) · `payload_hash` ·
  `data_classification` · `retention_class` · `key_id` · `signature`.
- **ACK après persistance durable** (`oa.qg-ack/v1`) : `accepted_through` · **`gaps[]`** (→ backfill) ·
  `duplicates[]` · `quarantined[]` · `retry_after`. Le VPS sait exactement ce qui a été reçu et rejoue les trous.
- Anti-rejeu · quotas/backpressure · classes de priorité (`critical/normal/bulk`).

## 5. Périmètre de données — liste blanche stricte (la leçon JAB)

Ce qui **REMONTE** (et rien d'autre) : `heartbeat` · **verdicts OmarTop versionnés** · `expected-work` ·
**empreintes d'erreur** (par code/hash) · **coût d'exploitation OA** (flux OA interne distinct).

Ce qui **NE REMONTE JAMAIS** : daybook complet (→ le QG reçoit un **résumé machine**
`{completed_runs, failed_runs, blocked_runs, last_success_at, quality_regressions}`) · `stderr` brut ·
prompts/réponses LLM · **noms de dossiers** · CA/trésorerie/factures/contacts · note client moyenne (pas
au MVP). **Redaction/classification par allowlist AU SHIP** (pas « tout le JSON puis on caviarde »).

> *Cas JAB (avocat)* : un daybook « dossier Durand c. Société X terminé » ne remonte aucun CA — mais le
> **secret professionnel a quitté le VPS**. D'où le résumé machine, jamais la narration.

## 6. Le témoin externe — hors domaine de panne (« qui garde le gardien »)

`external-witness` **ne partage aucun** : provider, compte cloud, Tailnet, IdP, DNS, CI/CD, canal
d'alerte avec le QG. Il teste une **canary sémantique** (pas seulement `/health`) : « le QG a-t-il ingéré
et jugé le dernier heartbeat de tel VPS ? ». **Il porte aussi l'exécution des lois du QG** (`LAW-QG-DR`,
`LAW-QG-CONTRACT`, outside-in du QG lui-même) — sinon un QG mort **déclarerait son propre PRA vert par
silence**. Le safety-core ne s'auto-observe pas ; le témoin le fait, de l'extérieur.

## 7. Ce qu'on AJOUTE à `omar-qg` (le gap précis)

| Brique | État | À faire |
|---|---|---|
| Console + agrégation flotte | ✅ existe | brancher le **résumé machine** du daybook + errors + heartbeat en flux typé |
| `health_probe` | ✅ existe | généraliser en **sondes outside-in** planifiées + signaux travail-attendu |
| `qg-ingest` (push mTLS + ACK gaps) | ⬜ | **neuf** — persistance durable, backfill par séquence |
| `qg-safety-core` + machine d'incident | ⬜ | **neuf, base propre** — flap-damping, corrélation, shadow mode |
| dead-man's-switch | ⬜ | silence = rouge (`LAW-QG-HEARTBEAT`) |
| `external-witness` | ⬜ | **neuf, hors domaine de panne** — canary sémantique + lois du QG |
| redaction au ship (allowlist) | côté Hub | figer la liste blanche §5 |
| evidence store long terme (classe B) | partiel | séparer du chemin critique |

## 8. Périmètre MVP (ce qu'on NE fait PAS)

- **Pas d'active-active / consensus Raft-Paxos** pour 3 VPS (LeChat le voulait, ChatGPT le retire) : ça
  ajoute des modes de panne avant d'améliorer la disponibilité. MVP = safety-core minimal + **store
  durable** + **témoin externe** + **backup immuable** + **replay** + **clean-room restore**.
- **Pas de logs bruts par défaut** (empreintes d'erreur oui, `stderr` non).
- Isolation inter-tenant **par construction** (RBAC déjà là, renforcé) — un VPS ne voit jamais un autre.

## 9. Mesuré par OmarTop (lois)

`LAW-QG-HEARTBEAT` (silence = rouge) · `LAW-QG-EXPECTED-WORK` (backup/restore/cycle frais) ·
`LAW-QG-CONTRACT` (flux typé/signé conforme `oa.vps-report/v1`) · `LAW-QG-REDACT` (allowlist au ship) ·
`LAW-QG-DR` (PRA/replay du QG, exécutée **par le témoin externe**). Le QG-minimum-viable **vert** =
pré-requis de **Gate 4 / prod**.

## 10. Front du QG (design — round 5)

**Le plus faible en accessibilité/responsive → passe dédiée.** Rail **persistant**
(Flotte / Safety-core / Incidents / Observabilité), **⌘K global**, mode **« seulement ce qui cloche »**
par défaut (VPS verts repliés + résumé langage naturel en tête : « 1 silencieux, 1 disputed, reste
sain »), état **« VPS en provisioning »** (avant le 1er heartbeat), tables → **cartes empilées** sous
breakpoint. **Sémantique honnête inter-app** : au QG, **orange = incident actif** (distinct du Hub où
orange = périmé) — le libellé, jamais la seule couleur. Même librairie (`StatusTile`/`ActionCard`) que le Hub.

## 11. Démarche

1. **Étendre** la console `omar-qg` sur une branche dédiée (ne pas casser RBAC / vues client).
2. **Construire** le safety-core isolé (§2) + le témoin externe (§6) — base propre, shadow mode.
3. Livrer le **QG-minimum-viable** (heartbeat + outside-in + travail-attendu + ingest push + témoin) →
   **dépendance dure de la 1ʳᵉ prod** (avant qu'un Hub client parte).
4. Durcir le contrat montant (§4) + le périmètre (§5) avant d'agréger un 2ᵉ client réel.

> **GO Alex requis** (touche la prod client + l'agrégation inter-tenants). Rollout : le QG doit veiller
> `oa-master` (canary) avant `pantheos`, avant `jab` (en dernier).
