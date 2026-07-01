# Capability context contract — QG / OA agents

But: donner aux agents le minimum de contexte utile sur les capacités OA, sans injecter tout le registre et sans exposer de secrets.

## Contrat mission

Chaque mission qui dépend d’outils/capacités peut déclarer:

```json
{"capability_context_ids": ["qg-static-api", "qg-hermesui", "agent-registry"]}
```

Règles:

1. 3 à 8 ids maximum par mission.
2. Sélection par besoin réel: domaine, outil à utiliser, preuve attendue, risque connu.
3. Champs injectables uniquement: `id`, `name`, `type`, `status`, `owner`, `known_gaps`, `how_to_use`, `proof_command`, `security_scope`, `last_checked`.
4. Exclure les sorties brutes de commandes, samples, tokens, `.env`, chemins secrets, données client non nécessaires.
5. Si une mission publie dans QG, inclure `qg-static-api`; si elle choisit des capacités, inclure `agent-registry`.

Sorties QG liées:

- `/api/capabilities-eval.json`
- `/api/capabilities-eval.md`
- bloc `/ops/` “Capability eval”.
