# oa.delivery-outcomes/v1

Statut : contrat public minimal et redacted, consommé par QG puis OmarHub.

## But

Un outcome produit relie explicitement les feedbacks, la décision, l'implémentation, la revue, les tests et la preuve live. Une carte Kanban seule ne constitue pas un outcome.

## Source et sortie

- Entrée append-only : `/home/omar/11-Pilotage/ledgers/outcomes/*.json`
- Sortie QG : `/api/delivery-outcomes.json`
- Schéma : `oa.delivery-outcomes/v1`
- En test uniquement, `OA_DELIVERY_OUTCOMES_SOURCE` peut remplacer le répertoire d'entrée.

Chaque fichier peut contenir un objet ou une liste d'objets.

## Champs requis par outcome

```json
{
  "outcome_id": "string",
  "project_id": "string",
  "title": "string",
  "phase": "backlog|implementation|review|integration|deployed|rodage|maintenance|unknown",
  "status": "string",
  "responsible_now": "string",
  "updated_at": "ISO-8601 string",
  "next_gate": "string",
  "feedbacks": [{"actor": "alex|cc-omar|h-omar|h-athena", "kind": "string", "summary": "string", "disposition": "string", "evidence_refs": ["safe-reference"]}],
  "delivery": {
    "decisions": [{"summary": "string", "evidence_refs": ["safe-reference"]}],
    "implementation": [{"summary": "string", "evidence_refs": ["safe-reference"]}],
    "reviews": [{"summary": "string", "evidence_refs": ["safe-reference"]}],
    "tests": [{"summary": "string", "evidence_refs": ["safe-reference"]}],
    "live_proofs": [{"summary": "string", "evidence_refs": ["safe-reference"]}]
  },
  "anomalies": ["short redacted summary"]
}
```

## Safety and degraded mode

- Le collecteur utilise une allowlist de champs : aucun transcript, header auth, env, token, chemin interne ou champ arbitraire n'est publié.
- Les erreurs sont bornées ; elles ne contiennent que le nom de fichier et une catégorie.
- Répertoire absent, JSON invalide ou contrat invalide : `status` et la phase concernée sont `unknown`. Le build QG reste disponible.
- `ok` signifie seulement qu'au moins un rapport contractuellement valide a été collecté ; ce n'est ni un verdict Athena ni une autorisation de release.
