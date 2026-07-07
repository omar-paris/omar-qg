# Audit Fable final — autonomie OA

*Fable, consultant/exécuteur senior — dernière fenêtre, 07/07/2026. Basé sur 4 jours d'immersion totale (mandat rescue 03-07/07) + vérifications fraîches de ce jour. Chaque preuve est vérifiée sauf mention [hypothèse].*

## 1. Verdict exécutif

Le système OA est passé en 4 jours de « machine en panne silencieuse » à « machine qui se mesure, se répare et se gouverne » : 899 done, 0 crash sur 184 runs/24 h, boucle de review autonome, 3 VPS qui rapportent, puzzle mesuré à 90 %. **Le problème n'est plus la machine : c'est qu'elle ne produit encore aucun revenu et que son humain reste son composant le plus surchargé.** Le funnel est techniquement ouvert mais **zéro lead réel n'est entré depuis l'ouverture** (dernier lead = un test du 05/07) : tout le travail restant à plus fort ROI est du côté trafic/vente, pas du côté infra. Deuxième vérité : l'autonomie est réelle mais repose sur des contrats récents (vps-report, VERDICT, handoff) qu'il faut **stabiliser 7 jours sans rien ajouter** — d'où la stop-doing list. Troisième vérité : la dépendance à Claude/Fable est désormais faible par construction (tout vit dans des cartes, des schémas et des crons), sauf un point : **les 15+ commits patches-oa non poussés** qui sont le seul artefact critique existant à un seul endroit.

## 2. Les 10 leviers à plus fort ROI

| Rang | Levier | Pourquoi | Preuve observée | Action 48h | Owner proposé |
|---|---|---|---|---|---|
| 1 | **Pousser patches-oa** (review + push fork + tag) | Seul artefact critique non répliqué ; un `hermes update` détruit le moteur d'autonomie (handoff, auto-unblock, disjoncteur) | `git log baseline..patches-oa` = 15+ commits, gateway tourne dessus | Review H-Omar du middleware auth, push `alexwill87/hermes-agent`, tag | H-Omar |
| 2 | **Premier trafic réel sur la landing** | Funnel 100 % construit, 0 visiteur : chaque jour sans trafic = ROI nul de tout le funnel | 0 lead réel depuis ouverture (vérifié var/leads/, dernier = test 05/07) | Alex envoie le lien à 5 artisans de son réseau + Google MyBusiness JAB ; mesurer leads/j sur /blocages | Alex (seul à avoir le réseau) |
| 3 | **Démo audit bout-en-bout enregistrée** | L'audit conversationnel est LA démo différenciante ; personne ne l'a jamais parcourue de bout en bout en conditions réelles | Cartes [AUDIT] 1/3 todo, 3/3 en gate ; parcours jamais filmé/testé par un humain externe | Alex fait l'audit complet en navigation privée, note chaque friction ; en faire le script de démo | Alex + oa-builder (frictions) |
| 4 | **Restore-test des backups** | Rouge le plus dangereux de la carte : backups jamais éprouvés sur omar ET jab — un backup non testé n'existe pas | MAINT-RESTORE-01 FAIL sur 2 VPS (vps-reports) | Restore réel d'un backup JAB sur un répertoire jetable + preuve dans le rapport quotidien | oa-vps-operator |
| 5 | **Mesurer la sécurité (4 items gris)** | SEC-UFW/SSH/SUDO/SECRETS jamais mesurés = on ne sait pas si la porte est fermée | Strate Sécurité : 4 items gris (carte.json) | Écrire les 4 checks (ufw status, sshd config, sudoers audit, scan secrets) dans omar-top/checks + brancher au vps-report | oa-builder + gate |
| 6 | **Merge PR#56 (/docs/) après gate** | Les liens profonds vers les docs sont le chaînon manquant du Control Tower (déjà codé, 62 tests verts) | PR#56 draft, /docs/ = 404 live | Gate Athena → merge → les 3 liens du brief deviennent vivants | H-Omar |
| 7 | **Boucle feedback → carte automatique** | Les feedbacks d'Alex (comme ce matin) doivent devenir des cartes sans qu'il le demande | Ses 3 feedbacks du 07/07 ont exigé ma présence pour devenir des corrections | Petit collecteur : toute réponse inline /blocages contenant « ??? » ou ton négatif → carte triage `[FEEDBACK-ALEX]` | oa-secretaire |
| 8 | **Réconcilier les 2 supervisions flotte** | /ops/ (vps-report, maturité) et /clients/ (inventory) racontent 2 histoires — retour du « 2 sources de vérité » | totals incohérents : omar `health=fail` dans inventory vs 10/12 PASS dans /ops/ | Décision d'architecture : inventory = apps, vps-report = standards ; une page consomme les deux, pas 2 pages | H-Omar (carte t_48c9fc95) |
| 9 | **Rapports Pantheos complets** | 3e VPS = famille d'Alex ; rapport partiel (12 apps, 0 standards) = angle mort sur alexgo.eu/kids | pantheos-health.v1.json sans standards[] (vérifié) | h-Aurel enrichit son rapport avec le générateur de référence omar-top/bin (copier-adapter) | h-Aurel |
| 10 | **Cartes humaines : lien cliquable obligatoire** | La question d'Alex « je clique où ??? » = symptôme général : une carte humaine sans lien direct est une carte morte | t_50fd4fd7 (OAuth Gmail) sans lien de consentement pendant 6 jours | Règle dans CONTRAT-DE-CARTE + check gardener : carte assignee=alex sans URL cliquable → non conforme | oa-qa-officer |

## 3. QG Control Tower

### Ce qui marche (vérifié ce jour)
- Le squelette décisionnel complet : Manifeste → Carte (puzzle 212 cellules mesurées) → Chantiers → Blocages (avec réponse inline d'Alex qui débloque réellement les cartes — prouvé 3 fois ce matin) → Ops (3 VPS) → Décisions (rebuild immédiat à la réponse).
- La chaîne de vérité : chaque couleur/compteur vient d'une source (vps-report, kanban.db, decisions.json) — plus rien de peint à la main.
- Le rythme : rebuild 30 min + rebuild instantané sur réponse + rapports VPS quotidiens 06h30.

### Ce qui manque
1. **Les liens profonds** : docs (/docs/ en PR#56), cartes kanban (id cité mais pas cliquable vers hermes.omar.paris/kanban), décisions↔cartes croisées. Le cockpit pointe, mais pas encore jusqu'au bout du doigt.
2. **Le « lancer »** : Alex peut voir et décider, pas encore *déclencher* (relancer une boucle, commander un rework) depuis le QG. La mécanique existe (qg_api → kanban) — il manque 2-3 boutons d'action sur /ops/ et /carte/.
3. **La fraîcheur affichée partout** : /objectifs/ figé au 14/06 encore en ligne, agent-loop figé au 15/06 — les fusions (étapes 6-8 du plan de convergence) n'ont pas été exécutées.
4. **L'historique** : aucun « hier vs aujourd'hui » — le puzzle dit où on est, pas si on avance. Un snapshot quotidien de carte.json + une flèche de tendance par strate suffiraient.

### Liens directs — recommandation concrète
Une seule convention, trois cibles : `qg.omar.paris/docs/?doc=<slug>` (PR#56, à merger), `hermes.omar.paris/kanban` + ancre carte (vérifier le support d'ancre du dashboard Hermes, sinon lien simple), URL GitHub directes (déjà fait). Règle : **tout id affiché est un lien** — un check pytest qui grep les `t_[0-9a-f]{8}` non entourés d'un `<a>` dans le HTML généré rendrait la règle exécutable.

### Pages à refondre dans l'ordre
1. Fusion decisions→blocages (une seule boîte de réception Alex — les deux boutons de réponse coexistent déjà).
2. Suppression /objectifs/ + /changelog/ (figés, doublons de /chantiers/ et « Dernières mergées »).
3. Fusion agent-loop→/boucles/ (quand le rework NO-GO des boucles passe sa gate).
4. /clients/ absorbé par /ops/ (levier n°8).
5. `/carte/` : ajouter la tendance quotidienne (levier historique).

## 4. Autonomie agents

### Boucles orphelines ou fragiles (preuves)
- **10 cartes actives sans parent** (requête task_links ce jour) — le contrat « lien montant » n'est pas encore appliqué par tous les créateurs.
- **21 gates ouvertes** dont ~la moitié sont des dailies re-générées chaque matin : la boucle daily crée plus de gates que la flotte n'en draine certains jours [hypothèse à mesurer sur 7 jours].
- **Les 3 reworks R3** (cause racine commune : artefact non rejouable à froid — fichiers untracked absents du diff) : la leçon n'est pas encore un standard. Standard à créer : « tout livrable de worker inclut son diff complet OU sa branche poussée ».
- **oa-audit** : réparé (skill seedé 06/07) mais son rôle a changé de facto (9 runs kanban) sans que son SOUL soit mis à jour.

### Contrats à standardiser (dans l'ordre)
1. **agent-report** : le vps-report/v1 est le modèle — généraliser le triplet {verdict, preuve, next_action ownerisée} à TOUT rapport d'agent (dailies incluses).
2. **gate** : VERDICT: GO|NO-GO|HOLD — déployé et adopté à 100 % depuis le 06/07 (vérifié) ; il reste à exiger la citation du standard OmarTop appliqué (« NO-GO — standard X §n ») : c'est ce qui arme le judiciaire.
3. **handoff** : `kanban_handoff` existe et marche ; le prescrire dans les SOULs restants (seuls builder/athena l'ont en consigne explicite).
4. **blockers** : tenant-scoped obligatoire (défaut JAB du 07/07, carte t_d70c17e0).
5. **docs** : le slug /docs/?doc= comme référence canonique dans les cartes.

### Automatisations qui réduisent la dépendance à Claude/Fable
- **Déjà en place** (c'était le mandat) : auto-unblock sur verdict, disjoncteur quota, purge multi-profils documentée, rapports quotidiens, digest unique, réponse inline Alex→déblocage.
- **À créer, par ROI décroissant** : (a) le collecteur feedback→carte (levier 7) ; (b) un `oa-doctor` schedulé qui exécute les checks OmarTop en continu (l'incohérence « exigé par un check, schedulé nulle part » tient depuis la classification) ; (c) drainage automatique des gates dont la PR est déjà MERGED (9 cartes de ce type trouvées par Mission 2 — un cron de 20 lignes) ; (d) le snapshot quotidien de carte.json (tendance).

## 5. Produit / revenus

### Actions 48h
1. **Trafic** : Alex envoie la landing à 5 artisans réels + l'affiche sur le Google MyBusiness de JAB (levier 2 — aucun agent ne peut le faire à sa place).
2. **Démo** : parcours audit complet par Alex en navigation privée, chronométré, frictions notées (levier 3).
3. **Devis JAB rétroactif** : formaliser dans le proposal_server ce que JAB paie déjà réellement — le premier devis « vrai » du système est celui du client existant.
4. Fermer la carte [AUDIT] 3/3 (gate en cours) : rapport→devis 67 € câblé.
5. Décision Alex : la démo cible (audit boulangerie ? fleuriste ?) — 1 secteur, pas 3.

### Actions 7 jours
- Onboarding Maryse comme 2e tenant réel (le rail bootstrap existe, la décision D22 la désigne).
- Stripe en sandbox sur le devis (la carte découpée l'attend), PAS en prod avant le premier devis accepté.
- Le rapport d'audit PDF/page — la « preuve de valeur » que le prospect garde.

### Ce qu'il faut arrêter
- Arrêter d'améliorer l'infra du funnel avant d'avoir 10 visiteurs réels dessus.
- Arrêter de créer des pages QG (5 pages cible, on y est presque — fusionner, pas ajouter).
- Arrêter les rapports Deepsearch/architecture tant que les contrats v1 actuels n'ont pas 7 jours de production.

## 6. Souveraineté pragmatique

### Local-first maintenant
- **Fait et à préserver** : kanban, QG, vps-reports, inter-vps-inbox (pull-first Pantheos = le bon modèle), leads, Vault (mais toujours en mode -dev : la migration Infisical décidée [D12] reste à faire — c'est le vrai sujet souveraineté n°1).
- **À faire** : patches-oa sur le fork (levier 1) — la souveraineté du code moteur.

### Cloud acceptable temporairement
- Codex/OpenAI comme runtime des agents (le forfait ×4 marche ; un fallback local Ollama existe déjà dans hermes pour la résilience, pas pour le quotidien).
- GitHub (org privée) — la traçabilité vaut plus que l'auto-hébergement git aujourd'hui.
- Google OAuth pour l'audit public (c'est même un argument de confiance client).

### Risques réels (vs fantasmes)
- **Réel** : Vault -dev (secrets en mémoire, perdus au restart, non chiffrés au repos) ; patches-oa non répliqués ; backups non testés ; 4 items SEC jamais mesurés. Ces quatre-là sont concrets et datés.
- **Fantasme au stade actuel** : auto-héberger les LLM pour la « vraie » souveraineté (coût/qualité prohibitifs à 1 client), multi-région, zero-trust complet. Le rapport Deepsearch est une carte des possibles, pas une todo — l'avis de H-Omar (« inspiration, pas vérité exécutable ») est le bon.

## 7. Plan d'exécution 7 jours

| Jour | Objectif | Livrable vérifiable | Risque |
|---|---|---|---|
| J1 (08/07) | patches-oa poussé + PR#56 mergée | fork à jour + /docs/ en 200 | review auth mal faite → gate Athena dessus |
| J1-J2 | Trafic initial + démo Alex | ≥5 envois tracés, 1 parcours audit filmé/noté | zéro réponse → c'est une DONNÉE (message à revoir) |
| J2 | Restore-test JAB + omar | preuve dans vps-report (MAINT-RESTORE-01 PASS) | restore échoue → c'est LE signal qu'il fallait |
| J3 | 4 checks SEC écrits + branchés | strate Sécurité sans gris sur omar | faux positifs → itérer les seuils |
| J3-J4 | Drainage auto gates-mergées + feedback→carte | 2 crons livrés avec gate | bruit → deliver local d'abord |
| J4-J5 | Fusions QG (decisions→blocages, retrait objectifs/changelog) | 5 pages exactement, tests verts | casser un lien Alex → vérifier avec lui page par page |
| J5-J7 | Devis JAB rétroactif + rapport Pantheos complet | devis dans proposal_server ; standards[] pantheos | h-Aurel indispo → reporter, pas forcer |
| J7 | Bilan des contrats v1 (7 j de prod) | verdicts adoptés/à réviser dans un doc court | — |

## 8. Questions bloquantes pour Alex

1. **Trafic** : à qui envoies-tu la landing cette semaine (5 noms) — et veux-tu qu'on prépare le message d'accompagnement ?
2. **Démo cible** : quel secteur pour LA démo (boulangerie/JAB est le plus documenté) ?
3. **Vault → Infisical** (D12, décidé jamais exécuté) : GO pour planifier la migration cette semaine ou explicitement reporté ?
4. **Maryse** : GO pour démarrer son onboarding comme 2e tenant (VPS + rail bootstrap) ?
5. **Le QG te suffit-il pour décider seul 7 jours** — ou quel manque t'obligerait encore à demander à un agent « où en est-on » ?

---
*Preuves principales : kanban.db (899 done, 184 runs/0 crash 24 h, 10 orphelines, 21 gates), var/carte.json (212 cellules, 90 %/75 %), var/leads/ (0 lead réel), vps-reports omar/jab/pantheos, PR#56 (/docs/ 404 live), FABLE_FINAL_HANDOFF.md. Rédigé sans modification du système — ce rapport est le livrable.*
