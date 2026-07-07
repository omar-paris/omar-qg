# QG — Système OA comme cockpit vivant

Date: 2026-07-07
Auteur: H-Omar/default
Statut: cadrage CTO, non implémenté

## 0. Correction de trajectoire

Le QG ne doit pas devenir une grande page de textes statiques ni une collection de patches utiles mais locaux.
Il doit devenir le reflet synchronisé, exploitable et hiérarchisé du système OA et des clients.

Constat terrain du 2026-07-07:
- le repo QG contient déjà des collecteurs et API (`public/api/*.json`);
- certaines surfaces sont dynamiques (`repo-health`, `carte`, `fleet`, `ops`, `triage`);
- mais il reste du bruit, des doublons de pages, des seeds statiques et des textes non dynamiques;
- `public/api/boucles.json` dit explicitement que `agent_loop_registry` repose encore sur un seed statique du 30/06;
- le QG a donc des briques de cockpit, mais pas encore une vraie boucle système fiable.

## 1. Définition: système OA

Le système OA n'est pas une app unique. C'est une boucle opératoire distribuée:

```txt
OmarTop = loi / standards / versions / checks / seuils minimum
Hub local = état opérationnel local d'un VPS ou PC
QG = tour de contrôle globale, client + système, sur données redacted
Kanban/GitHub = exécution, dette, PR, gates
Athena = revue froide / judiciaire
H-Omar = arbitrage CTO / cohérence / priorités business
Agents locaux = opérateurs de nœud, producteurs de rapports locaux
```

## 2. Définition: VPS managé par OA

Un VPS est "managé par OA" s'il remplit au moins ce contrat versionné:

### oa.managed-vps/v1

Un VPS managé expose ou produit régulièrement:

1. `identity`
   - vps_id stable;
   - owner agent/runtime;
   - tenant/scope (`oa-internal`, `family`, `client:<id>`);
   - exposition (`public`, `tailnet`, `internal`).

2. `runtime`
   - services critiques connus;
   - health local;
   - Caddy/proxy status si concerné;
   - storage/memory/swap minimum.

3. `agent_plane`
   - agent local attendu;
   - statut reachable/running/degraded/unknown;
   - dernier rapport émis;
   - capacité de recevoir recommandations.

4. `security_plane`
   - secrets par refs uniquement;
   - pas de secrets en clair dans rapports;
   - sudo/politiques connues;
   - endpoints sensibles non publics.

5. `data_plane`
   - sources documentaires déclarées;
   - exclusions sensibles;
   - Cloud Map/registry si disponible;
   - scopes agents.

6. `ops_plane`
   - backups;
   - monitoring/alerting;
   - logs utiles;
   - runbooks ou actions de remédiation.

7. `standards_alignment`
   - version OmarTop ciblée;
   - contrôles pass/fail/unknown;
   - écarts classés `missing_measure`, `non_compliant`, `not_applicable`, `business_choice`.

8. `client_readiness`
   - prêt onboarding oui/non/partiel;
   - prochaine action;
   - décision humaine requise si besoin.

## 3. Flux canonique vivant

```txt
Chaque VPS / PC / client
  -> produit `oa.vps-report/v1` ou `oa.hub-status/v1`
  -> H-Omar receiver valide schema + redaction + fraîcheur
  -> QG agrège seulement les données safe
  -> QG calcule écart vs OmarTop
  -> Kanban/GitHub reçoit les actions réelles
  -> Athena gate les claims critiques
  -> OmarTop évolue quand une règle devient standard durable
```

## 4. Ce qui est utile vs bruit

### Utile dans QG

- fraîcheur des rapports;
- statut par VPS/client;
- écart vs standard OmarTop versionné;
- action suivante ownerisée;
- gate bloquante;
- source de preuve safe;
- décisions Alex uniquement quand nécessaires.

### Bruit dans QG

- longs textes doctrinaux non liés à un état;
- doublons Hub/OmarTop/Catalogue;
- seeds statiques présentés comme vivants;
- compteurs sans action;
- apps listées sans version/health/source;
- alertes stables sans changement;
- TODO non ownerisés.

## 5. Strates QG proposées

Le QG doit cesser d'être organisé par pages historiques et devenir un cockpit par strates:

1. `Système OA`
   - cœur OA: QG, Hub, OmarTop, AppOmar, Catalogue, Landing, Lab;
   - agents et boucles;
   - GitHub/Kanban/Athena.

2. `Fleet / VPS`
   - OA-master;
   - Pantheos/H-Aurel;
   - JAB/Edilia/CC-JAB;
   - futurs VPS clients.

3. `Clients`
   - prospect/audit;
   - devis;
   - onboarding;
   - provisioning;
   - exploitation/SAV;
   - maturité.

4. `Standards`
   - version OmarTop ciblée;
   - minimum requis;
   - écarts;
   - PR/issues standards.

5. `Data & Cloud Map`
   - sources;
   - exclusions;
   - scopes agents;
   - review needed;
   - readiness extraction/vectorisation.

6. `Actions`
   - prochains 10 gestes utiles;
   - bloquants;
   - owners;
   - gates;
   - décisions Alex.

## 6. Versioning des standards

OmarTop doit versionner les contrats:

- `oa.managed-vps/v1` — qu'est-ce qu'un VPS managé;
- `oa.vps-report/v1` — rapport redacted inter-VPS;
- `oa.hub-status/v1` — état Hub local consommable QG;
- `oa.resource-scope/v1` — données/sources/scopes agents;
- `oa.cloudmap/v1` — capacité Cloud Map conforme;
- `oa.client-onboarding/v1` — étapes minimales client.

Le QG affiche pour chaque nœud:

```txt
cible: oa.managed-vps/v1 + oa.vps-report/v1
etat: conforme | partiel | inconnu | non applicable | fail
version_omartop: <sha/version>
next_action: <owner + lien>
```

## 7. Cloud Map dans cette vision

Cloud Map ne doit pas être logique interne OmarTop ni QG.

- Cloud Map Engine indexe/classifie localement.
- OmarTop définit `oa.cloudmap/v1`.
- Hub permet l'onboarding et la review locale.
- QG affiche uniquement l'état safe: actif, sources, volumes, review_needed, exclusions, scopes, blocages.

## 8. Refonte QG à mener

### Phase A — Audit anti-illusion

Objectif: dire ce qui est vivant, ce qui est seed, ce qui est texte mort.

Livrable:
- `qg_truth_audit.json`;
- page `/ops/truth/` ou bloc dans `/ops/`;
- chaque widget porte `source_type`: `live`, `generated`, `seed`, `manual`, `unknown`.

### Phase B — Contrat managed VPS

Objectif: créer la matrice VPS managés par OA.

Livrable:
- `schemas/managed-vps.schema.json`;
- collecteur `collect_managed_vps.py`;
- API `/api/managed-vps.json`;
- page QG Fleet lisible.

### Phase C — Écarts vs OmarTop

Objectif: QG calcule le gap, pas seulement affiche des statuts.

Livrable:
- ingestion minimum OmarTop standards/version;
- mapping contrôles -> strates QG;
- cellules `pass/fail/unknown/not_applicable`;
- next action auto proposée quand `unknown/fail`.

### Phase D — Clients et onboarding

Objectif: un client OA suit un lifecycle unique.

Livrable:
- `client_lifecycle`: audit -> devis -> onboarding -> provisioning -> hub -> maturité -> SAV;
- statut par client/prospect;
- séparation vue interne / vue client-safe.

## 9. QG comme tour de contrôle décisionnelle

Correction majeure ajoutée après retour Alex: le QG ne doit pas seulement observer. Il doit devenir la bannière commune où les agents prennent leur cap, rendent compte, et où Alex/H-Omar/Athena arbitrent.

Le système cible n'est donc pas:

```txt
Agents -> conversations éparses -> parfois Kanban -> parfois QG
```

Mais:

```txt
Alex formule intention du jour dans QG
  -> QG transforme en objectifs / missions / décisions attendues
  -> Kanban matérialise l'exécution traçable
  -> Agents produisent artefacts + preuves + demandes de décision
  -> Athena contrôle les livrables critiques
  -> H-Omar arbitre / priorise / autorise
  -> Alex valide, sudo, tranche ou réoriente depuis QG
  -> QG met à jour l'état du système et la stratégie
```

### 9.1 Les 3 boucles à rendre visibles

Le QG doit rendre visibles trois boucles, pas seulement des statuts techniques:

1. **Stratégie**
   - ambitions du moment;
   - priorités business;
   - hypothèses produit;
   - décisions ouvertes;
   - arbitrages Alex/H-Omar.

2. **Production**
   - missions agents;
   - cartes Kanban;
   - PR / artefacts;
   - blockers;
   - sudo / secret / dépense requis;
   - livrables du jour.

3. **Contrôle**
   - gates Athena;
   - preuves;
   - conformité OmarTop;
   - écarts;
   - incidents;
   - validation Alex.

### 9.2 QG comme point de départ de journée

Alex doit pouvoir commencer la journée dans QG avec une intention simple:

```txt
Voilà ce que j'aimerais aujourd'hui.
Qu'est-ce que vous pouvez produire ?
Qu'est-ce qui bloque ?
Qu'est-ce que je dois valider ?
```

Le QG doit répondre avec:

- une proposition de plan du jour;
- les agents mobilisables;
- les livrables proposés;
- les décisions humaines requises;
- les risques;
- les cartes Kanban créées ou proposées;
- les validations attendues au fil de la journée.

### 9.3 QG comme compte-rendu agents

Chaque agent contrôlé par OA devrait pouvoir rendre compte dans un format standard consommable QG:

```json
{
  "agent_id": "oa-builder",
  "period": "2026-07-07-am",
  "mission": "...",
  "status": "running|blocked|done|needs_review",
  "produced": [],
  "proofs": [],
  "needs_from_alex": [],
  "needs_from_h_omar": [],
  "needs_from_athena": [],
  "next_action": "...",
  "kanban_task_id": "...",
  "github_refs": [],
  "risk": "low|medium|high"
}
```

Ce rapport ne remplace pas Kanban: il l'agrège. Kanban reste le ledger d'exécution; QG devient le cockpit de synthèse, d'arbitrage et de validation.

### 9.4 QG et Kanban: séparation nette

- **Kanban** = unité de travail, dispatch, statut, résultat persistant.
- **QG** = intention, priorisation, supervision, décision, validation, état global.

Une carte Kanban sans visibilité QG peut exister pour du travail interne bas niveau.
Mais une décision stratégique, une validation Alex, une release, un blocage sudo, ou une dérive système doit remonter QG.

### 9.5 Conversations éparses -> bannière commune

Les conversations Telegram, Agora, VS Code, Claude Code, Hermes, Fable et autres ne doivent plus être des sources de vérité concurrentes.

Règle cible:

- conversation = canal d'entrée ou de discussion;
- Kanban = trace de travail;
- GitHub = trace code/review;
- OmarTop = standard;
- Athena = contrôle;
- QG = bannière commune et état décisionnel.

Si une conversation produit une décision, elle doit être recanonisée dans QG/Kanban/GitHub/OmarTop selon sa nature.

### 9.6 Interface QG cible

Le QG doit ajouter une zone de commandement, pas seulement des pages de lecture:

1. **Intentions du jour**
   - saisie ou import depuis Alex/H-Omar;
   - conversion en missions proposées.

2. **Plan proposé par les agents**
   - qui peut produire quoi aujourd'hui;
   - livrables attendus;
   - dépendances.

3. **Décisions à prendre**
   - sudo;
   - secret;
   - dépense;
   - release;
   - arbitrage produit;
   - validation client.

4. **Contrôles à valider**
   - Athena verdicts;
   - smoke tests;
   - preuves;
   - écarts OmarTop.

5. **Fil d'exécution unifié**
   - événements Kanban/GitHub/agents;
   - seulement les changements utiles;
   - pas de bruit répétitif.

## 10. Règle CTO

Avant tout nouveau patch QG, demander:

1. Est-ce branché sur une source vivante ou est-ce un texte?
2. Est-ce que ça réduit l'incertitude d'Alex?
3. Est-ce que ça relie système, client, standard ou action?
4. Est-ce que ça aide à décider, produire ou contrôler?
5. Est-ce que ça supprime un doublon ou en crée un?
6. Est-ce que la fraîcheur et la preuve sont visibles?

Si non: ne pas ajouter au QG.

## 11. Prochain geste recommandé

Ne pas ajouter une nouvelle page décorative.

Prochain PR QG recommandé:

`feat/qg-control-tower-truth-audit-and-managed-vps-contract`

Scope:
- auditer les API/pages existantes par source_type;
- exposer `managed-vps` V0;
- afficher une matrice courte OA-master/Pantheos/JAB;
- marquer explicitement les données seed/manual comme non fiables;
- ajouter le modèle `agent_report` consommable par QG;
- ajouter une première section `Décisions / validations Alex`;
- clarifier Kanban = ledger d'exécution, QG = cockpit de commandement;
- créer les issues OmarTop nécessaires pour standardiser `oa.managed-vps/v1` et les rapports agents.
