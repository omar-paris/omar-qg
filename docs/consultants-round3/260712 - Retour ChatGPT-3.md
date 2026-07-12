# Verdict

**Je refuse les deux options extrêmes.**

* **Refaire intégralement le QG** serait coûteux, risqué et jetterait des fonctions déjà mûres : RBAC, vues client, sondes, alertes, conformité et audit.
* **Continuer à étendre librement le QG organique** jusqu’à en faire le gardien de toute la flotte serait dangereux : on transformerait une dette fonctionnelle tolérable en dette de sûreté.

Ma recommandation est donc :

> **ÉTENDRE la console existante, mais RECONSTRUIRE à côté un noyau de sûreté minimal, indépendant et testable.**

Décision par périmètre :

| Périmètre                                            | Décision                             |
| ---------------------------------------------------- | ------------------------------------ |
| Front flotte, navigation, vues client, RBAC existant | **CONSERVER et étendre**             |
| Ingestion des signaux critiques                      | **NOUVEAU noyau**                    |
| Calcul de l’état flotte                              | **NOUVEAU noyau déterministe**       |
| Machine d’incident et alerting                       | **NOUVEAU noyau**                    |
| Logs, métriques, traces                              | **Services séparés du noyau**        |
| Preuve flotte                                        | **Stockage séparé et ancré hors QG** |
| Actions descendantes vers les VPS                    | **RETIRER du MVP**                   |
| Remontée VPS→QG                                      | **Push sortant uniquement**          |
| Supervision du QG                                    | **Témoin extérieur indépendant**     |

Le brief positionne désormais le QG à la fois comme cockpit de l’opérateur et filet de sécurité de la flotte, avec une concentration inter-clients déjà identifiée comme dangereuse. Cette double mission impose une séparation nette entre la **console pratique** et le **noyau de sûreté**. 

Architecture cible :

```text
Hub local
   │
   │ push mTLS sortant uniquement
   ▼
QG Ingest Gateway
   │
   ├──► QG Safety Core
   │       ├─ registre flotte
   │       ├─ état des VPS
   │       ├─ évaluateur déterministe
   │       ├─ machine d’incident
   │       └─ routeur d’alertes indépendant
   │
   ├──► Evidence Store + checkpoints externes
   │
   └──► Telemetry Cells
           ├─ logs
           ├─ métriques
           └─ traces

QG Console existante ── lecture API ──► Safety Core
                                      └► Telemetry Cells

Témoin extérieur indépendant
   ├─ surveille le QG
   ├─ reçoit un heartbeat minimal des VPS
   └─ alerte sans dépendre du QG
```

La console peut tomber sans arrêter l’évaluation des incidents. Loki peut tomber sans empêcher un heartbeat de devenir rouge. Le QG peut être indisponible sans empêcher le métier local de continuer.

---

# P0 — À corriger avant la première production

## P0.1 — MODIFIER : étendre la console, pas le cœur de sûreté existant

**Pourquoi**

Un logiciel peut être « mature » parce qu’il a beaucoup de fonctionnalités, tout en étant totalement immature comme système de sûreté. La maturité d’un QG safety-critical se prouve autrement :

* frontières de confiance explicites ;
* comportement déterministe ;
* modes de panne documentés ;
* tests de non-régression et d’isolation ;
* dépendances bornées ;
* possibilité de fonctionner sans le front ;
* preuve que les alertes partent même lorsque le QG est partiellement cassé.

Le danger serait de continuer à ajouter des `if`, des crons, des vues et des accès directs à une base organique dont personne ne maîtrise plus exactement les couplages.

**Cas concret**

Une release destinée à ajouter un filtre dans la vue « Clients » modifie un modèle partagé. Le worker qui calcule les silences ne retrouve plus le champ `last_seen`. Tous les VPS restent visuellement verts pendant huit heures. La console fonctionne ; le filet, lui, est mort.

**À faire**

1. Geler toute nouvelle logique safety-critical dans l’ancien QG.
2. Écrire des tests de caractérisation sur son comportement actuel.
3. Créer un `qg-safety-core` avec sa propre base, ses propres migrations et sa propre API.
4. Faire consommer cette API par le QG existant.
5. Faire tourner ancien et nouveau évaluateurs en parallèle.
6. Comparer alertes manquées, faux positifs et divergences pendant une période représentative.
7. Supprimer ensuite l’ancien calcul de sûreté : il ne doit jamais rester deux vérités actives.

**RETIRER** également tout accès direct de la console à la base du safety core. La console appelle une API ; elle ne lit pas les tables selon son humeur du jour.

---

## P0.2 — RETIRER : le « pull côté Omar » et tout canal descendant au MVP

Il existe une contradiction documentaire :

* le modèle affirme une remontée **montante uniquement** ;
* plusieurs passages décrivent encore `outbox → pull côté Omar`.  

Ce n’est pas la même architecture.

### Décision recommandée

```text
VPS → connexion sortante mTLS → QG
```

Le QG ne doit pas :

* se connecter en SSH aux VPS ;
* détenir un credential lui permettant de lire chaque Hub ;
* scanner les VPS ;
* tirer les outboxes ;
* pousser des commandes ;
* disposer d’un compte agent global flotte.

**Pourquoi**

Un QG qui peut entrer sur les VPS devient un pivot inter-clients. Sa compromission ne produit plus seulement une fuite de logs : elle produit une compromission de flotte.

**Cas concret**

Le compte de service du QG est compromis. L’attaquant réutilise sa capacité de pull pour accéder aux endpoints internes de cinquante clients, puis exploite un Hub ancien. L’isolation « un VPS = un client » est détruite depuis le centre.

### Clarification indispensable sur le mot « bloquant »

* **Bloquant comme gate de mise en production** : oui.
* **Bloquant dans le chemin métier quotidien** : non.
* **Bloquant pour une action locale R4/R5 lorsque la surveillance est inconnue** : éventuellement, mais ce contrôle doit vivre dans le Hub local, sur une politique locale signée et non dans un appel synchrone au QG.

Le QG doit rester **superviseur**, pas devenir le bus obligatoire que la V4 vient précisément de retirer du Hub.

---

## P0.3 — AJOUTER : un témoin extérieur réellement indépendant

La « troisième position » est une bonne intuition, mais elle est sous-spécifiée.

Un serveur différent n’est pas indépendant s’il partage avec le QG :

* le même fournisseur ;
* le même compte cloud ;
* le même Tailnet ;
* le même DNS ;
* le même IdP ;
* la même CI/CD ;
* les mêmes credentials administrateur ;
* le même code de calcul de santé.

### Le témoin doit avoir une autre frontière administrative

Il lui suffit de faire peu de choses :

```text
- recevoir un heartbeat minimal et signé des VPS ;
- sonder le QG ;
- vérifier l’arrivée des checkpoints de preuve ;
- envoyer une alerte directement par un canal indépendant ;
- ne conserver quasiment aucune donnée métier.
```

**Cas concret**

Une mauvaise règle ACL Tailnet coupe simultanément :

* les sondes QG→VPS ;
* l’accès de l’opérateur au QG ;
* les alertes émises par le QG ;
* les sondes de la prétendue « troisième position », également membre du Tailnet.

Le système transforme une panne commune en mille faux incidents — ou pire, en silence complet.

### À ajouter aussi : un canal d’alerte hors QG

Le QG ne peut pas être chargé d’envoyer l’unique alerte annonçant que le QG est mort. Il faut au moins :

* un canal principal ;
* un canal indépendant de secours ;
* un test synthétique périodique de livraison ;
* une attente d’accusé ;
* une escalade si l’alerte n’est pas acquittée.

---

## P0.4 — MODIFIER : heartbeat + outside-in + log store ne suffisent pas

**Réponse nette : non, ces trois briques ne suffisent pas.**

Elles répondent seulement à trois questions partielles :

| Signal     | Ce qu’il prouve réellement                       |
| ---------- | ------------------------------------------------ |
| Heartbeat  | un processus est capable d’émettre quelque chose |
| Outside-in | un endpoint répond depuis un point donné         |
| Logs       | certaines opérations ont produit une trace       |

Aucun ne prouve que le système réalise encore son travail utile.

### AJOUTER quatre familles de signaux

1. **Auto-déclaration locale** : heartbeat, état des services, version.
2. **Observation extérieure** : DNS, TLS, authentification, `/ready`, latence.
3. **Travail attendu** : dernier backup, dernier contrôle de conformité, dernier cycle agent, âge de l’outbox, dernier test de canal.
4. **Santé de la chaîne de télémétrie** : dernière séquence acceptée, trous, files pleines, événements rejetés, données perdues.

**Cas concret**

Le Hub émet parfaitement son heartbeat. `/ready` répond 200. Loki reçoit des logs. Mais :

* le cron backup est arrêté depuis six jours ;
* aucun run agent n’a terminé depuis trois heures ;
* le token du logiciel de facturation est expiré ;
* l’outbox grossit sans être acquittée.

Le VPS est joignable, mais opérationnellement cassé.

### MODIFIER le vert

Un VPS ne doit être vert que si ses signaux obligatoires sont concordants.

```text
local = vert
outside_in = vert
expected_work = vert
telemetry_pipeline = vert
--------------------------------
état final = vert
```

Si les signaux divergent :

```text
local = vert
outside_in = rouge
--------------------------------
état final = DISPUTED, jamais vert
```

Je rajouterais les états flotte :

```text
healthy
degraded
silent
isolated
stale
disputed
unknown
maintenance
suspected_compromise
```

### AJOUTER une vraie machine d’incident

```text
pending
→ firing
→ acknowledged
→ investigating
→ mitigated
→ resolved
```

Avec :

* hystérésis ;
* délais `for` ;
* déduplication ;
* regroupement ;
* inhibition ;
* fenêtres de maintenance avec motif et expiration ;
* escalade ;
* lien vers runbook ;
* fermeture automatique seulement sur preuve de retour.

**Cas concret**

Une panne Tailnet provoque 500 échecs de sonde. Sans corrélation, Alexandre reçoit 500 alertes VPS. Avec un graphe de dépendances, le QG produit un incident principal « connectivité Tailnet » et conserve les 500 impacts comme conséquences, sans transformer le téléphone en maracas.

---

## P0.5 — MODIFIER : ne pas promettre « exactly once »

Le contrat montant est bien orienté, mais `sequence + accusé + anti-rejeu` ne produit pas automatiquement du exactly-once.

### Décision

Utiliser des garanties différentes selon le flux :

| Flux                | Garantie cible                                                  |
| ------------------- | --------------------------------------------------------------- |
| Heartbeat           | dernier état valide gagne, doublons tolérés                     |
| Conformité          | at-least-once + déduplication + détection de trous              |
| Preuve              | append-only applicatif + déduplication + checkpoint             |
| Erreurs structurées | at-least-once                                                   |
| Logs et traces      | at-least-once ou best effort explicite                          |
| Backfill historique | voie distincte, sans déclencher d’alerte rétroactive par défaut |

Les files persistantes de l’OpenTelemetry Collector résistent à un redémarrage, mais les données peuvent encore être perdues en cas de disque plein, panne disque ou dépassement des limites de retry ; la documentation précise que leurs garanties restent plus faibles que celles d’une file dédiée. Le Collector ne doit donc pas devenir le transport de preuve du QG. ([OpenTelemetry][1])

### AJOUTER au contrat

```text
envelope_version
event_id
deployment_id
tenant_id
stream_id
producer_id
producer_epoch
sequence
event_type
schema_name
schema_version
producer_version
policy_bundle_version
occurred_at
sent_at
priority
retention_class
data_classification
payload_hash
key_id
signature
```

La séquence doit être portée par :

```text
(deployment_id, producer_epoch, stream_id)
```

et non par un compteur global du VPS.

### Pourquoi `producer_epoch` est indispensable

Après une restauration ou une réinstallation, une séquence peut repartir à zéro. Sans époque ou `boot_id`, le QG ne sait pas si l’événement est :

* un doublon ;
* un événement ancien ;
* une nouvelle instance ;
* un replay légitime ;
* une usurpation.

### L’accusé doit arriver après persistance durable

Réponse type :

```json
{
  "stream_id": "compliance",
  "producer_epoch": "01J...",
  "accepted_through": 1854,
  "gaps": [1849, 1851],
  "duplicates": [1842],
  "quarantined": [1853],
  "retry_after_s": 30,
  "server_time": "..."
}
```

**Cas concret**

Le QG persiste l’événement, mais son ACK est perdu. Le VPS réémet. Sans `event_id` et déduplication, deux incidents sont créés. Avec une promesse naïve « exactly-once », l’équipe pense ce risque résolu alors qu’il ne l’est pas.

---

## P0.6 — AJOUTER : lier le tenant à l’identité mTLS, pas au payload

`tenant_id` et `deployment_id` ne doivent jamais être crus parce qu’ils figurent dans le JSON.

Le QG doit :

1. authentifier le certificat du VPS ;
2. résoudre l’identité autorisée depuis le certificat ;
3. dériver `tenant_id` et `deployment_id` côté serveur ;
4. comparer avec les champs du payload ;
5. rejeter toute divergence.

### Règles

* un certificat distinct par VPS ;
* aucun certificat partagé ;
* rotation et révocation ;
* durée de vie limitée ;
* `key_id` et numéro de série enregistrés ;
* ré-enrôlement explicite après reconstruction ;
* aucune possibilité pour le client de choisir son tenant Loki ou son espace de stockage.

Loki identifie les tenants par `X-Scope-OrgID`. Sa documentation recommande que cet en-tête soit fixé par un proxy ou une gateway de confiance, pas par l’utilisateur final ; elle permet également des requêtes multi-tenants lorsque cette fonction est activée. Ici, le sender VPS ne doit jamais pouvoir fabriquer cet en-tête, et les requêtes multi-tenants brutes doivent rester désactivées. ([Grafana Labs][2])

**Cas concret**

Un Hub compromis modifie simplement :

```json
"tenant_id": "cabinet-concurrent"
```

Si le QG utilise ce champ pour router le log, un client écrit dans l’espace d’un autre. Le mTLS a authentifié « un VPS autorisé », mais l’isolation tenant a tout de même échoué.

---

## P0.7 — RETIRER : daybook, stderr et prompts bruts du plan de preuve

C’est un angle mort sérieux.

### Le daybook n’est pas une preuve

Un journal quotidien rédigé par un agent est une **narration**. Il peut être :

* incomplet ;
* erroné ;
* optimiste ;
* généré à partir d’une donnée périmée ;
* halluciné ;
* manipulé par un contenu externe.

Il peut être utile au cockpit, mais il ne doit pas entrer dans le calcul de conformité ou dans l’evidence plane comme vérité.

**Cas concret**

Le daybook indique :

> « Backup vérifié avec succès. »

Le processus de backup a retourné 0, mais le test de restauration n’a jamais été lancé. Le texte est rassurant ; la preuve est absente.

### Séparer les plans

| Plan         | Contenu                                                                |
| ------------ | ---------------------------------------------------------------------- |
| Evidence     | événements machine signés, verdicts, références de preuve, checkpoints |
| Opérationnel | erreurs structurées, codes, composant, empreinte de stack              |
| Narratif     | daybook et résumés agents                                              |
| Forensic     | logs bruts, stderr, traces détaillées                                  |
| LLM          | prompts, réponses, tool calls                                          |

### RETIRER du MVP central par défaut

* le stderr brut ;
* les corps HTTP ;
* le contenu des emails ;
* les noms complets de dossiers ;
* les prompts et réponses Langfuse ;
* les pièces jointes ;
* le texte intégral des daybooks ;
* toute ligne libre non validée par schéma.

### Remplacer par

```text
error_code
component
severity
stack_fingerprint
trace_id
first_seen
last_seen
occurrence_count
remediation_status
redacted_excerpt facultatif
```

Pour un client sensible, le log brut reste local. Le QG reçoit l’empreinte et les métadonnées. Un paquet forensic détaillé peut être envoyé plus tard sous procédure explicite, tenant unique, durée limitée et accès audité.

**Pourquoi**

« Pas de CA/trésorerie » est une bonne décision, mais un prompt LLM, un stderr ou un daybook peut contenir encore plus sensible qu’un montant. Le brief interdit les données commerciales tout en centralisant logs et observabilité : il faut résoudre cette contradiction par schéma, pas par bonne intention. 

La V4 mentionne encore ailleurs des vues d’« agrégation commerciale », alors que le brief QG interdit CA et trésorerie au MVP. Il faut **retirer cette mention du référentiel courant** ou la classer explicitement comme évolution future opt-in. 

---

## P0.8 — MODIFIER : la conformité flotte ne peut pas être un simple score moyen

Sur une flotte hétérogène, `68 %`, `81 %` ou `100 %` ne sont comparables que si :

* les mêmes lois sont présentes ;
* les mêmes versions sont exécutées ;
* les mêmes données sont disponibles ;
* les mêmes règles de calcul s’appliquent ;
* les mêmes contrôles sont obligatoires.

### AJOUTER

```text
policy_bundle_version
law_id
law_version
evaluator_hash
evaluated_at
evidence_reference
input_freshness
applicable
evaluated
verdict
```

Et séparer :

```text
pass_rate
coverage_rate
freshness_rate
```

**Cas concret**

* VPS ancien : 10 lois, 10 vertes → **100 %**.
* VPS nouveau : 20 lois, 17 vertes → **85 %**.

Le QG conclut que l’ancien est plus sûr. En réalité, il ne vérifie même pas la moitié des contrôles.

### Règle

Le QG doit afficher :

> 100 % de réussite sur 50 % de couverture — politique v1 — non comparable à v3.

Les comparaisons flotte doivent se faire par **cohorte de policy bundle**. Un score moyen inter-versions est une manière très élégante de mentir avec des chiffres parfaitement exacts.

---

## P0.9 — AJOUTER : rendre le mensonge du QG détectable

La 3e position et le PRA ne suffisent pas contre :

* un bug logique ;
* une règle d’alerte incorrecte ;
* une compromission du QG ;
* une suppression volontaire de preuve ;
* une mauvaise restauration ;
* une UI affichant un état différent du calcul brut.

### Le vert doit être dérivé, jamais éditable

Chaque état doit conserver :

```text
decision_id
rule_bundle_version
input_event_ids
evidence_hashes
computed_at
evaluator_version
confidence
```

La console ne doit pas pouvoir écrire :

```text
status = green
```

Elle peut seulement produire un événement :

```text
incident.acknowledged
maintenance.started
operator.comment_added
```

### AJOUTER des checkpoints externes

Périodiquement :

1. le QG calcule un hash ou une racine de ses événements de preuve ;
2. le checkpoint est signé ;
3. il est envoyé dans un stockage indépendant ;
4. le témoin extérieur vérifie sa continuité.

Un stockage WORM de type Object Lock peut empêcher la suppression ou l’écrasement des versions pendant une durée définie. Ce type de mécanisme convient aux **checkpoints minimisés**, pas aux logs personnels bruts. ([AWS Documentation][3])

**Cas concret**

Un attaquant compromet le QG, supprime un incident et réécrit l’état du client en vert. Il peut modifier la base active, mais il ne peut pas faire correspondre la nouvelle histoire avec les checkpoints déjà ancrés hors de son domaine.

### Important

Une signature du Hub prouve uniquement :

> « cette donnée a été produite par la clé du Hub ».

Elle ne prouve pas :

> « cette donnée dit vrai ».

Un VPS compromis peut signer un heartbeat vert parfaitement valide. Il faut donc conserver la pluralité des sources : local, outside-in, travail attendu et témoin extérieur.

---

## P0.10 — AJOUTER : la continuité de l’opérateur humain

Voici, à mon avis, **le plus grand angle mort du QG**.

Le système est conçu comme le cockpit d’un opérateur solo, mais il ne traite pas l’indisponibilité de cet opérateur.

> Une alerte détectée mais non traitée n’est pas un filet de sécurité. C’est un témoin de l’accident.

### Questions actuellement sans réponse

* Qui reçoit l’alerte si Alexandre est indisponible ?
* Qui possède les accès de récupération ?
* Qui peut diagnostiquer sans voir tous les clients ?
* Que se passe-t-il la nuit, le week-end ou pendant une hospitalisation ?
* À partir de quand le client est-il informé ?
* Quelles opérations sûres peuvent être réalisées sans Alexandre ?
* Qui peut révoquer un certificat compromis ?
* Qui déclenche le PRA du QG ?

### AJOUTER

* un répondant secondaire ou prestataire de secours ;
* un rôle break-glass très borné ;
* des accès de récupération sous séquestre ;
* une procédure d’escalade ;
* un délai d’acquittement ;
* une alerte directe au client pour certains incidents prolongés ;
* des runbooks exécutables par une autre personne ;
* un test périodique « opérateur principal indisponible » ;
* un heartbeat organisationnel : l’astreinte est-elle réellement couverte ?

**Cas concret**

À 03 h 10, le disque d’un cabinet atteint 98 %. L’alerte arrive sur le téléphone unique de l’opérateur, éteint. À 05 h 00, PostgreSQL s’arrête. À 08 h 30, le client découvre seul la panne. Techniquement, le QG avait parfaitement fonctionné. Commercialement et opérationnellement, le filet n’existait pas.

---

# P1 — À traiter avant de dépasser quelques dizaines de clients

## P1.1 — AJOUTER : des classes de priorité et une politique de perte

Toutes les données ne doivent pas partager la même file.

```text
P0 — heartbeat, révocation, incident critique, checkpoint
P1 — conformité, backup, état agent, sécurité
P2 — erreurs structurées
P3 — métriques détaillées
P4 — logs debug et traces volumineuses
```

### Règle

En cas de saturation :

1. supprimer ou échantillonner P4 ;
2. réduire P3 ;
3. conserver P0 et P1 ;
4. générer un événement `telemetry_loss`;
5. ne jamais remplir le disque du VPS pour sauver des logs.

**Cas concret**

Une boucle de crash produit 100 Mo de stderr par minute. Sans budget, le collecteur local remplit le disque et transforme une panne agent en panne totale du client.

Le Collector doit avoir un `memory_limiter`, une file bornée et une politique explicite de backpressure ; les recommandations OpenTelemetry prévoient précisément ces contrôles, mais elles n’éliminent pas le risque de perte. ([OpenTelemetry][4])

---

## P1.2 — MODIFIER : l’isolation tenant doit exister dans le stockage, pas seulement dans le front

Le QG existant possède déjà des vues client filtrées et du RBAC. Ce n’est pas suffisant, surtout après une fuite inter-tenant antérieure.

### Défenses nécessaires

* tenant dérivé de l’identité mTLS à l’ingestion ;
* tenant imposé par la gateway de logs ;
* stockage ou index séparé par cellule/tenant selon sensibilité ;
* quotas par tenant ;
* rétention par tenant ;
* chiffrement avec clés séparées pour les clients sensibles ;
* requêtes multi-tenants brutes désactivées ;
* cache partitionné ;
* exports marqués par tenant ;
* tests négatifs automatiques sur chaque route et type de requête ;
* accès support Just-in-Time avec justification ;
* authentification renforcée avant accès aux logs bruts.

Loki supporte l’isolation par tenant et des limites d’ingestion par tenant, mais cette isolation dépend fortement de la bonne fixation de l’identité de tenant par la gateway. ([Grafana Labs][2])

**Cas concret**

Le filtre du front affiche correctement Client A. Mais l’endpoint d’export reçoit un `tenant_id` depuis une query string oubliée et renvoie le CSV de Client B. Le RBAC visuel est vert ; la fuite est complète.

---

## P1.3 — MODIFIER : le PRA doit traiter la corruption logique et la compromission

Une réplica synchrone protège contre la panne matérielle. Elle ne protège pas contre :

* un `DELETE` erroné ;
* une migration destructive ;
* une règle d’alerte cassée ;
* un ransomware ;
* un administrateur compromis ;
* une donnée mensongère propagée.

**Cas concret**

Un bug supprime toutes les lignes `fleet_state`. La réplica, parfaitement fidèle, supprime exactement les mêmes lignes.

### AJOUTER

* sauvegardes point-in-time ;
* snapshots immuables ;
* rétention différée ;
* comptes et clés de backup séparés ;
* procédure de clean-room recovery ;
* restauration testée ;
* reconstruction du QG depuis code et données ;
* reprise des curseurs d’ingestion ;
* test de replay ;
* exercice de compromission, pas seulement de panne.

Le PRA doit prouver :

```text
QG détruit
→ safety core reconstruit
→ clés restaurées ou renouvelées
→ événements rejoués
→ trous identifiés
→ alertes recalculées
→ console reconnectée
```

---

## P1.4 — AJOUTER : un cycle de vie explicite du VPS

Le contrat manque d’états d’identité et d’exploitation :

```text
provisioning
active
maintenance
isolated
suspected_compromise
suspended
offboarding
retired
```

### À gérer

* première inscription ;
* renouvellement de certificat ;
* reconstruction du même VPS ;
* changement d’IP ou d’hébergeur ;
* restauration ancienne ;
* révocation après compromission ;
* départ du client ;
* export de données ;
* fin de rétention ;
* suppression de l’espace telemetry ;
* conservation éventuelle de preuves minimisées.

**Cas concret**

Un VPS est reconstruit depuis un backup vieux de trois semaines avec le même `deployment_id` et une séquence revenue à 400. Le QG le confond avec une attaque par rejeu et bloque ses messages — ou, inversement, fusionne ses données avec l’ancienne instance.

D’où la séparation :

```text
deployment_id = identité durable du déploiement client
producer_epoch = incarnation technique courante
```

---

## P1.5 — AJOUTER : une politique de données par flux

Créer un manifeste du type :

```yaml
streams:
  heartbeat:
    fields: [deployment_id, producer_epoch, sequence, status, sent_at]
    retention: 90d
    pii_allowed: false
    destination: safety_core

  error_summary:
    fields: [component, error_code, severity, fingerprint, trace_id]
    retention: 180d
    pii_allowed: false
    destination: safety_core

  raw_logs:
    enabled: false
    retention: 7d
    tenant_isolation: dedicated
    access: break_glass

  llm_content:
    enabled: false
    retention: 0d
```

### Redaction fail-closed

Si :

* le schéma est inconnu ;
* le redacteur plante ;
* un champ non allowlisté apparaît ;
* la classification est absente ;

alors l’événement est **mis en quarantaine**, pas envoyé « au mieux ».

### Rétention

La durée doit être définie par finalité et par classe, pas par une règle globale « tout garder un an ». La CNIL recommande de minimiser les données dans les journaux et de justifier les durées ; elle donne couramment une fourchette de six mois à un an pour la journalisation standard, avec des prolongations seulement lorsqu’elles sont justifiées par une finalité précise. ([CNIL][5])

Le QG doit donc distinguer :

* preuve minimisée ;
* logs techniques ;
* traces LLM ;
* accès opérateur ;
* incidents ;
* données mises sous conservation particulière.

---

## P1.6 — AJOUTER : des tests de panne adverses

La validation du QG ne doit pas être « le dashboard s’ouvre ».

Scénarios obligatoires :

1. heartbeat dupliqué ;
2. séquences désordonnées ;
3. trou de séquence ;
4. ACK perdu ;
5. VPS hors ligne sept jours ;
6. retour massif en backfill ;
7. horloge VPS en avance de quinze minutes ;
8. restauration avec séquence réinitialisée ;
9. certificat expiré ;
10. certificat révoqué ;
11. VPS tentant d’usurper un tenant ;
12. schéma v1, v2 et v4 simultanément ;
13. QG indisponible douze heures ;
14. log store indisponible ;
15. alerting principal indisponible ;
16. Tailnet cassé ;
17. redactor qui plante ;
18. log contenant un faux secret canari ;
19. vague de logs 100 fois supérieure ;
20. opérateur principal indisponible ;
21. QG compromis simulé ;
22. restauration du QG dans un environnement propre.

Pour chacun :

```text
signal attendu
état attendu
alerte attendue
délai attendu
données susceptibles d’être perdues
preuve produite
```

---

# Échelle : le heartbeat n’est pas le problème, les logs et l’humain le sont

À raison d’un heartbeat par minute :

* **1 000 VPS = environ 16,7 heartbeats/seconde** ;
* avec un message de 1 Ko, cela représente environ **1,5 Go/jour** avant overhead.

Ce trafic est assez modeste.

En revanche, avec une hypothèse très basse de **5 Ko/s de logs par VPS** :

| Flotte              |         Volume brut |
| ------------------- | ------------------: |
| 100 VPS             |  environ 43 Go/jour |
| 1 000 VPS           | environ 432 Go/jour |
| 1 000 VPS, 30 jours | environ 13 To bruts |

Cela exclut réplication, index, objets, traces et sauvegardes.

## MODIFIER : « un QG » doit devenir une notion logique

À l’échelle :

```text
Global Fleet Directory
   ├─ statuts minimisés
   ├─ registre tenant
   └─ routage vers cellules

Cellule A
   ├─ ingest
   ├─ safety state
   └─ telemetry tenants 1–150

Cellule B
   └─ tenants 151–300

Cellule sensible
   └─ cabinets / santé / données à risque
```

Le cockpit global ne stocke que les résumés nécessaires. Les logs bruts restent dans leur cellule.

### Quand partitionner

Pas uniquement à un nombre fixe de clients. Déclencheurs :

* un tenant dépasse 10 % du volume ;
* capacité d’ingestion durablement supérieure à 60–70 % ;
* temps de restauration supérieur au RTO ;
* volume de stockage hors budget ;
* p95 des requêtes trop élevé ;
* cardinalité excessive ;
* nécessité contractuelle ou sectorielle d’isoler un client ;
* blast radius jugé trop grand.

Comme garde-fou initial, je plafonnerais une cellule à **100–200 tenants** avant retour d’expérience. Un client très sensible peut justifier une cellule dédiée dès le premier jour.

### RETIRER : les labels à cardinalité incontrôlée

Ne pas indexer comme labels Loki :

```text
trace_id
task_id
invoice_id
user_id
URL complète
nom de fichier
message d’erreur libre
```

La documentation Loki déconseille les labels à valeurs non bornées comme les trace IDs ou order IDs, car ils font exploser le nombre de streams, l’index et le coût. ([Grafana Labs][6])

Utiliser comme labels :

```text
tenant
cell
environment
service
severity
event_family
```

Le reste va dans les métadonnées structurées ou le corps.

---

# Les nouvelles lois QG que j’ajouterais

| Loi                        | Verte quand                                                                         |
| -------------------------- | ----------------------------------------------------------------------------------- |
| `LAW-QG-SAFETY-CORE`       | la console et le noyau de sûreté sont séparés et testés indépendamment              |
| `LAW-QG-UPLINK-ONLY`       | aucun credential QG ne permet une entrée ou une commande sur un VPS                 |
| `LAW-QG-INGEST-IDENTITY`   | tenant et deployment sont dérivés du certificat, jamais du payload                  |
| `LAW-QG-SEQUENCE`          | doublons, trous, replay et epochs sont détectés                                     |
| `LAW-QG-SCHEMA-COMPAT`     | toutes les versions actives de la flotte passent les tests de contrat               |
| `LAW-QG-POLICY-COMPAT`     | les scores comparés utilisent le même policy bundle ou sont marqués non comparables |
| `LAW-QG-TELEMETRY-LOSS`    | toute perte ou saturation est mesurée et visible                                    |
| `LAW-QG-DATA-MINIMIZATION` | aucun champ hors allowlist ne quitte un VPS                                         |
| `LAW-QG-TENANT-ISOLATION`  | tests croisés ingestion/requête/export/cache entièrement verts                      |
| `LAW-QG-WITNESS`           | témoin indépendant frais et capable d’alerter seul                                  |
| `LAW-QG-EVIDENCE-ANCHOR`   | checkpoints externes continus et vérifiables                                        |
| `LAW-QG-ALERT-DELIVERY`    | alertes critiques livrées, acquittées et escaladées selon le SLO                    |
| `LAW-QG-RESTORE`           | reconstruction complète testée avec replay et curseurs                              |
| `LAW-QG-OPERATOR-COVERAGE` | un répondant disponible existe et le plan de relève est testé                       |
| `LAW-QG-COST-BUDGET`       | ingestion, rétention et coût sont bornés par tenant et cellule                      |

---

# Réponses directes aux sept attaques

## 1. Extend ou redo ?

**Ni extension libre, ni redo total.**

* Étendre la console, ses vues et son RBAC.
* Reconstruire un safety core minimal.
* Migrer par strangulation et shadow mode.
* Ne pas partager la base entre ancien QG et safety core.

## 2. Heartbeat + outside-in + log store suffisent-ils ?

**Non.**

Il manque :

* travail attendu ;
* santé de la télémétrie ;
* machine d’incident ;
* corrélation des causes communes ;
* délais de détection ;
* escalade ;
* test de livraison des alertes ;
* gestion du mode maintenance ;
* preuve de restauration ;
* opérateur réellement disponible.

Le log store aide au diagnostic. Il ne doit pas être une condition nécessaire au déclenchement du filet.

## 3. Quels trous dans le contrat montant ?

Les principaux :

* exactly-once mal posé ;
* absence de `producer_epoch` ;
* séquence globale au lieu de séquence par stream ;
* ACK non défini ;
* pas de protocole de trous ;
* pas de voie backfill ;
* pas de priorité ;
* pas de quotas ;
* pas de politique de perte ;
* tenant non lié au certificat ;
* évolution de policy bundle non traitée ;
* ré-enrôlement et offboarding non traités ;
* redactor fail-open possible ;
* pas de séparation safety events / telemetry.

## 4. Qui garde le gardien ?

* témoin dans un autre domaine de panne ;
* canal d’alerte indépendant ;
* QG sans accès descendant ;
* checkpoints externes ;
* console séparée du calcul ;
* règles versionnées ;
* sauvegardes immuables ;
* tests de compromission ;
* états `disputed` et `suspected_compromise`.

Une réplica seule ne suffit pas : elle réplique aussi les mensonges et les erreurs.

## 5. Le périmètre de données est-il juste ?

**Oui pour l’interdiction du CA et de la trésorerie. Non pour les artefacts libres.**

À centraliser :

* heartbeat minimal ;
* conformité versionnée ;
* événements machine structurés ;
* erreurs par code et empreinte ;
* checkpoints de preuve.

À laisser local par défaut :

* daybooks complets ;
* stderr brut ;
* prompts et réponses ;
* contenus emails ;
* noms de dossiers ;
* logs applicatifs libres ;
* traces contenant les arguments d’outils.

## 6. Que se passe-t-il à 100 ou 1 000 clients ?

* Le heartbeat reste facile.
* Les logs, traces, rétention et cardinalité deviennent dominants.
* Le QG doit adopter des cellules.
* Le cockpit global ne doit pas faire de requêtes brutes inter-tenants.
* Les quotas et budgets doivent exister avant, pas après la première facture de stockage épique.
* À 1 000 clients, la capacité humaine de réponse devient plus critique encore que la capacité CPU.

## 7. Le plus grand angle mort ?

**L’opérateur solo.**

Le QG suppose qu’une détection produit mécaniquement une action. C’est faux. Sans relève, escalade, accès de récupération, runbooks transmissibles et couverture explicite, le QG n’est pas un filet de sécurité : c’est un excellent observateur sans bras.

---

# Gate de production que je signerais

Je donnerais un **GO production QG** uniquement lorsque ces dix conditions sont prouvées :

1. Le QG existant est devenu une console ; le safety core fonctionne sans lui.
2. Aucun canal descendant ni credential flotte n’existe au QG.
3. Le flux est un push sortant mTLS avec identité tenant dérivée du certificat.
4. Les doublons, trous, replays, changements d’epoch et versions hétérogènes sont testés.
5. Un heartbeat vert ne suffit jamais à produire un état flotte vert.
6. Le témoin extérieur peut détecter la perte du QG et alerter directement.
7. Les logs bruts, prompts et daybooks sont désactivés par défaut au centre.
8. Les tests de fuite inter-tenant sont verts sur ingestion, stockage, requêtes, caches et exports.
9. Une restauration complète du QG a été exécutée avec reprise des curseurs.
10. Un incident a été simulé avec l’opérateur principal indisponible et réellement pris en charge.

## Décision finale

> **NO-GO pour “étendre le QG organique jusqu’à ce qu’il devienne le gardien”.**

> **GO conditionnel pour “conserver le cockpit existant autour d’un safety core neuf, ascendant uniquement, observé par un témoin indépendant”.**

Le QG V4 est une bonne direction, mais sa sûreté ne viendra pas de l’ajout de plus de dashboards ou de plus de logs. Elle viendra de frontières plus petites, de garanties explicites, d’un refus du canal descendant, d’une preuve extérieure et d’une organisation capable de répondre lorsque la machine crie.

### Documents de base analysés

* **Brief QG round 3**, pour la décision extend, les rôles evidence/safety/observabilité, le contrat montant et les sept angles d’attaque.  
* **Master Hub V4**, pour le placement de l’observabilité au QG, le caractère latéral du Hub et le workstream QG.  
* **CDC technique Hub V4**, pour l’outside-in, le dead-man’s-switch, les logs mutualisés et les lois existantes.  
* **Décisions finales V4**, notamment T6 sur l’observabilité mutualisée et T8 sur le CDC propre du QG. 

[1]: https://opentelemetry.io/docs/collector/resiliency/?utm_source=chatgpt.com "Resiliency"
[2]: https://grafana.com/docs/loki/latest/operations/multi-tenancy/?utm_source=chatgpt.com "Manage tenant isolation | Grafana Loki documentation"
[3]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html?utm_source=chatgpt.com "Locking objects with Object Lock"
[4]: https://opentelemetry.io/docs/collector/deploy/other/agent-to-gateway/?utm_source=chatgpt.com "Agent-to-gateway deployment pattern"
[5]: https://www.cnil.fr/fr/la-cnil-publie-une-recommandation-relative-aux-mesures-de-journalisation?utm_source=chatgpt.com "La CNIL publie une recommandation relative aux mesures ..."
[6]: https://grafana.com/docs/loki/latest/get-started/labels/cardinality/?utm_source=chatgpt.com "Cardinality | Grafana Loki documentation"
