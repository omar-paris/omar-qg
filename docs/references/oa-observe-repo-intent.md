# oa-observe — registre d'intention par repo (`var/repo-intent.json`)

Statut : référence opérateur · schéma `oa.repo-intent/1` · carte `t_d1d22bf2`

## Pourquoi

`det_repo_idle()` signalait « pas en mode amélioration » dès qu'un repo n'avait
plus de commit depuis `REPO_IDLE_DAYS` **et** n'avait « pas de backlog ». Trois
défauts rendaient ce verdict faux :

1. un échec `gh issue list` (`n_issues is None`) était compté comme « 0 issue » ;
2. `returncode`/`stderr` de `gh` étaient jetés : l'échec était invisible ;
3. un repo **gelé volontairement** était indistinguable d'un repo abandonné.

Quatrième cause de persistance : la clôture automatique ne regardait que
`var/oa-observe-kanban-state.json`. Une clé absente de ce fichier (perte,
restauration, écriture partielle) rendait la carte immortelle.

## Comportement actuel

| Situation | Finding émis | Carte Kanban |
|---|---|---|
| `n_issues is None` (échec `gh`) | `gh_unreadable` (P2) + note `rc=<n> : <stderr[:200]>` dans `notes` | oui (P2) |
| `n_issues == 0` et idle | `repo_idle` (P2) | oui |
| `n_issues > 0` et idle | aucun | non |
| `intent: frozen` dans le registre | `repo_intent_frozen` (INFO) | **non** (briefing seulement) |
| `intent: active` ou absent | comportement historique | oui |

`n_issues is None` ne produit **jamais** `repo_idle` : « je ne sais pas » n'est
pas « zéro ».

## Réconciliation board

`plan_kanban_sync()` réconcilie les cartes **du board**, pas seulement le fichier
d'état : toute carte ouverte `created_by=oa-observe` dont la clé d'idempotence
n'apparaît plus dans les findings courants reçoit un commentaire puis
`complete`. Le fichier d'état n'est plus qu'un cache.

Bornes de sécurité :

- `--only <det>` : la réconciliation est limitée aux détecteurs réellement
  exécutés — un scan ciblé ne peut pas clore les cartes des autres détecteurs ;
- `--fixture` : réconciliation désactivée (pas de scan réel) ;
- `--no-board-reconcile` : désactive explicitement la réconciliation ;
- `--kanban-dry-run` : liste les `resolve` candidats sans rien exécuter.

## Déclarer un repo figé

Ajouter une entrée dans `var/repo-intent.json` (gitignoré, machine-local) :

```json
{
  "schema": "oa.repo-intent/1",
  "repos": {
    "omar-exemple": {
      "intent": "frozen",
      "decided_by": "H-Omar",
      "decided_at": "YYYY-MM-DD",
      "card": "t_...",
      "reason": "pourquoi le gel est décidé",
      "reopen_condition": "ce qui doit être vrai pour rouvrir"
    }
  }
}
```

Un registre absent, illisible ou d'un autre schéma est ignoré (le scan retombe
sur le comportement historique) : un registre cassé ne doit jamais faire taire
une alerte.

## Empreinte stable

Pour `repo_idle`, l'empreinte d'idempotence est ancrée sur le **nom du repo**
(et la sévérité), pas sur la mesure volatile (« 37j sans commit ») : une seule
carte par repo, pas une nouvelle carte chaque jour.

## Reprise du cron

Le producteur `oa-observe-morning.sh` reste **pausé**. La reprise est une
décision séparée, après preuve de non-régression sur les doublons.
