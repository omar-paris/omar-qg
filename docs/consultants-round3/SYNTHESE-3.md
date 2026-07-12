# SYNTHÈSE round 3 — challenge du QG (cockpit inter-VPS)

Synthèse des 4 retours consultants (12/07) confrontés à `HUB-CDC-QG.md` (décision **ÉTENDRE `omar-qg`**)
et au `BRIEF-QG.md`. Consultants : **CG** = ChatGPT-3, **CL** = Claude-3, **GM** = Gemini-3, **LC** = LeChat-3.

Convention : un point est **NOUVEAU** s'il n'est pas déjà couvert par le CDC du QG (qui contient déjà :
extend sur branche, agrégation conformité, RBAC/vues client, health_probe→outside-in, dead-man's-switch VPS,
log store classe B, contrat montant typé/signé/mTLS/anti-rejeu/séquence/accusé/backpressure, redaction
allowlist au ship, 3e position, PRA/réplication D13, U7 pas de CA/trésorerie, lois LAW-HUB-OUTSIDE-IN /
LAW-QG-CONTRACT / LAW-QG-REDACT / LAW-QG-DR).

---

## 0. VERDICT sur le QG

### Par consultant

| Consultant | Extend vs redo | QG-minimum-viable suffisant ? | Verdict de fond |
|---|---|---|---|
| **CG (ChatGPT)** | **Ni extend libre, ni redo total.** Étendre la **console/RBAC/vues** ; **reconstruire à côté un safety-core NEUF**, base séparée, migration par **strangler + shadow mode** (2 évaluateurs en parallèle puis on supprime l'ancien — jamais deux vérités actives). | **NON.** Manque : travail attendu, santé télémétrie, machine d'incident, corrélation, escalade, test de livraison d'alerte, preuve de restauration, opérateur réellement disponible. | **NO-GO** pour « étendre le QG organique jusqu'à ce qu'il devienne le gardien ». **GO conditionnel** (10 conditions) pour « cockpit existant autour d'un safety-core neuf, ascendant-only, témoin indépendant ». Beaucoup à changer. |
| **CL (Claude)** | **Faux binaire → SÉPARER.** Étendre le **cockpit** (organique, peut tomber 1h) ; **construire neuf/minimal/isolé, ailleurs**, le **watchdog** safety-critical. Coupler la fonction la plus critique au code le plus instable est l'erreur. | **NON.** Détecte mais ne rattrape rien : manque 1re réponse auto, escalade multi-canal SLA, anti-faux-positifs (flap-damping, multi-signal), heartbeat à assertions. | Priorité absolue = **dead-man's-switch tiers EXTERNE pour le QG lui-même** (sinon tout l'argument sécurité est circulaire, **bloquant**). Beaucoup à changer. |
| **GM (Gemini)** | **MODIFIER l'extend organique.** Le thread-model / patterns DB de l'ancien QG sont incompatibles avec le safety-critical. **Sanctuariser l'ancien code pour le monitoring**, **bâtir un micro-noyau de contrôle (control plane) étanche à côté**. | **NON.** Manque throttling dynamique + circuit-breaker d'ingestion (tempêtes de logs d'un VPS en boucle saturent le log store mutualisé). | Convergent avec CG/CL : isolation stricte du noyau de contrôle. Beaucoup à changer. |
| **LC (LeChat)** | **Étendre (avec corrections).** Le plus « contents » : garde la décision extend, ne pousse pas la séparation noyau/cockpit ; ajoute redondance, logs signés, isolation, sharding. Rebuild seulement si dette trop lourde. | **NON.** Manque récupération auto, vérification croisée (heartbeat+sondes+logs), intégrité des logs. | Extend confirmé **à condition** de corriger SPOF (QG redondant), isoler/chiffrer les logs, vérif croisée. Roadmap en 4 phases. |

### Verdict global

**Extend CONFIRMÉ mais REQUALIFIÉ — et NON, on n'est pas « contents ».** Convergence forte **3 contre 1**
(CG + CL + GM) : le CDC dit « étendre `omar-qg` » sans distinguer les deux natures du QG ; les trois exigent
de **SÉPARER un noyau de sûreté / watchdog NEUF, minimal, isolé et testable** du **cockpit organique** (qu'on
étend, lui). Ce n'est pas du redo total, ni l'extend simple écrit au CDC : c'est un **extend + build-clean à
côté**. LC est le seul à valider l'extend quasi tel quel. **Les 4 jugent le QG-minimum-viable (heartbeat +
outside-in + log store) INSUFFISANT** comme filet bloquant. Donc : signal clair de **révision structurelle
du CDC du QG**, pas d'un simple durcissement.

---

## 1. Extraction — points NOUVEAUX (par thème)

### A. Extend vs redo / architecture

- **Q1 (CG, CL, GM)** — **Séparer un noyau de sûreté NEUF du cockpit organique.** Extend seulement la console
  (vues, RBAC, front) ; safety-core / watchdog reconstruit à part (base propre, migrations propres, API propre).
  La maturité fonctionnelle ≠ maturité safety (frontières de confiance, déterminisme, modes de panne documentés,
  tests d'isolation, fonctionnement sans le front). *NOUVEAU* (le CDC dit « étendre sur branche sans casser »).
- **Q2 (CG)** — **Migration par strangler + shadow mode** : geler la logique safety dans l'ancien QG, écrire des
  tests de caractérisation, faire tourner ancien et nouveau évaluateurs en parallèle, comparer alertes
  manquées/faux positifs/divergences, puis supprimer l'ancien calcul. **Jamais deux vérités de sûreté actives.** *NOUVEAU*
- **Q3 (CG)** — **La console ne lit jamais la base du safety-core directement**, uniquement via API (« elle ne lit
  pas les tables selon son humeur »). *NOUVEAU*
- **Q4 (GM)** — **Incompatibilité DB/thread-model concrète** : une requête lourde du front sur la SQLite mutualisée
  bloque le thread d'ingestion → heartbeats de N VPS suspendus → **fausses alertes globales de panne**. Argument
  technique direct pour la séparation. *NOUVEAU*
- **Q5 (CL)** — **Le QG a déjà fui inter-tenant une fois** (admis au brief) : en faire la concentration
  safety-critical = doubler la mise sur le composant au pire historique. Le chemin evidence/sécurité a besoin
  d'un modèle de tenancy **propre et audité à part**, pas du RBAC organique. *NOUVEAU (angle historique)*

### B. QG-minimum-viable (le filet)

- **Q6 (CG, CL, LC)** — **heartbeat + outside-in + log store ne suffisent pas.** Ces 3 signaux prouvent seulement
  qu'un process émet / qu'un endpoint répond / qu'une trace existe — pas que le système fait encore son travail utile. *NOUVEAU (le CDC les pose comme suffisants pour le MVP)*
- **Q7 (CG)** — **Ajouter le signal « travail attendu »** : dernier backup, dernier contrôle de conformité,
  dernier cycle agent terminé, âge de l'outbox, dernier test de canal. (Cas : `/ready`=200, Loki reçoit, mais
  backup arrêté 6 j, token facturation expiré, outbox qui gonfle → joignable mais opérationnellement cassé.) *NOUVEAU*
- **Q8 (CG)** — **Ajouter le signal « santé de la chaîne de télémétrie »** : dernière séquence acceptée, trous,
  files pleines, événements rejetés, données perdues (`telemetry_loss`). *NOUVEAU*
- **Q9 (CG, CL)** — **État DISPUTED** : si `local=vert` mais `outside_in=rouge` → **jamais vert**. La
  **contradiction entre sources est le meilleur signal**, de sévérité supérieure à chacune seule ; le CDC a les
  deux sources mais ne les croise pas. *NOUVEAU*
- **Q10 (CG)** — **Énumération d'états flotte** : healthy / degraded / silent / isolated / stale / disputed /
  unknown / maintenance / suspected_compromise. *NOUVEAU*
- **Q11 (CG)** — **Vraie machine d'incident** : pending→firing→acknowledged→investigating→mitigated→resolved,
  avec hystérésis, délais `for`, déduplication, regroupement, inhibition, fenêtres de maintenance, escalade,
  lien runbook, fermeture auto seulement sur preuve de retour. *NOUVEAU*
- **Q12 (CG, CL)** — **Corrélation des causes communes** : une panne Tailnet = 1 incident « connectivité »
  + 500 impacts, pas 500 alertes. *NOUVEAU*
- **Q13 (CL, LC)** — **1re réponse automatique / self-heal** (tentative de restart/heal avant d'alerter, script
  Ansible) : un filet qui détecte sans agir n'est qu'une façon bruyante d'apprendre l'échec. *NOUVEAU*
- **Q14 (CL)** — **Escalade multi-canal à paliers avec SLA** (Telegram→SMS→appel), pas « une alerte » : sans
  relève, la latence détection→action reste de plusieurs heures pour un solo. *NOUVEAU*
- **Q15 (CL, LC)** — **Les faux positifs tueront le filet avant tout bug** : N VPS artisans (box Hetzner, Tailnet
  capricieux) = flot de fausses alertes « down » → le solo mute le canal en une semaine → rate la vraie. Ajouter
  **confirmation multi-signal + flap-damping + seuils de tolérance + heures calmes**. *NOUVEAU*
- **Q16 (GM)** — **Throttling dynamique + circuit-breaker d'ingestion au récepteur** : un seul VPS en boucle
  d'erreurs (cf. 558 crashs passés) shippe des Go/s et sature disque/CPU du QG, aveuglant tous les autres. *NOUVEAU*

### C. Contrat montant

- **Q17 (CG)** — **Ne pas promettre « exactly-once ».** `sequence + accusé + anti-rejeu` ≠ exactly-once. Garanties
  **par flux** : heartbeat = dernier état gagne / conformité = at-least-once + dédup + détection de trous /
  preuve = append-only + checkpoint / logs = best-effort explicite. Le Collector OTel ne doit pas être le
  transport de preuve. *NOUVEAU*
- **Q18 (CG)** — **Ajouter `producer_epoch` (ou boot_id) ; séquence portée par `(deployment_id, producer_epoch,
  stream_id)`, pas un compteur global VPS.** Sans époque, après restauration/réinstall une séquence repart à zéro
  et le QG ne distingue plus doublon / ancien / nouvelle instance / replay / usurpation. *NOUVEAU*
- **Q19 (CG, LC)** — **`event_id` pour idempotence/déduplication** (clé unique par événement). ACK reçu après
  **persistance durable**, avec rapport `accepted_through / gaps / duplicates / quarantined / retry_after`. *NOUVEAU (le CDC a l'accusé mais pas le contrat d'idempotence ni le rapport de trous)*
- **Q20 (GM)** — **Head-of-line blocking sur flotte hétérogène** : un payload `oa.event/v2` rejeté par un QG plus
  ancien est rejoué indéfiniment et **bloque tout le flux ultérieur, y compris les rapports critiques de sécurité**
  (et le dead-man's-switch s'active à tort car le heartbeat réseau passe encore). *NOUVEAU, majeur*
- **Q21 (CG)** — **Voie backfill séparée** : le retour massif d'historique après longue coupure ne doit pas
  déclencher d'alertes rétroactives. *NOUVEAU*
- **Q22 (CG, GM)** — **Classes de priorité + politique de perte** (P0 heartbeat/révocation/incident/checkpoint …
  P4 logs debug) : en saturation, échantillonner P4, garder P0/P1, émettre `telemetry_loss`, **ne jamais remplir
  le disque du VPS pour sauver des logs**. *NOUVEAU*
- **Q23 (LC)** — Buffer de réordonnancement + horodatage NTP strict pour l'ordre des événements. *NOUVEAU (partiel)*

### D. Qui garde le gardien / SPOF

- **Q24 (CL, CG, GM)** — **Dead-man's-switch tiers EXTERNE pour le QG lui-même**, opéré par un service
  **hors de ton infra** (healthchecks-like, autre provider/région) que le QG doit pinguer ; son silence alerte par
  un canal indépendant. **Seul moyen de terminer la régression « qui garde le gardien ».** CL le pose **bloquant
  et n°1**. *NOUVEAU (le CDC a « 3e position » mais sous-spécifiée / potentiellement dans la même infra)*
- **Q25 (CG, CL)** — **Le témoin doit être dans un autre domaine de panne** : pas le même provider / compte cloud /
  Tailnet / DNS / IdP / CI-CD / credentials admin / code de calcul de santé. (Cas : une ACL Tailnet coupe d'un coup
  sondes, accès opérateur, alertes ET la « 3e position » membre du même Tailnet.) *NOUVEAU*
- **Q26 (GM, CL)** — **Le témoin fait des canaries end-to-end** : simuler un VPS fictif défaillant et vérifier que
  le QG lève l'alerte attendue dans le délai — détecter le **freeze sémantique** (read-models figés alors que
  `/health`=200), pas seulement « QG en ligne ». *NOUVEAU*
- **Q27 (CL)** — **Le prober outside-in doit tourner hors du process principal du QG** (autre région), sinon un
  « QG figé » fige aussi le prober. *NOUVEAU*
- **Q28 (CG, LC)** — **Canal d'alerte indépendant du QG** : le QG ne peut pas être chargé d'émettre l'unique alerte
  disant que le QG est mort. Canal principal + secours indépendant + test synthétique de livraison + attente
  d'accusé + escalade si non acquitté. *NOUVEAU*
- **Q29 (CG)** — **Rendre le mensonge du QG détectable** : le vert doit être **dérivé, jamais éditable**. Chaque
  état porte `decision_id / rule_bundle_version / input_event_ids / evidence_hashes / evaluator_version`. La console
  ne peut pas écrire `status=green` ; elle n'émet que des événements (`incident.acknowledged`, `maintenance.started`). *NOUVEAU*
- **Q30 (CG)** — **Checkpoints externes ancrés** : le QG hash périodiquement ses événements de preuve, signe,
  envoie dans un stockage **WORM/Object-Lock indépendant** ; le témoin vérifie la continuité. Un attaquant qui
  compromet le QG ne peut pas réconcilier sa nouvelle histoire avec les checkpoints ancrés hors de son domaine. *NOUVEAU*
- **Q31 (CG, CL)** — **Signature = origine, pas honnêteté** : un VPS compromis détient des clés légitimes et signe
  un heartbeat « vert » parfaitement valide (ou shippe de la conformité falsifiée « tout vert » en exfiltrant).
  → conserver la **pluralité des sources** (local + outside-in + travail attendu + témoin). *NOUVEAU*
- **Q32 (CG, LC)** — **Le PRA doit couvrir la corruption logique et la compromission**, pas que la panne matérielle :
  une réplica réplique aussi le `DELETE`, la migration destructive, le ransomware, la donnée mensongère. Ajouter
  PITR, snapshots immuables, comptes/clés de backup séparés, clean-room recovery, restauration testée avec replay
  et reprise des curseurs, **exercice de compromission**. *NOUVEAU (le CDC a PRA/réplication D13, pas ces modes)*

### E. Gouvernance des données

- **Q33 (CG, CL, GM)** — **Retirer daybook / stderr brut / prompts LLM / corps HTTP / noms de dossiers du plan de
  preuve central par défaut.** Le daybook est une **narration** (incomplet, optimiste, halluciné, manipulable) —
  utile au cockpit, jamais une vérité de conformité. Un prompt/stderr peut être **plus sensible qu'un montant** :
  la contradiction « pas de CA mais on centralise logs/observabilité » doit être résolue **par schéma, pas par
  bonne intention**. *NOUVEAU (le CDC place daybook/errors dans l'evidence plane)*
- **Q34 (CG)** — **Séparer les plans** : Evidence (événements machine signés/verdicts/checkpoints) / Opérationnel
  (erreurs structurées) / Narratif (daybook) / Forensic (logs bruts, stderr) / LLM (prompts, réponses, tool calls). *NOUVEAU*
- **Q35 (CG, CL)** — **Remplacer « error » par un schéma structuré** : `error_code / component / severity /
  stack_fingerprint / trace_id / first_seen / last_seen / occurrence_count / remediation_status`, extrait rédigé
  facultatif. Le log brut reste local ; le QG reçoit l'empreinte + métadonnées. *NOUVEAU*
- **Q36 (CL, GM)** — **Pour les clients sensibles (avocat JAB), ne PAS centraliser les logs du tout** :
  « centraliser les logs » peut être incompatible avec les obligations de confidentialité d'un cabinet, redaction
  ou pas. Log store **local** ; le QG ne reçoit qu'un error = code/compteur. *NOUVEAU, tranchant*
- **Q37 (CG, CL, GM)** — **Redaction fail-closed + défense en profondeur** (au ship ET à l'ingest ET au rendu) :
  schéma inconnu / redacteur qui plante / champ hors allowlist / classification absente → **quarantaine**, jamais
  « au mieux ». *NOUVEAU (le CDC a la redaction au ship, pas la profondeur ni le fail-closed)*
- **Q38 (CL)** — **Traiter tout flux montant comme `untrusted_content` MÊME signé** : un log rendu brut dans le
  cockpit = log-injection / stored-XSS ; c'est `LAW-AGENT-UNTRUSTED-INPUT` non appliqué à l'ingestion QG.
  Sanitization, pas de HTML brut, quarantaine d'un tenant devenu incohérent. *NOUVEAU*
- **Q39 (CG)** — **Lier le tenant à l'identité mTLS, pas au champ `tenant_id` du payload** : authentifier le
  certificat → dériver `tenant_id`/`deployment_id` côté serveur → comparer au payload → rejeter toute divergence.
  Un cert par VPS, rotation/révocation, aucun choix de tenant Loki (X-Scope-OrgID) par le sender. *NOUVEAU (le CDC met tenant_id dans le payload signé)*
- **Q40 (CG, GM, LC)** — **Isolation tenant dans le stockage, pas seulement le front/RBAC** : index/stockage séparé
  par tenant sensible, quotas et rétention par tenant, clés de chiffrement séparées, requêtes multi-tenants brutes
  désactivées, **tests négatifs sur ingestion/requête/export/cache**, accès support Just-in-Time. (Cas : export
  reçoit un `tenant_id` d'une query string oubliée → CSV du client B alors que le front est vert.) *NOUVEAU*
- **Q41 (CG)** — **Manifeste de politique par flux** (yaml : `fields / retention / pii_allowed / destination`) +
  **rétention par finalité/classe** (CNIL 6 mois–1 an), pas « tout garder 1 an ». *NOUVEAU*
- **Q42 (CG)** — **La conformité flotte ne peut pas être un score moyen** : `100 % sur 10 lois v1` n'est pas
  comparable à `85 % sur 20 lois v3`. Ajouter `policy_bundle_version / law_version / evaluator_hash / coverage`,
  séparer `pass_rate / coverage_rate / freshness_rate`, comparer **par cohorte de policy bundle**, afficher
  « 100 % sur 50 % de couverture — non comparable ». *NOUVEAU, important*
- **Q43 (GM)** — **Ledger de preuve hash-chaîné PAR CLIENT, pas global** : un chaînage global rend l'effacement
  RGPD d'un client destructeur (casse la chaîne de tous les autres). Un fichier de preuves chaîné distinct par
  tenant. *NOUVEAU*
- **Q44 (LC)** — Logs signés par client (signature numérique). *NOUVEAU (recoupe Q29/Q43)*

### F. Échelle

- **Q45 (CG, CL)** — **Ce n'est pas le heartbeat qui casse, ce sont les logs et l'attention.** Volume : ~432 Go/jour
  bruts à 1000 VPS (hyp. 5 Ko/s) ; le heartbeat reste ~1,5 Go/jour. Et le **vrai mur arrive vers ~30 clients** :
  le rapport signal/bruit — concevoir le cockpit **exceptions-only** (« tout vert = une ligne »). *NOUVEAU*
- **Q46 (CG, GM, LC)** — **« Un QG » doit devenir logique** : Global Fleet Directory (statuts minimisés) + cellules
  par plage de tenants + cellule dédiée pour clients sensibles ; le cockpit global ne fait **jamais** de requête
  brute inter-tenants. *NOUVEAU*
- **Q47 (CG)** — **Déclencheurs de partitionnement** (pas un nombre fixe) : un tenant >10 % du volume, ingestion
  >60–70 %, RTO dépassé, coût hors budget, p95 trop haut, cardinalité, exigence contractuelle, blast radius. Plafond
  initial ~100–200 tenants/cellule ; client très sensible = cellule dédiée dès J1. *NOUVEAU*
- **Q48 (CL)** — **Le watchdog ne se partitionne JAMAIS par client** (il lui faut la vue globale pour voir le
  silence corrélé) ; seul le cockpit / log store shard. **Silence corrélé (10 VPS d'un coup) = suspecter le
  gardien, pas les gardés** — distinguer « la flotte est down (ta faute) » de « ces VPS-là sont down ». *NOUVEAU, nuance le sharding*
- **Q49 (CG)** — **Cardinalité Loki** : ne pas indexer comme labels `trace_id / task_id / invoice_id / user_id /
  URL / nom de fichier / message libre` (explosion des streams/index/coût) ; labels bornés seulement
  (`tenant / cell / service / severity / event_family`). *NOUVEAU*
- **Q50 (CG)** — **Budgets de coût bornés par tenant et par cellule AVANT la première facture** (`LAW-QG-COST-BUDGET`). *NOUVEAU*
- **Q51 (LC)** — Archivage automatique (logs >30 j → stockage froid), sondes mutualisées (1 pour N), fréquence
  heartbeat réduite. *NOUVEAU (partiel, options coût)*

### G. Autre / angles morts

- **Q52 (CG, CL)** — **Continuité de l'opérateur humain — « le plus grand angle mort » (CG déclaré).** Le QG suppose
  qu'une détection produit mécaniquement une action ; faux pour un solo. Ajouter : répondant secondaire / prestataire
  de secours, rôle break-glass borné, accès de récupération sous séquestre, procédure d'escalade + délai d'acquittement,
  alerte directe au client pour certains incidents prolongés, runbooks exécutables par un tiers, test périodique
  « opérateur principal indisponible », heartbeat organisationnel de l'astreinte. (Cas : 03h10 disque à 98 %, alerte
  sur le téléphone éteint, PostgreSQL s'arrête à 05h, client découvre seul à 08h30 — techniquement le QG a
  fonctionné, le filet n'existait pas.) *NOUVEAU*
- **Q53 (CG, CL)** — **Retirer tout canal descendant du MVP** : le QG ne doit avoir **aucun** pull / SSH / scan /
  push de commande / credential d'agent global flotte — **push sortant mTLS uniquement**. Un QG qui peut entrer sur
  les VPS devient un pivot inter-clients (sa compromission = compromission de flotte). **Contradiction documentaire
  signalée** : d'autres passages V4 décrivent encore `outbox → pull côté Omar` — à trancher. Le QG reste superviseur,
  pas le bus obligatoire que la V4 a retiré du Hub. *NOUVEAU / lève une incohérence*
- **Q54 (CG)** — **Clarifier « bloquant »** : bloquant comme **gate de mise en prod** = oui ; bloquant dans le
  **chemin métier quotidien** = non ; un éventuel blocage d'action locale R4/R5 vit dans le **Hub local** (politique
  locale signée), pas dans un appel synchrone au QG. *NOUVEAU (précision)*
- **Q55 (CG)** — **Cycle de vie explicite du VPS** : provisioning / active / maintenance / isolated /
  suspected_compromise / suspended / offboarding / retired ; gérer inscription, renouvellement de cert,
  reconstruction du même VPS, changement d'IP/hébergeur, restauration ancienne, révocation, offboarding, fin de
  rétention. (Cas : VPS reconstruit d'un backup de 3 semaines, même `deployment_id`, séquence revenue à 400 → confondu
  avec un rejeu ou fusionné à tort.) *NOUVEAU*
- **Q56 (CG)** — **Batterie de tests de panne adverses** (22 scénarios : heartbeat dupliqué, trou de séquence, ACK
  perdu, VPS offline 7 j, backfill massif, horloge en avance, cert révoqué, usurpation de tenant, schémas v1/v2/v4
  simultanés, QG indisponible 12 h, redactor qui plante, secret canari, vague ×100, opérateur indisponible, QG
  compromis simulé, restauration en env propre…), chacun avec signal/état/alerte/délai/perte/preuve attendus. *NOUVEAU*
- **Q57 (CG, CL)** — **Mention « agrégation commerciale » ailleurs dans la V4** contredit « pas de CA/trésorerie »
  au MVP → retirer du référentiel courant ou classer explicitement en évolution future opt-in. *NOUVEAU / lève une incohérence*
- **Q58 (CG)** — **Nouvelles lois QG** proposées : `LAW-QG-SAFETY-CORE`, `LAW-QG-UPLINK-ONLY`,
  `LAW-QG-INGEST-IDENTITY`, `LAW-QG-SEQUENCE`, `LAW-QG-SCHEMA-COMPAT`, `LAW-QG-POLICY-COMPAT`,
  `LAW-QG-TELEMETRY-LOSS`, `LAW-QG-DATA-MINIMIZATION`, `LAW-QG-TENANT-ISOLATION`, `LAW-QG-WITNESS`,
  `LAW-QG-EVIDENCE-ANCHOR`, `LAW-QG-ALERT-DELIVERY`, `LAW-QG-RESTORE`, `LAW-QG-OPERATOR-COVERAGE`,
  `LAW-QG-COST-BUDGET`. *NOUVEAU*
- **Q59 (LC)** — QG redondant actif-actif (Raft/Paxos) comme réponse SPOF. *NOUVEAU (à confronter à Q24/Q32 : la
  redondance seule réplique aussi les mensonges — cf. CG « une réplica seule ne suffit pas »)*

---

## 2. LISTE 1 — à INTÉGRER (convergences fortes / peu contestables)

- **K1** — **Séparer un noyau de sûreté (safety-core / watchdog) NEUF, minimal, isolé, du cockpit organique ;
  n'étendre que la console.** Migration par strangler + shadow mode, jamais deux vérités de sûreté actives, console
  qui lit le noyau via API seulement. *(Q1, Q2, Q3, Q4 — CG+CL+GM, 3/4)*
- **K2** — **Dead-man's-switch tiers EXTERNE pour le QG lui-même**, hors infra, autre domaine de panne (pas le même
  provider/Tailnet/DNS/IdP/CI/credentials), avec canal d'alerte indépendant + test de livraison + accusé + escalade.
  Termine « qui garde le gardien ». *(Q24, Q25, Q28 — CL bloquant, CG, GM)*
- **K3** — **Le vert est un état DÉRIVÉ multi-signal, jamais éditable ni mono-source** : croiser local + outside-in
  + travail attendu ; état **DISPUTED** sur contradiction ; la console n'émet que des événements, elle n'écrit pas
  `status=green`. *(Q6, Q9, Q29, Q31 — CG, CL, LC vérif croisée)*
- **K4** — **Ajouter les signaux « travail attendu » et « santé télémétrie »** (backup, conformité, cycle agent,
  âge outbox / dernière séquence, trous, files, pertes) — le heartbeat nu ne prouve pas le travail utile. *(Q7, Q8 — CG)*
- **K5** — **Machine d'incident complète + corrélation des causes communes + flap-damping/anti-faux-positifs** :
  hystérésis, dedup, regroupement, inhibition, fenêtres de maintenance, escalade, runbook ; une panne Tailnet =
  1 incident, pas 500. Sans ça, le solo mute le canal. *(Q11, Q12, Q15 — CG, CL, LC)*
- **K6** — **Contrat montant durci** : abandonner « exactly-once » (garanties par flux), ajouter `producer_epoch` +
  séquence par `(deployment_id, producer_epoch, stream_id)`, `event_id`/idempotence, ACK après persistance avec
  rapport gaps/duplicates/quarantined, voie backfill séparée, classes de priorité + `telemetry_loss`. *(Q17, Q18, Q19, Q21, Q22 — CG, LC, GM)*
- **K7** — **Tenant dérivé de l'identité mTLS (jamais du payload) + isolation tenant dans le stockage** (index/clés/
  quotas/rétention par tenant, requêtes brutes inter-tenants désactivées, tests négatifs ingestion/requête/export/
  cache). Leçon de la fuite JAB. *(Q39, Q40 — CG, GM, LC)*
- **K8** — **Séparer les 5 plans de données ; retirer daybook/stderr/prompts/corps du plan de preuve central ;
  remplacer « error » par un schéma structuré (code/fingerprint/compteur)** ; redaction **fail-closed** en défense
  en profondeur (ship+ingest+rendu) ; traiter tout flux montant comme **untrusted_content même signé**. *(Q33, Q34, Q35, Q37, Q38 — CG, CL, GM)*
- **K9** — **Circuit-breaker / throttling / quotas d'ingestion au récepteur + budgets de coût par tenant/cellule**,
  et « ne jamais remplir le disque du VPS pour sauver des logs ». *(Q16, Q22, Q50 — GM, CG)*
- **K10** — **Conformité flotte versionnée, jamais un score moyen** : cohortes de policy bundle, `coverage_rate` /
  `freshness_rate` séparés, « non comparable » affiché. *(Q42 — CG)*
- **K11** — **PRA élargi à la corruption logique et à la compromission** (PITR, snapshots immuables, comptes/clés
  backup séparés, clean-room recovery, replay + reprise des curseurs, exercice de compromission) + **checkpoints de
  preuve ancrés hors QG (WORM)** vérifiés par le témoin. *(Q30, Q32 — CG, LC)*
- **K12** — **Continuité de l'opérateur humain** : répondant secondaire, break-glass borné, accès de récupération
  sous séquestre, escalade + SLA d'acquittement, alerte client sur incident prolongé, runbooks transmissibles, test
  « opérateur indisponible », 1re réponse auto / self-heal. *(Q13, Q14, Q52 — CG, CL, LC)*
- **K13** — **Retirer tout canal descendant du MVP : push sortant mTLS uniquement, aucun credential QG→VPS.** *(Q53 — CG, CL)*
- **K14** — **Modèle logique cellulaire pour l'échelle** : Directory global minimisé + cellules par plage de tenants
  + cellule dédiée clients sensibles ; le watchdog garde la vue globale (ne shard pas) ; discipline de cardinalité
  Loki ; cockpit exceptions-only. *(Q45, Q46, Q47, Q48, Q49 — CG, CL, GM, LC)*
- **K15** — **Batterie de tests de panne adverses + cycle de vie explicite du VPS + jeu de lois QG dédié.** *(Q55, Q56, Q58 — CG)*

## 3. LISTE 2 — à TRANCHER (arbitrages / désaccords / coûts non triviaux)

- **V1** — **Ampleur de la séparation : extend simple (CDC actuel) vs cockpit-étendu + safety-core NEUF à côté
  (CG/CL/GM) vs extend + corrections (LC).** C'est le désaccord central 3-contre-1. Trancher le niveau d'ambition
  (et le coût) avant tout le reste. *(Q1–Q5, Q59)*
- **V2** — **Le dead-man's-switch tiers est-il hors infra chez un fournisseur externe (CL/CG) ?** Cela introduit une
  dépendance/fournisseur tiers et un secret hors de ton périmètre — vs une « 3e position » interne mais autre région.
  Bloquant selon CL : à trancher tôt. *(Q24, Q25, Q27)*
- **V3** — **Gouvernance des logs des clients sensibles (JAB avocat) : centraliser errors=code/compteur seulement,
  logs bruts local-only, daybook hors preuve — ou centraliser avec redaction ?** Décision produit + juridique
  (confidentialité cabinet), pas seulement technique. *(Q33, Q36, Q43, Q44)*
- **V4** — **« error » shippé = code/compteur (OK central) ou texte (local-only clients sensibles) ?** Formulation
  précise de la frontière du contrat. *(Q35, Q36)*
- **V5** — **Redondance active-active du QG (LC, Raft/Paxos) vs safety-core minimal + PRA/replay (CG).** CG avertit
  qu'une réplica réplique aussi les mensonges et erreurs ; arbitrer coût/complexité de la HA vs valeur réelle. *(Q59 vs Q32)*
- **V6** — **Contradictions documentaires à résoudre dans le référentiel V4** : (a) `outbox → pull côté Omar` vs
  « montant uniquement » ; (b) « agrégation commerciale » ailleurs vs « pas de CA/trésorerie » au MVP. *(Q53, Q57)*
- **V7** — **`tenant_id` dans le payload signé (CDC actuel) vs dérivé du certificat mTLS côté serveur (CG).**
  Change le contrat montant et le modèle d'enrôlement des certs. *(Q39)*
- **V8** — **Ledger de preuve par client vs global hash-chaîné**, pour concilier immuabilité et effacement RGPD. *(Q43)*
- **V9** — **Politique anti-faux-positifs vs réactivité** : seuils/flap-damping/heures calmes réduisent le bruit mais
  augmentent la fenêtre de détection — calibrer le compromis pour un solo. *(Q15)*
- **V10** — **Quand partitionner en cellules** : nombre fixe (LC ~500) vs déclencheurs multi-critères (CG 100–200 +
  triggers). *(Q46, Q47)*

---

*Synthèse produite le 12/07 à partir des 4 retours round 3 intégraux + `HUB-CDC-QG.md` + `BRIEF-QG.md`.*
