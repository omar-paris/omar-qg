# Brief Claude Design — QG V1 (cockpit inter-VPS + surface de sécurité)

But : concevoir le **front du QG V1** — le cockpit de l'opérateur solo (« voir tous mes clients ») **+**
la surface du **filet de sécurité de la flotte**. On **part de l'existant (QG V0.9.3)** : on **étend le
cockpit** et on **ajoute la surface du safety-core neuf**.

## À lire (repo `omar-hub`)
- **`docs/HUB-CDC-QG.md`** — le rôle du QG en V4 + le QG V1 (cockpit étendu + safety-core neuf isolé).
- **`docs/consultants/round3/SYNTHESE-3.md`** — le verdict consultants (séparer safety-core / cockpit,
  vert dérivé multi-signal, dead-man's-switch tiers, qui-garde-le-gardien, gouvernance des logs).
- **`docs/HUB-FRONT-SPEC.md`** — **réutiliser le MÊME design system que le Hub** (`StatusTile`/`ActionCard`,
  prisme décision/état, honnêteté des états) pour la **cohérence** Hub↔QG.

## Ce qu'on attend
1. **Vue flotte** : tous les VPS/clients — conformité 4 couleurs, santé, heartbeat — en `StatusTile` par VPS ;
   **état `DISPUTED`** quand les signaux se contredisent (le vert est **dérivé multi-signal, jamais éditable**).
2. **Drill-down par client/VPS** : conformité (OmarTop), maturité, activité, incidents — via les composants du Hub.
3. **Surface safety-core** (le neuf) : statut **dead-man's-switch** (silence = alerte), **matrice de sondes
   outside-in**, **timeline d'incidents** (corrélation causes communes + anti-faux-positifs/flap-damping),
   escalade. + le **témoin externe du QG lui-même** (« qui garde le gardien »).
4. **Observabilité mutualisée** : logs/traces/séries-temps long terme (exceptions-only, pas un mur).
5. **Consommateurs** : l'opérateur (Alex) + les agents ; **RBAC** (les vues client filtrées existent déjà).
6. **Honnêteté & gouvernance** : données montantes = conformité/daybook/errors/heartbeat seulement (pas de
   CA/trésorerie) ; logs de clients sensibles = code/compteur au central, bruts **local-only**.

**Livrable** : composants **réutilisés du Hub** + composants propres au QG (grille flotte, timeline
d'incidents, matrice de sondes), même design system.
