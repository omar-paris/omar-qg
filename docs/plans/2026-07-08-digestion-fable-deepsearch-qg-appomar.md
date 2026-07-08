# Digestion Fable / Deep Search — QG + AppOmar

Date: 2026-07-08
Auteur: H-Omar/default
Statut: matrice d’intégration — pas un dépôt brut de MD

## 0. Décision de méthode

Les documents Fable / Deep Search ne sont pas des livrables produit en eux-mêmes. Ils doivent être digérés selon quatre sorties:

1. **Intégrer** — devient contrat, test, schéma, source UI ou règle QG/AppOmar.
2. **Reprendre** — utile mais doit être reformulé, verticalisé ou découpé.
3. **Écarter** — trop générique, faux niveau d’abstraction, non vérifié, ou hors timing.
4. **Suivre** — bonne idée, mais nécessite une carte/issue/gate avant exécution.

## 1. Sources inspectées

| Source | Rôle | Statut |
|---|---|---|
| `omar-app/docs/research/2026-07-08-audit-business-tech-appomar-deep-search-result.md` | Rapport brut Deep Search | Matière première, non exécutable |
| `omar-app/docs/plans/2026-07-08-google-deep-search-audits-business-tech-world.md` | Prompt + cadrage recherche | À garder comme traçabilité de recherche |
| `omar-app/docs/plans/2026-07-08-audit-business-tech-onboarding-devis-deepsearch.md` | Cadrage audit → onboarding → devis | À reprendre en backlog produit |
| `omar-app/docs/plans/2026-07-08-audit-business-tech-deep-search-integration-plan.md` | Plan d’intégration technique | À transformer en issues/tests, pas tout merger d’un bloc |
| `omar-qg/docs/plans/2026-07-07-qg-revue-page-par-page-control-tower.md` | Revue QG page par page | Source prioritaire QG |
| `omar-qg/docs/plans/2026-07-07-qg-systeme-oa-cockpit-vivant.md` | Vision QG cockpit vivant | Source prioritaire QG |
| `omar-qg/docs/reviews/2026-07-07-fable-final-autonomy-audit.md` | Audit Fable autonomie | Source de décisions, mais trop pavée pour UI directe |

## 2. Matrice d’intégration

| Élément | Décision | Destination système | Pourquoi |
|---|---|---|---|
| Audit public sans compte + sauvegarde optionnelle | **Intégrer** | AppOmar contrat + tests + UI audit | Décision Alex directe ; réduit friction prospect |
| Devis réservé aux inscrits/authentifiés | **Intégrer** | AppOmar + Caddy/QG décision release | Sépare diagnostic public et engagement commercial |
| PayPal cible, Stripe legacy | **Intégrer** | AppOmar checkout + contrat offre | Évite promesse fausse et vieille dette Stripe |
| Traçabilité D/V/H/F | **Intégrer** | AppOmar `report_contract` + future UI rapport | Rend le rapport crédible : déclaré/vérifié/hypothèse/fichier |
| Consentement sources publiques | **Intégrer** | AppOmar étape audit + tests | Nécessaire RGPD/confiance ; évite recherche sauvage |
| Cyber baseline TPE | **Reprendre** | AppOmar arbre audit + OmarTop standard | Utile, mais doit devenir questions courtes par secteur |
| Facturation électronique 2027 | **Reprendre** | Audit secteurs TPE/PME | Fort intérêt business, mais à contextualiser par métier |
| Scoring multi-indices | **Reprendre** | AppOmar rapport + QG standards | Garder explicabilité ; écarter formules pseudo-scientifiques |
| Banque complète de questions Deep Search | **Reprendre** | Packs sectoriels + arbre YAML | Trop long brut ; doit devenir blocs conversationnels validés |
| Rapport final 17 sections | **Reprendre** | Template rapport v1 | Bonne structure, mais version courte client d’abord |
| Onboarding agent_profile | **Intégrer progressivement** | AppOmar onboarding + Hub/QG client lifecycle | Relié à la promesse OA ; nécessite tests A→Z |
| Devis pédagogique justifié | **Reprendre** | AppOmar devis | OK après rapport ; pas au centre de l’audit |
| QG séparation pouvoirs OmarTop/QG/Athena/H-Omar | **Intégrer** | QG home + OmarTop standards | Clarifie qui décide / exécute / contrôle |
| QG source_type/freshness/proof/owner/next_action | **Intégrer** | QG chaque widget | C’est exactement ce qui manque à Alex aujourd’hui |
| QG `/decisions/` pavés Fable | **Écarter comme UI brute** | QG doit condenser + détails repliés | Les pavés empêchent la décision ; garder en source/détails |
| QG `/blocages/` comme page centrale | **Intégrer** | QG priorité P0 | Alex doit voir le blocage, sa cause, son owner, son action |
| Dagu/CUE/Rego/Firecracker/libkrun | **Suivre** | Backlog standards/infra | Intéressant, pas priorité cockpit/revenu immédiat |
| Cloud Map/vstash | **Suivre** | Futur `oa.resource-scope/v1` | À cadrer après QG source/proof et AppOmar audit |
| Multi-tenant Maryse/Maroc | **Suivre après QG** | QG clients lifecycle + AppOmar onboarding | Risqué si QG ne montre pas les blocages et validations |

## 3. Priorité proposée

### P0 — QG cockpit Alex

Objectif: arrêter les décisions opaques et les rapports inutilisables.

À livrer d’abord:

1. `/decisions/` lisible: titre, option recommandée, impact, source, détails repliés, erreur API explicite.
2. `/blocages/` lisible: cause, owner, action, preuve, lien carte/PR/gate, pas une seule ligne tronquée.
3. Home QG: top 5 “à décider / à produire / à contrôler”, avec fraîcheur et source.

### P1 — Digestion AppOmar

Transformer les docs audit en backlog concret:

1. tracer D/V/H/F dans rapport ;
2. étape sources publiques consenties ;
3. arbre audit business/tech v1 ;
4. rapport court client + détails repliés ;
5. onboarding/devis dérivés du rapport.

### P2 — Maroc / second tenant

Ne pas démarrer fort tant que QG ne sait pas montrer:

- ce qui bloque ;
- ce qui est vivant vs seed ;
- ce qui attend Alex ;
- ce qui a été validé par Athena.

## 4. Backlog exécutable immédiat

| Ordre | Item | Repo | Gate |
|---|---|---|---|
| 1 | Fix `/decisions/`: erreur explicite + détails repliés + options visibles | `omar-qg` | tests QG + Athena |
| 2 | Refaire `/blocages/`: afficher détail complet et owner/action/preuve | `omar-qg` | tests QG + dogfood |
| 3 | Home QG top actions du jour | `omar-qg` | Athena |
| 4 | AppOmar: rapport D/V/H/F minimal | `omar-app` | Athena PR #62 ou follow-up |
| 5 | AppOmar: sources publiques consenties | `omar-app` | Athena |

## 5. Décision CTO

On ne jette rien, mais on arrête de considérer les MD comme intégrés. La priorité système immédiate est **QG cockpit**, parce que sans cockpit clair Alex ne voit ni les blocages, ni les validations, ni l’état réel des agents. AppOmar continue en PR, mais sans release tant que la digestion n’a pas été découpée et gate Athena passée.
