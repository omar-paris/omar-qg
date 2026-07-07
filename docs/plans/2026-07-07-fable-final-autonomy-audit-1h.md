# Brief Fable final — audit autonomie OA en 1h

## Contexte

Tu travailles avec Omar & Alex comme consultant/exécuteur senior **Claude Code Fable** pour une fenêtre courte, peut-être la dernière.

Réponds et écris tes rapports en **français**.

H-Omar/Hermes reste l’orchestrateur CTO : Kanban/QG/GitHub sont sources de vérité, Athena/reviewer garde les gates froides, et tu ne dois **pas** merger, release, déployer, supprimer, archiver, ni créer de système parallèle.

Objectif : produire un audit très utile avant autonomie maximale locale/souveraine.

## Mission en 1h

Auditer l’ensemble OA visible depuis le workspace et produire un plan d’amélioration priorisé, opérationnel, anti-bruit.

Tu dois regarder en priorité :

1. **QG / Control Tower**
   - Est-ce que le QG aide vraiment Alex/H-Omar à décider ?
   - Où manquent les liens directs vers docs, cartes Kanban, décisions, blocages, preuves ?
   - Comment transformer docs + blocages + décisions en cockpit actionnable sans énorme menu ?

2. **Autonomie agents / operating system**
   - Où les agents créent-ils du bruit, des orphelins, des boucles non fermées ?
   - Quels contrats simples faut-il standardiser : agent report, gate, docs, blockers, handoff ?
   - Quelles automatisations réduisent la dépendance à Claude/Fable ?

3. **Produit / revenus**
   - Quelles 5 actions concrètes rapprochent OA d’une vente réelle ?
   - Où le funnel landing → audit → devis → paiement → onboarding est le plus fragile ?
   - Quelle démo client prioriser ?

4. **Souveraineté pragmatique**
   - Quels éléments doivent être local-first maintenant ?
   - Quels éléments cloud restent acceptables temporairement ?
   - Quels risques sont réels vs fantasmes architecturaux ?

5. **Stop-doing list**
   - Qu’est-ce qu’OA doit arrêter de faire pendant 7 jours pour sortir de l’itération infinie ?

## Sources à consulter en priorité

Repo QG :

```txt
/home/omar/23-Offre/actifs/omar-qg
```

Docs clés :

```txt
docs/plans/2026-07-07-qg-revue-page-par-page-control-tower.md
docs/plans/2026-07-07-qg-systeme-oa-cockpit-vivant.md
docs/references/2026-07-07-sovereign-multi-agent-architecture-google-deepsearch.md
README.md
QG_CONTRACT.md
CHANGELOG.md
```

Surfaces générées utiles :

```txt
public/index.html
public/blocages/index.html
public/ops/index.html
public/agent-loop/index.html
public/docs/index.html
public/api/docs-index.json
public/api/blocages.json
public/api/agent-loop-audit.json
public/api/repo-health.json
```

Si tu as le temps, regarde aussi :

```txt
/home/omar/23-Offre/actifs/omar-top
/home/omar/23-Offre/actifs/omar-app
/home/omar/23-Offre/actifs/omar-landing
/home/omar/31-Agents
/home/omar/11-Pilotage
```

## Contraintes

- Ne lis pas ou ne demande pas de secrets.
- Ne modifie pas de fichier sans accord explicite ; pour cette mission, produire d’abord un rapport.
- Ne propose pas de grand framework abstrait si une checklist/action suffit.
- Distingue **preuves vérifiées**, **hypothèses**, **recommandations**.
- Priorise les actions qui réduisent le bruit opérationnel ou rapprochent des revenus.
- Les cartes Kanban peuvent être référencées par numéro/id, même sans lien direct.
- Les docs QG peuvent maintenant être référencés via `/docs/?doc=<slug>`.

## Livrable attendu

Créer un fichier Markdown :

```txt
/home/omar/23-Offre/actifs/omar-qg/docs/reviews/2026-07-07-fable-final-autonomy-audit.md
```

Format obligatoire :

```md
# Audit Fable final — autonomie OA

## 1. Verdict exécutif
- 5 lignes max.

## 2. Les 10 leviers à plus fort ROI
| Rang | Levier | Pourquoi | Preuve observée | Action 48h | Owner proposé |

## 3. QG Control Tower
### Ce qui marche
### Ce qui manque
### Liens directs docs / Kanban / décisions / preuves — recommandation concrète
### Pages à refondre dans l’ordre

## 4. Autonomie agents
### Boucles orphelines ou fragiles
### Contrats à standardiser
### Automatisations à créer

## 5. Produit / revenus
### Actions 48h
### Actions 7 jours
### Ce qu’il faut arrêter

## 6. Souveraineté pragmatique
### Local-first maintenant
### Cloud acceptable temporairement
### Risques réels

## 7. Plan d’exécution 7 jours
| Jour | Objectif | Livrable vérifiable | Risque |

## 8. Questions bloquantes pour Alex
- Maximum 5 questions.
```

## Message court à coller dans Fable

```txt
Tu travailles avec nous comme consultant/exécuteur senior Claude Code Fable. Réponds et écris tes rapports en français.
Hermes/H-Omar reste l’orchestrateur CTO : Kanban/QG/GitHub sont sources de vérité, Athena garde les gates froides. Ne merge pas, ne release pas, ne déploie pas, ne supprime rien, ne lis pas de secrets.

Lis le brief durable : /home/omar/23-Offre/actifs/omar-qg/docs/plans/2026-07-07-fable-final-autonomy-audit-1h.md
Mission : audit final autonomie OA en 1h, avec livrable Markdown dans /home/omar/23-Offre/actifs/omar-qg/docs/reviews/2026-07-07-fable-final-autonomy-audit.md
Avant d’agir, confirme en 5 lignes ce que tu as compris et commence directement l’audit.
```
