# OA Dev/Prod Governance v0 — QG comme boussole et garde-barrière

Date: 2026-07-08
Owner: H-Omar / QG OA
Statut: v0 contractuel, à transformer en checks QG + gates Athena
Portée: toutes les apps OA, AppOmar, QG, Hub, Catalogue, Landing, OmarTop, Lab, agents Hermes/Claude Code, et intégrations inter-VPS.

## 1. Décision CTO

Le QG devient le cockpit qui détermine les règles de développement et de production du système OA.

Cela ne veut pas dire que le QG code toutes les applications. Cela veut dire que le QG doit exposer et vérifier les contrats minimaux que chaque application doit respecter avant d'être considérée comme saine, homogène et déployable.

## 2. Problème actuel constaté

Les applications OA avancent encore trop souvent en silo:

- AppOmar peut intégrer une image ou une icône non canonique si aucun registre d'assets ne fait autorité.
- EduGame / Kids Academy peut avancer avec H-Aurel ou Claude Code sans consommer automatiquement les standards OA transverses.
- Les apps ont des styles, assets, manifestes et gates hétérogènes.
- Le Kanban, Athena, le registre agents, les rapports VPS et les manifestes ne sont pas encore reliés dans une vue conformité unique.
- Le QG montre des signaux, mais ne bloque pas encore assez explicitement les déploiements non conformes.

Conclusion: le problème n'est pas seulement visuel. C'est un problème de gouvernance applicative.

## 3. Rôle cible du QG

Le QG doit répondre pour chaque application:

1. Quelle est cette application ?
2. Où est son repo ?
3. Où est son live ?
4. Quel VPS la porte ?
5. Quels assets canoniques elle utilise ?
6. Quel design system / charte elle applique ?
7. Quels tests/gates ont été passés ?
8. Quel agent ou builder en est responsable ?
9. Quelle revue Athena autorise la mise en prod ?
10. Quelle non-conformité bloque le prochain déploiement ?

## 4. Contrat minimal obligatoire par application

Chaque app OA doit fournir ou être représentée par un manifeste `oa.app-manifest/v1` contenant au minimum:

```json
{
  "schema": "oa.app-manifest/v1",
  "id": "appomar",
  "name": "AppOmar",
  "surface": "business|family|internal|client",
  "repo": "https://github.com/...",
  "local_path": "/home/omar/...",
  "live_url": "https://...",
  "vps": "vps-omar|pantheos|jab|client",
  "owner_agent": "h-omar|h-aurel|...",
  "builder": "oa-builder|claude-code|human",
  "review_gate": "h-athena",
  "asset_profile": "oa-brand|kids-academy|client-brand|none",
  "design_profile": "oa-default|kids-academy|client-specific|none",
  "data_sensitivity": "public|internal|personal|child|secret-adjacent",
  "prod_policy": "main-only-athena-gated",
  "health_checks": [],
  "known_gaps": []
}
```

Aucune nouvelle app OA ne doit être considérée comme intégrée au système sans ce manifeste ou une entrée équivalente dans le registre QG.

## 5. Règles dev/prod non négociables

### 5.1 Développement

- Une branche par changement fonctionnel.
- Pas de build de branche dans le dossier live.
- Pas d'asset généré ou inventé si un asset canonique existe ou si Alex a demandé un asset précis.
- Toute app doit référencer son profil de design et son profil d'assets.
- Toute app famille/enfant doit appliquer les invariants Kids Academy si elle touche `alexgo.eu` ou Pantheos.

### 5.2 Revue

- OA-Builder construit et smoke-check.
- H-Athena détient la revue-gate à froid.
- H-Omar arbitre après lecture du verdict.
- Pas de `pass` ou `pass_with_nits`, pas de merge/release.
- `pass_with_nits` impose correction ou décision explicite avant release si le nit touche sécurité, prod, données, assets ou confusion utilisateur.

### 5.3 Production

- Prod depuis `main` uniquement.
- Déploiement live uniquement après merge.
- Smoke live obligatoire après déploiement.
- Le résultat doit être persisté dans Kanban avec preuves.
- Une route/API d'une PR ouverte visible en prod est un incident de séparation staging/prod.

## 6. Registre assets canonique

Le QG doit porter un registre d'assets `oa.asset-registry/v1`.

Types minimaux:

- `brand.logo`
- `brand.avatar`
- `brand.icon`
- `brand.mascot`
- `app.icon`
- `capability.icon`
- `illustration`
- `screenshot`

Champs minimaux:

```json
{
  "schema": "oa.asset-registry/v1",
  "id": "oa-lobster-icon",
  "label": "Icône homard OA",
  "type": "brand.mascot",
  "canonical_path": "/home/omar/...",
  "public_url": null,
  "sha256": "...",
  "allowed_for": ["landing", "appomar", "qg", "hub"],
  "status": "candidate|canonical|deprecated|unknown",
  "notes": "..."
}
```

Règle importante: si aucun asset homard canonique n'existe, on écrit `missing_canonical_asset`, on ne fabrique pas une fausse image pour faire semblant.

## 7. Design system / homogénéité

Chaque app doit déclarer un `design_profile`:

- `oa-default`: surfaces business Omar & Alex.
- `kids-academy`: surfaces famille/enfants Pantheos.
- `client-specific`: client OA avec charte dédiée.
- `internal-tool`: outil interne brut mais cohérent.
- `none`: non conforme, à corriger.

Le QG doit exposer les écarts:

- pas de charte;
- pas de tokens/couleurs;
- assets non canoniques;
- navigation incohérente;
- absence de manifest;
- absence de smoke live;
- absence de gate Athena;
- données sensibles ou enfants sans politique explicite.

## 8. Inter-VPS et agents

Le QG doit distinguer les domaines:

- VPS Omar / OA business: H-Omar, AppOmar, QG, Hub, Catalogue, Landing, OmarTop.
- Pantheos / famille: H-Aurel, Kids Academy, EduGame, `alexgo.eu`.
- JAB / client: Edilia et apps client.

Règle: les standards peuvent être transverses, mais les risques et gouvernances restent séparés.

H-Aurel ne doit pas être déconnecté des standards: il doit consommer un contrat QG public-safe, sans secrets ni données enfant brutes.

## 9. Cas AppOmar

AppOmar est une surface business critique. Pour elle:

- audit = chat coach, pas formulaire;
- assets Omar/homard doivent provenir du registre canonique;
- pas de faux homard généré si un asset réel existe;
- paiement/onboarding/offre doivent rester cohérents avec Catalogue et Landing;
- toute release doit être gate Athena.

Écart actuel à traiter: assets présents mais non centralisés; usage d'images non prouvé comme canonique.

## 10. Cas EduGame / H-Aurel

EduGame doit être une couche au-dessus de Kids Academy, pas une app libre hors standard.

Invariants:

- pas de terminal libre par défaut;
- pas de modification directe de `SOUL.md` par enfant;
- pas de publication externe sans validation parent;
- pause parent/enfant = compteur arrêté ET activité bloquée;
- pas de logs familiaux bruts dans les rapports H-Omar/QG;
- changelog public-safe obligatoire.

Écart actuel à traiter: le runbook existe, mais le contrat n'est pas encore relié au QG comme conformité transverse.

## 11. Prochaines pages QG nécessaires

1. `/conformite/` — score de conformité par application.
2. `/assets/` — registre des assets canoniques, candidats, manquants.
3. `/apps/` enrichi — manifestes, owners, VPS, live, gates, gaps.
4. `/standards/` — règles dev/prod, design profiles, data policies.
5. `/vps/` — fleet par domaine, rapports `oa.vps-report/v1`, statut inter-VPS.

## 12. Definition of Done du chantier QG gouvernance

- Un manifeste app existe pour chaque app centrale OA.
- Un registre assets existe et distingue réel/canonique/candidat/manquant.
- AppOmar et EduGame sont évaluées comme cas pilotes.
- Une page QG expose les non-conformités.
- Athena peut revoir le résultat à froid.
- Une carte Kanban porte chaque action exécutable.

## 13. Décision actuelle

La priorité n'est pas d'ajouter des features isolées. La priorité est de faire du QG le chapeau qui empêche les applications OA de diverger.

Ordre recommandé:

1. Canoniser les assets OA réels.
2. Créer les manifestes AppOmar et EduGame/Kids Academy.
3. Ajouter une page QG conformité/applications/assets.
4. Brancher Athena sur ces contrats.
5. Reprendre AppOmar avec ces règles, pas avant.
