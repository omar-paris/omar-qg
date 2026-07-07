# QG — Revue page par page vers Control Tower

Date: 2026-07-07
Auteur: H-Omar/default
Statut: conducteur de revue avec Alex — préparation, non implémentation
Repo: `/home/omar/23-Offre/actifs/omar-qg`

## 0. But

Préparer la revue du QG **du haut de la première page jusqu'à la dernière**, page par page, avec Alex.

Objectif: décider pour chaque page:

1. ce qu'elle doit permettre de **décider / produire / contrôler**;
2. si elle est utile telle quelle, à fusionner, à transformer, ou à retirer;
3. quelle source vivante elle doit consommer;
4. quelle action concrète lancer ensuite dans Kanban/GitHub/OmarTop/Athena;
5. quels éléments du rapport `Sovereign Multi Agent Architecture.md` doivent être intégrés.

Le QG cible n'est pas un dashboard passif. C'est la **tour de contrôle décisionnelle OA**.

```txt
Intention Alex
  -> QG priorise / propose / affiche ce qui demande décision
  -> Kanban exécute
  -> Agents produisent rapports + preuves
  -> Athena contrôle
  -> H-Omar arbitre
  -> OmarTop standardise
  -> QG reflète l'état système
```

## 1. Principes tirés du rapport Deepsearch

Le rapport est utile comme **inspiration architecturale**, mais pas comme vérité exécutable à copier sans audit. Certains outils/citations/claims doivent être vérifiés avant adoption.

### 1.1 À intégrer dans les standards OmarTop

| Axe | Standard OmarTop à créer/renforcer | Pourquoi |
|---|---|---|
| Séparation des pouvoirs | `oa.governance-powers/v1` | OmarTop = loi, QG/Hub = exécutif, Athena = judiciaire. Empêche les agents de modifier leurs propres règles/gates. |
| VPS managé | `oa.managed-vps/v1` | Définir ce qu'un VPS doit produire pour être considéré supervisé par OA. |
| Rapport d'état | `oa.vps-report/v1` | Contrat redacted produit localement par chaque VPS/agent. |
| Hub local | `oa.hub-status/v1` | État local safe consommable par QG sans accès direct aux bases sensibles. |
| Ressources documentaires | `oa.resource-scope/v1` | Sources, exclusions, permissions, review_needed, extraction contrôlée. |
| Cloud Map | `oa.cloudmap/v1` | Metadata-first, pas de déplacement physique des documents, extraction à la demande. |
| Rapport agent | `oa.agent-report/v1` | Mission, statut, preuves, besoins Alex/H-Omar/Athena, next action. |
| Secrets | `oa.secrets-runtime/v1` | Secrets via refs/scopes, jamais secrets bruts dans rapports/QG/logs. |
| Validation | `oa.athena-gate/v1` | Validation déterministe d'abord, LLM seulement pour diagnostic d'écart. |

### 1.2 À intégrer dans la supervision QG

QG doit afficher, pour chaque bloc important:

```txt
source_type: live | generated | seed | manual | unknown
freshness: timestamp + âge
proof: lien API / fichier / PR / task / gate
owner: agent/humain/service
standard_target: OmarTop contract/version
status: pass | fail | unknown | degraded | not_applicable
next_action: action ownerisée ou décision requise
```

### 1.3 À intégrer dans Athena QA

Athena doit devenir la gate froide de conformité:

1. vérifier la structure des rapports (`vps-report`, `agent-report`, `hub-status`);
2. vérifier redaction/secrets;
3. classer les écarts `ROUGE / JAUNE / GRIS / VERT`;
4. produire un verdict exploitable par H-Omar;
5. ne pas réécrire le produit à la place du builder.

### 1.4 Push-back CTO

À ne pas adopter aveuglément maintenant:

- **Dagu**: intéressant, mais QG a déjà collecteurs + crons + Hermes cron. On ne remplace pas l'existant avant d'avoir prouvé le manque.
- **CUE/Rego**: bon horizon pour contrats, mais V0 peut commencer en JSON Schema/Python si c'est ce qui ferme vite la boucle.
- **Firecracker/libkrun**: bon standard L3, pas chantier immédiat pour le QG page-par-page.
- **vstash**: piste Cloud Map, mais d'abord clarifier le contrat `oa.resource-scope/v1` et les sources existantes.
- **Auto-remédiation réseau**: utile plus tard; aujourd'hui, bloquer/alerter sans GO humain sur actions risquées.

## 2. Inventaire réel des pages QG actuelles

Preuve: inventaire `public/**/index.html` + `README.md` du repo QG.

Routes actuelles principales:

```txt
/
/manifeste/
/carte/
/blocages/
/objectifs/
/chantiers/
/agent-loop/
/ops/
/clients/
/partenaires/
/decisions/
/builds/
/changelog/
/apps/landing/
/apps/app/
/apps/catalogue/
/apps/lab/
/apps/qg/
/apps/hub/
/apps/omartop/
```

APIs visibles principales:

```txt
/api/core-repos.json
/api/blocages.json
/api/chantiers.json
/api/objectifs.json
/api/decisions.json
/api/builds.json
/api/carte.json
/api/boucles.json
/api/agent-loop-audit.json
/api/agent-loop-registry.json
/api/repo-health.json
/api/ops/storage-summary.json
/api/ops/vps-fleet.json
/api/vps-app-inventory.json
/api/vps-resource-onboarding-v0.json
/api/oa-fleet-supervision-v0.json
/api/vps.json
```

## 3. Ordre recommandé de revue avec Alex

Je propose de ne pas suivre seulement l'ordre technique des fichiers, mais l'ordre de lecture visible du QG:

1. `/` — accueil / registry / point de départ
2. `/manifeste/`
3. `/carte/`
4. `/blocages/`
5. `/objectifs/`
6. `/chantiers/`
7. `/agent-loop/`
8. `/ops/`
9. `/clients/`
10. `/partenaires/`
11. `/decisions/`
12. `/builds/`
13. `/changelog/`
14. `/apps/*/` — fiches apps, en lot ou une par une

## 4. Grille page par page

### 4.1 `/` — Registry CORE OA

**État actuel:** page d'entrée centrée registry CORE OA, tuiles blocages/builds/agent-loop/fleet, API `/api/core-repos.json`.

**Utilité cible:** doit devenir le vrai **poste de commandement du jour**.

**À garder:**
- résumé haut niveau;
- liens vers blocages, ops, builds;
- registry apps/repos si lié à santé réelle.

**À changer:**
- remplacer l'impression “registry” par “Que doit-on décider / produire / contrôler maintenant ?”;
- afficher une zone `Intentions / Plan proposé / Décisions / Contrôles`;
- marquer explicitement les données figées ou générées.

**Source vivante attendue:**
- `qg_control_state.json` ou équivalent;
- `agent_report` agrégé;
- blocages, ops, builds, Athena gates.

**Question Alex pendant revue:**
> Quand tu ouvres le QG, veux-tu voir d'abord les objectifs business, les blocages humains, ou l'état des agents ?

**Action probable:** refondre home en cockpit 4 bandes: `Décider`, `Produire`, `Contrôler`, `Surveiller`.

---

### 4.2 `/manifeste/` — Boussole OA

**État actuel:** page doctrine/manifeste, API `/api/manifeste.json`.

**Utilité cible:** garder seulement si elle sert de boussole courte reliée aux standards et actions.

**À garder:**
- promesse OA;
- règles de décision;
- liens vers AppOmar/OmarTop/chantiers.

**À changer:**
- ne pas dupliquer OmarTop;
- afficher `source_type`, version du manifeste, date de validation;
- lier chaque principe à un standard OmarTop ou une page QG opérationnelle.

**Inspiration Deepsearch:** séparation pouvoirs + souveraineté + anti-Kubernetes/sprawl.

**Action probable:** transformer en `Doctrine courte + standards liés`, pas texte long.

---

### 4.3 `/carte/` — Puzzle OA

**État actuel:** très grande page (~104 KB), APIs `/api/carte.json`, `/api/boucles.json`, marqueurs `figé/snapshot/seed`.

**Utilité cible:** carte système utile si elle montre les relations **système -> client -> standard -> preuve -> action**.

**À garder:**
- vision globale;
- strates OA;
- dépendances fortes.

**À changer:**
- signaler les segments seed/figés;
- éviter la carte décorative exhaustive;
- prioriser les zones actives: QG, OmarTop, Athena, AppOmar, Hub, Cloud Map, VPS.

**Inspiration Deepsearch:** modèle institutionnel des trois pouvoirs.

**Action probable:** découper en carte synthétique + liens vers pages dédiées; créer un contrat de relation `oa.system-map/v1`.

---

### 4.4 `/blocages/` — Ce qui bloque

**État actuel:** page déjà utile, source collecteur `/api/blocages.json`, action endpoint `/api/blocages/answer`.

**Utilité cible:** page centrale décisionnelle: ce que seul Alex/H-Omar/sudo/secret/release peut débloquer.

**À garder:**
- compteur unique;
- séparation par type;
- `qui_debloque`;
- réponse inline si fiable.

**À changer:**
- relier chaque blocage à standard/gate/action;
- distinguer `decision`, `secret`, `sudo`, `spend`, `prod-risk`, `unknown`;
- ajouter sévérité façon Athena: ROUGE/JAUNE/GRIS.

**Inspiration Deepsearch:** scoring écarts de conformité.

**Action probable:** faire de `/blocages/` la première page à valider après home.

---

### 4.5 `/objectifs/` — Objectifs

**État actuel:** snapshot figé depuis le 14/06 selon README/tests.

**Utilité cible:** ne doit pas rester figé. Soit il devient `Objectifs stratégiques actifs`, soit il fusionne dans home/chantiers.

**À garder:**
- peu d'objectifs;
- progression;
- décisions liées.

**À changer:**
- source vivante obligatoire;
- owner + horizon + preuve;
- relation à AppOmar/revenus/clients.

**Action probable:** fusion partielle dans home; garder route legacy jusqu'à migration.

---

### 4.6 `/chantiers/` — Quoi finir dans l'ordre

**État actuel:** `var/chantiers.json`, marqueur figé, renvois décisions.

**Utilité cible:** page d'exécution synthétique, pas remplacement Kanban.

**À garder:**
- ordre de priorité;
- horizon;
- lien blocage/décision.

**À changer:**
- chaque chantier doit avoir `kanban_task_id`, owner, proof, next action;
- limiter aux chantiers actifs, pas backlog complet.

**Action probable:** connecter à Kanban + agent reports; afficher top 5 chantiers seulement.

---

### 4.7 `/agent-loop/` — Audit anti-orphelins

**État actuel:** APIs `/api/agent-loop-audit.json`, `/api/agent-loop-registry.json`, marqueurs figé/snapshot.

**Utilité cible:** essentiel pour autonomie agents, mais doit passer de seed audit à boucle vivante.

**À garder:**
- anti-orphelins issue/Kanban/PR/gate;
- registry agents;
- sorties machine-readable.

**À changer:**
- ajouter `oa.agent-report/v1`;
- afficher agents actifs/dormants/non-spawnables;
- montrer mission en cours, preuve, besoin, next action;
- ne jamais faire croire qu'un agent tourne si assignee non spawnable.

**Inspiration Deepsearch:** gouvernance agents non déterministes + rapports standardisés.

**Action probable:** prioritaire après `/blocages/` et `/ops/`.

---

### 4.8 `/ops/` — Ops quotidien

**État actuel:** page déjà dense; APIs storage, repo health, VPS fleet, daily ledger. Marqueur snapshot.

**Utilité cible:** cœur supervision technique/fleet.

**À garder:**
- storage;
- repo health;
- VPS fleet;
- daily ledger;
- source unique supervision.

**À changer:**
- structurer selon `oa.vps-report/v1` et `oa.managed-vps/v1`;
- afficher conformité OmarTop par VPS;
- mettre `freshness` visible partout;
- séparer `unknown` de `down`;
- afficher `managed_by_oa=true/false/partial`.

**Inspiration Deepsearch:** vps-report, NMM L0/L1/L2/L3, secrets governance, telemetry.

**Action probable:** construire matrice OA-master / Pantheos / JAB / futurs clients.

---

### 4.9 `/clients/` — Clients & VPS

**État actuel:** inventaire apps silencieux, `legacy/compat`, renvoie supervision vers `/ops/`.

**Utilité cible:** lifecycle client, pas supervision technique principale.

**À garder:**
- inventaire client/VPS redacted;
- apps par client/VPS;
- liens vers onboarding/resources.

**À changer:**
- afficher lifecycle: audit -> devis -> onboarding -> provisioning -> hub -> maturité -> SAV;
- ne pas mélanger clients et VPS internes;
- garder supervision technique dans `/ops/`.

**Inspiration Deepsearch:** onboarding reproductible + rapports d'état.

**Action probable:** transformer en page `Clients lifecycle`, pas “inventaire silencieux” seulement.

---

### 4.10 `/partenaires/` — Catalogue fournisseurs

**État actuel:** catalogue fournisseurs, marker compat.

**Utilité cible:** utile si lié aux choix fournisseurs OA et standards; sinon bruit.

**À garder:**
- fournisseurs stratégiques: Hetzner, Infisical, Nango, LiteLLM, Langfuse, Tailscale, etc.;
- coût/licence/risque/souveraineté.

**À changer:**
- relier aux standards OmarTop et décisions AppOmar;
- ne pas devenir une liste SaaS décorative;
- indiquer `adopted`, `candidate`, `rejected`, `watch`.

**Inspiration Deepsearch:** stack minimale 90 jours, mais avec vérification locale.

**Action probable:** peut être fusionnée dans `/manifeste/` ou `/ops/standards` si elle ne porte pas de décision.

---

### 4.11 `/decisions/` — Décisions en attente

**État actuel:** endpoint `/api/decisions/answer`, marker legacy.

**Utilité cible:** page centrale de validation Alex/H-Omar.

**À garder:**
- décisions ouvertes/répondues;
- réponse directe;
- anchors pour liens depuis objectifs/chantiers.

**À changer:**
- fusion logique avec `/blocages/` ou statut clair: décision ≠ blocage;
- typologie des décisions: business, secret, sudo, release, architecture, client;
- chaque décision doit avoir impact, deadline, option recommandée.

**Action probable:** soit conserver comme sous-page de `/blocages/`, soit la mettre très haut dans home.

---

### 4.12 `/builds/` — Builds du jour

**État actuel:** API `/api/builds.json`, marqueurs snapshot/legacy.

**Utilité cible:** preuve de production, pas changelog bis.

**À garder:**
- commits/builds récents;
- déploiements;
- liens PR/commit.

**À changer:**
- relier chaque build à une mission/chantier/gate;
- afficher `built`, `reviewed`, `released`, `live_smoked`;
- éviter de compter un commit comme valeur business sans livraison.

**Inspiration Deepsearch:** observabilité, trace IDs, coût/latence plus tard.

**Action probable:** connecter à `agent-report` + Athena verdicts.

---

### 4.13 `/changelog/` — Changelog

**État actuel:** historique QG, nombreux liens API, marqueurs snapshot/seed.

**Utilité cible:** journal de confiance visible, pas source de vérité principale.

**À garder:**
- livraison QG visible;
- dates/version;
- lien vers preuves.

**À changer:**
- chaque entrée doit pointer vers PR/build/gate ou “doc-only”;
- séparer changement code vs cadrage vs runtime;
- éviter d'y cacher des décisions actives.

**Action probable:** garder en support, pas dans le flux principal de revue.

---

### 4.14 `/apps/*/` — Fiches apps

Routes:

```txt
/apps/landing/
/apps/app/
/apps/catalogue/
/apps/lab/
/apps/qg/
/apps/hub/
/apps/omartop/
```

**État actuel:** fiches issues registry/apps/repos, variable selon app.

**Utilité cible:** chaque fiche app doit répondre:

```txt
À quoi sert l'app ?
Est-elle live ?
Quelle version ?
Quel repo/source ?
Quel owner ?
Quelle preuve récente ?
Quel écart vs OmarTop ?
Quelle prochaine action ?
```

**À changer:**
- ne pas dupliquer Hub/Catalogue/OmarTop;
- ajouter health/version/live URL/PR active/gate;
- afficher `business_role`: acquisition, audit, onboarding, supervision, standard, client, interne.

**Action probable:** revoir en lot après les pages système; commencer par `/apps/qg/`, `/apps/app/`, `/apps/omartop/`, `/apps/hub/`.

## 5. Synthèse: pages à traiter en priorité

| Priorité | Page | Pourquoi |
|---|---|---|
| P0 | `/` | C'est le point d'entrée; aujourd'hui trop “registry”, pas assez tour de contrôle. |
| P0 | `/blocages/` | Cœur décisionnel Alex/H-Omar; déjà proche de l'usage voulu. |
| P0 | `/ops/` | Cœur supervision fleet; doit intégrer `vps-report`/managed VPS. |
| P1 | `/agent-loop/` | Cœur autonomie agents; besoin `agent-report/v1`. |
| P1 | `/decisions/` | À clarifier/fusionner avec blocages ou remonter home. |
| P1 | `/clients/` | Doit devenir lifecycle client, pas inventaire silencieux uniquement. |
| P2 | `/carte/` | Utile mais trop grande/seed; à rendre relationnelle et vérifiable. |
| P2 | `/chantiers/` | À connecter à Kanban/agents; sinon snapshot. |
| P2 | `/objectifs/` | Figé; à fusionner ou revitaliser. |
| P3 | `/partenaires/` | Utile seulement si elle porte des arbitrages standards/fournisseurs. |
| P3 | `/manifeste/` | Garder court, relié à OmarTop. |
| P3 | `/builds/` | Preuve utile, mais doit être reliée aux gates/livraisons. |
| P3 | `/changelog/` | Support de confiance, pas cockpit. |
| P3 | `/apps/*/` | À normaliser après le socle cockpit. |

## 6. Proposition de méthode Telegram

Pour chaque page, je propose le format de revue suivant:

```txt
PAGE: /xxx/
A. Ce qu'elle fait aujourd'hui
B. Ce qu'elle devrait faire dans le QG Control Tower
C. Ce qu'on garde / supprime / fusionne
D. Source vivante nécessaire
E. Action immédiate proposée
F. Question Alex si arbitrage nécessaire
```

Règle de décision:

- si la page aide à **décider**, **produire**, ou **contrôler** → on la garde/refond;
- si elle est seulement informative mais utile → on la fusionne;
- si elle est texte mort, seed non assumé, ou doublon → on retire/masque derrière legacy.

## 7. Premier lot de code recommandé

Nom de branche:

```txt
feat/qg-control-tower-page-review-and-truth-contract
```

Scope minimal:

1. ajouter un `qg_truth_audit.json` généré listant pages/widgets/API avec `source_type`;
2. ajouter sur la home un bandeau Control Tower: `Décisions`, `Production`, `Contrôle`, `Fleet`;
3. enrichir `/ops/` avec matrice `managed-vps` V0;
4. ajouter modèle `oa.agent-report/v1` comme fixture/API;
5. marquer visiblement les pages `figé/seed/legacy`;
6. ne pas supprimer les routes avant revue Alex page par page.

## 8. Décision CTO

Ma recommandation: **on commence la revue par `/` puis `/blocages/` puis `/ops/`**, pas par les pages app.

Raison: si ces trois pages deviennent correctes, le QG devient déjà une tour de contrôle. Les autres pages pourront ensuite être jugées par rapport à cette colonne vertébrale.
