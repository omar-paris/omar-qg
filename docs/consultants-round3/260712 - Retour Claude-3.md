Je m'appuie sur **BRIEF-QG.md** et sur tout le contexte V4 déjà en tête. Je note la décision durable, puis je tape.Le brief est bon — il a déjà intégré la redaction au ship, le mTLS, la reprise par séquence, la 3ᵉ position. Donc je ne rejoue pas ça. Je vais **au-delà de sa propre lucidité**. Priorisé, le pire d'abord.

---

**1. Le filet a un trou en son centre : QUI juge la liveness du QG lui-même ? (le vrai angle mort — ta question 7)**

Le socle de sécurité V4 dit : *« un Hub ne peut jamais se déclarer vert seul → le QG le juge de l'extérieur. »* Magnifique. Mais **qu'est-ce qui juge le QG de l'extérieur ?** Le brief répond « observé depuis une 3ᵉ position » — sauf que si cette 3ᵉ position est un script *sur le QG* qui surveille le QG, c'est **exactement la faute** que tout le design rejette (l'auto-observation). Tu as une **régression à l'infini** : le Hub est surveillé par le QG, le QG par… rien de vraiment indépendant. Résultat : le QG meurt en silence à 2h (OOM, incident Hetzner, son propre bug), les heartbeats de tous les VPS s'empilent sans traitement, **aucun VPS n'est réellement down, mais tout le filet de la flotte est éteint et rien sur Terre ne le sait.** Le « le silence ressemble à la santé » que le QG était censé résoudre **réapparaît un cran plus haut, au QG** — et cette fois il n'y a pas de niveau au-dessus.

**AJOUTER (bloquant) : un dead-man's-switch EXTERNE et bête pour le QG lui-même**, opéré par un **tiers** (service d'uptime type healthchecks, autre provider, autre région), que le QG doit pinguer ; son silence alerte par un canal **hors de ton infra**. C'est le seul moyen de **terminer** la régression « qui garde le gardien ». Règle : la racine de confiance de la liveness doit être quelque chose que **tu n'exploites pas** et qui est **trop bête pour mentir**. Corollaire : les sondes outside-in doivent tourner depuis une position indépendante **du Hub ET du process principal du QG** (un petit prober séparé, autre région) — sinon « QG figé » fige aussi le prober.
*Cas concret : samedi 2h, le disque du QG sature, le process d'ingest se fige sans crasher (donc systemd ne le restart pas). Les VPS heartbeatent dans le vide. Maryse tombe à 3h. Lundi, tu découvres 31h d'outage flotte non détectées. Ton filet était mort, et il n'a pas su qu'il était mort.*

---

**2. « Extend vs redo » est un faux binaire : il faut SÉPARER le watchdog du cockpit (ta question 1)**

Le QG a **deux identités aux exigences opposées** : (a) un **cockpit** de confort (vues client, agrégation, front) — vélocité élevée, organique, peut être down 1h ; (b) un **watchdog** safety-critical (dead-man's-switch, outside-in, alerting) — doit ne **jamais mentir ni mourir en silence**, immuable, ennuyeux. **Étendre le QG organique, c'est coupler la fonction la plus critique au code le plus instable.** Chaque feature de confort que tu pushes au cockpit peut, en crashant/OOMant, **emporter le watchdog avec elle** — et personne ne surveille la flotte pile quand ton propre changement a cassé quelque chose. Le QG « a grossi au fil du temps » = plus haute vélocité + plus de complexité incidente = **le pire hôte possible** pour un rôle de sécurité.

**MODIFIER la décision « extend » : les deux, mais sur des axes différents.** On **étend** le QG organique pour le **cockpit** ; on **construit neuf, minimal, isolé, ailleurs** le **watchdog**. Le cockpit peut planter sans éteindre le filet.
*Cas concret : tu ajoutes une vue « marge par client » au QG, bug boucle infinie, OOM. 40 min de QG mort — donc de dead-man's-switch mort. Une feature de confort a coulé le filet de sécurité.*

Et où « extend » mord précisément : le brief admet *« une fuite inter-tenant est déjà arrivée »*. Donc le QG **a déjà fui entre clients une fois** — et tu veux en faire la **concentration inter-clients safety-critical**. C'est doubler la mise sur le composant au **pire historique** pour l'échec qui compte le plus. Le chemin evidence/sécurité a besoin d'un modèle de tenancy **propre et audité à part**, pas du RBAC organique.

---

**3. Le « filet » détecte mais ne rattrape rien — et se fera muter en une semaine (ta question 2)**

Heartbeat + outside-in + log store, c'est le **20 % facile** (détecter). Un filet qui détecte sans agir est juste une façon plus bruyante d'apprendre que tu as déjà échoué. Il manque :

- **L'escalade et la réponse.** L'opérateur est **un** solo. Le dead-man's-switch sonne à 3h → qui agit ? Si la réponse est « Alex voit demain », la latence détection→réponse est de **plusieurs heures**, donc le client est down plusieurs heures **quand même**. Un filet pour solo **doit** inclure une **1ʳᵉ réponse automatique** (tentative de restart/heal avant d'alerter) + une **escalade multi-canal à paliers avec SLA** (Telegram → SMS → appel), pas « une alerte ».
- **Les faux positifs tueront le filet avant tout bug.** N VPS artisans (réseaux fragiles, petites box Hetzner, redémarrages Nextcloud, hoquets Tailnet) = **flot d'alertes « VPS down » fausses**. Un solo qui reçoit 5 fausses alertes/nuit **coupe le canal en une semaine** — et rate la vraie. **AJOUTER : confirmation multi-signal + flap-damping** (n'alerter que si heartbeat manquant **ET** sonde KO **ET** silence de logs, corrélés sur une fenêtre) + paliers de sévérité + heures calmes.
*Cas concret : semaine 1, 4 fausses alertes/nuit à cause d'un Tailnet capricieux. Semaine 2, tu mets le canal en silencieux. Semaine 3, JAB tombe vraiment ; l'alerte part dans le canal muté ; tu l'apprends par son coup de fil furieux.*

---

**4. La signature prouve l'origine, pas l'honnêteté : le mensonge silencieux et l'agrégat empoisonné (ta question 4)**

Le brief couvre le QG *down* ou *compromis*. Il rate deux modes plus vicieux :

- **Le heartbeat qui ment.** Le dead-man's-switch fait confiance à la **présence** du battement, pas à sa **véracité**. Un VPS dont l'agent est deadlocké, le disque plein, mais dont le petit cron heartbeat tire encore → dit « je suis vivant » alors qu'il est mort fonctionnellement. **MODIFIER : heartbeats à assertions signées** (porter des faits vérifiables — dernier run de conformité OK, disque %, agent-alive — avec preuve) et **alerter sur assertion dégradée**, pas seulement sur absence. Un ping nu est le piège classique.
- **L'agrégat empoisonné.** Le contrat est signé/mTLS (bien, anti-spoof). Mais un VPS **compromis détient des clés légitimes** : il peut shipper de la conformité/des logs **falsifiés** vers le haut (« tout vert ») tout en exfiltrant. Pire : si le QG **rend les logs d'un VPS dans le front cockpit sans sanitization**, un client compromis **attaque ton propre cockpit** par le canal d'observabilité (log-injection / stored-XSS). C'est **exactement `LAW-AGENT-UNTRUSTED-INPUT`** — que personne n'a appliqué à l'ingestion QG. **AJOUTER : traiter tout flux montant comme `untrusted_content` MÊME signé** (sanitization, pas de HTML brut, quarantaine d'un tenant devenu incohérent).
- **Le signal que tu n'exploites pas : la contradiction.** Le VPS dit « vert » mais la sonde outside-in dit « KO » → **cette contradiction est ton meilleur signal**, de plus haute sévérité que l'un ou l'autre seul. Le brief a les deux sources mais ne les **croise** pas.

---

**5. « Errors seulement » fuit quand même : le log EST la fuite, et pour JAB il ne doit pas partir (ta question 5)**

Le périmètre MVP (conformité/daybook/errors/heartbeat) est bon **sauf que "errors" contient du texte**, et c'est là que ça fuit. La redaction-au-ship est une promesse que le **VPS émetteur** fait sur **ses propres données** — un VPS **buggé ou compromis ne la tiendra pas**, et une allowlist rate les formes de champ nouvelles. Donc le QG recevra, tôt ou tard, du **stderr client non rédigé** (un nom de dossier dans une stack trace).

- **RETIRER, pour les clients sensibles : le ship des logs bruts vers le QG.** Pour un avocat (JAB), « centraliser les logs » peut être **incompatible avec ses obligations de confidentialité**, redaction ou pas. Le log store reste **local** ; le QG ne reçoit qu'un **error = code + compteur**, jamais le message+stack. **À trancher explicitement : un "error" shippé est-il un code/compteur (OK) ou un texte (local-only pour clients sensibles) ?**
- **AJOUTER : redaction en défense en profondeur** (au ship **ET** à l'ingest **ET** au rendu) + **rétention par classification** (le défaut est « ne pas shipper », pas « shipper et garder 1 an »). Chaque octet retenu au QG est une **responsabilité** : une brèche du QG expose N clients, dont des avocats.
*Cas concret : le connecteur PennyLane de JAB throw une exception qui embarque un libellé de facture nominatif ; l'allowlist ne matche pas ce champ ; le texte atterrit en clair dans Loki au QG central. Six mois plus tard, un accès QG mal configuré l'expose. Tu viens de faire fuiter le dossier d'un client d'avocat — le pire scénario réputationnel de ta boîte.*

---

**6. L'échelle qui casse en premier n'est pas le compute, c'est TON attention (ta question 6)**

Le brief pense « 100/1000 clients » côté charge. Le mur arrive **bien avant**, à ~30 : si chaque client génère un faux positif/semaine, c'est ~4/jour — tu es noyé (cf. point 3). **La limite d'échelle du QG, c'est le rapport signal/bruit à 30 clients, pas la RAM à 1000.** **MODIFIER l'objectif : concevoir pour l'attention** — un seul écran « ce qui ne va pas », exceptions-only, « tout vert = une ligne ». Un cockpit qui affiche N tuiles client est déjà inutilisable à N=50.

Deux corollaires : **(a) rétention/coût des logs × N = bombe** (linéaire en clients × verbosité, et 100 % responsabilité) → minimisation + TTL par classification. **(b) Silence corrélé = suspecte le gardien, pas les gardés** : si 10 VPS deviennent silencieux d'un coup, c'est **bien plus probablement ton ingest QG qui est cassé** que 10 outages simultanés. Le watchdog doit **distinguer « la flotte est down » (ta faute) de « ces VPS-là sont down »** — sinon tu réveilles 10 fausses alertes au lieu d'une vraie (« mon QG est cassé »). Et le watchdog ne se partitionne **jamais** par client (il lui faut la vue globale pour voir le silence corrélé) ; seul le cockpit/log store shard par tenant — ce qui reconfirme le point 2 (séparer les deux).

---

## Synthèse

Le QG en V4 est **sous-spécifié pour ce qu'on lui demande** : on lui a confié le filet de sécurité de la flotte tout en le traitant comme un tableau de bord de confort qu'on « étend ». Les deux ne cohabitent pas dans un même process organique.

Trois décisions à prendre en direct, par ordre : **(1)** poser un **dead-man's-switch externe tiers pour le QG lui-même** (sans lui, tout l'argument de sécurité est circulaire — c'est bloquant) ; **(2)** **séparer physiquement watchdog et cockpit** (extend le cockpit, build-clean le watchdog, ailleurs) ; **(3)** trancher la **gouvernance des logs pour les clients sensibles** — pour JAB, défaut *ne pas centraliser*.

S'il n'y en avait qu'une : **le point 1.** Tu as inventé le QG pour que le Hub ne se mente pas à lui-même. Ne laisse pas le QG se mentir à lui-même de la même façon. Le filet a besoin d'un clou planté **en dehors** de toi.

Si tu veux, on écrit le périmètre du **watchdog minimal** (heartbeat à assertions + outside-in indépendant + dead-man's-switch tiers + règles de corrélation/flap-damping), séparé du cockpit, prêt à poser en dépendance dure de la 1ʳᵉ prod.