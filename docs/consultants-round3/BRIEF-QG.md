# QG (cockpit inter-VPS) — Brief consultants (avocats du diable) — round 3, 12/07

Vous challengez **un composant précis** : le **QG**, le cockpit inter-VPS d'un système multi-agents où
chaque client a son propre VPS (« Hub » local). Vous avez déjà validé l'architecture Hub (V4) ; ici on
zoome sur le QG, devenu **critique**. Pas de consensus, pas de politesse. Cas concrets, priorisés.

## 1. Contexte (rappel V4)

Chaque VPS a un **Hub local** = plan latéral (control/observation/evidence), **jamais** le chemin
obligatoire du métier (les apps continuent si le Hub tombe). Un Hub **ne peut jamais se déclarer vert
seul**. Le **QG** est : (a) le **cockpit de l'opérateur solo** (« voir tous mes clients »), et (b) le
**filet de sécurité de la flotte**.

**Décision prise (à challenger)** : **ÉTENDRE** un QG **existant et mature** (RBAC + vues client filtrées,
sondes de santé, alertes, audit des boucles d'agents, agrégation de conformité graduée par VPS, front web
Tailnet-only) — **plutôt que le refaire**.

## 2. Le rôle du QG en V4

- **Evidence plane flotte** : reçoit les artefacts montants (ship-own) de chaque VPS — **uniquement
  conformité / journal quotidien / erreurs / heartbeat** au MVP (**PAS** de CA/trésorerie — donnée
  commerciale gardée locale).
- **Filet de sécurité (bloquant pour la 1re prod)** : **dead-man's-switch** (un VPS silencieux =
  alerte, pas « vert par défaut ») + **sondes outside-in** (test des endpoints depuis une 3e position,
  indépendant du Hub local) + **log store mutualisé**.
- **Observabilité mutualisée** (logs/traces/séries-temps long terme) **au QG**, pas par-VPS (les VPS
  n'ont qu'un collecteur léger, pour tenir sur une petite box).
- **Contrat montant** : chaque flux VPS→QG typé/signé/minimisé (`schema_version/deployment_id/tenant_id/
  sequence/payload_hash/data_classification/signature`, mTLS, anti-rejeu, accusé, reprise par séquence),
  **redaction par allowlist AU SHIP** (avant l'egress — un stderr d'un cabinet d'avocats peut contenir un
  nom de dossier client).
- **Sécurité** : le QG est une **nouvelle concentration inter-clients** → **observé depuis une 3e
  position** (« qui garde le gardien ? »), **PRA/réplication**, RBAC strict (une fuite inter-tenant est
  déjà arrivée).

## 3. Angles d'attaque demandés

1. **Extend vs redo** : étendre un QG **organique** (qui a grossi au fil du temps) est-il le bon choix
   quand il devient **safety-critical**, ou la criticité justifie-t-elle une **reconstruction propre** ?
   Où « étendre » va-t-il mordre (dette, couplage, tests) ?
2. **QG-minimum-viable** : heartbeat + outside-in + log store **suffisent-ils** comme filet bloquant ?
   Que manque-t-il (fenêtre de détection, faux positifs, corrélation, escalade) ?
3. **Le contrat montant** : trous ? ordre/exactly-once, backpressure, évolution de schéma sur une
   **flotte hétérogène** (VPS à versions différentes), reprise après longue coupure, quotas.
4. **« Qui garde le gardien ? »** : le QG est à la fois **safety-critical** ET un **SPOF inter-clients**.
   La 3e position + PRA suffisent-elles ? Que se passe-t-il si le QG **ment** (bug) ou est **compromis** ?
5. **Gouvernance des données** : « conformité/daybook/errors/heartbeat seulement » est-il le bon
   périmètre MVP ? Où fuit-on entre clients (surtout via les **logs shippés** d'un client sensible) ?
6. **Échelle** : N VPS qui heartbeatent + shippent leurs logs vers **un** QG — coût/charge/rétention à
   100, 1000 clients ? Quand le QG lui-même doit-il se partitionner/répliquer ?
7. **Le plus grand angle mort** que personne n'a vu sur le QG.

## 4. Format
Pour chaque trou : **AJOUTER / MODIFIER / RETIRER** + **pourquoi** + un **cas concret**. Priorisez le pire.
Déposez votre retour ; on le confrontera au CDC du QG.
