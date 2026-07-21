# Architecture

corparius exécute une entreprise autonome comme une boucle d'agents planifiés. Un tick représente une heure simulée. À chaque tick, l'ordonnanceur sélectionne les agents dus, chacun déroule une courte séquence d'outils, et le pare-feu de sécurité plus la validation humaine encadrent chaque étape. L'état (actions, jetons, approbations, horloge) est persisté dans SQLite.

## Topologie d'orchestration

Quatre schémas de contrôle existent pour un système multi-agents: centralisé (un coordinateur unique planifie et délègue), décentralisé (des pairs se coordonnent sans superviseur), hiérarchique (plusieurs couches de délégation) et hybride (planification centrale, exécution déléguée en parallèle). corparius adopte un contrôle centralisé à flux déterministe. Le code décide quels agents s'exécutent et dans quel ordre, le modèle ne choisit pas le routage. Ce choix vient du cas Polsia, où la délégation dynamique sans contrôle produit des dérives, et d'une règle de conception simple: si le code peut décider, le code décide.

La spécialisation des agents reste utile. Une évaluation d'Anthropic mesure qu'une architecture à agent principal plus sous-agents spécialisés dépasse un agent unique de même génération de 90,2 % sur des tâches de recherche complexes, par l'isolation du contexte et la parallélisation. corparius garde la spécialisation (dix rôles, chacun avec son contexte et ses outils) sans l'autonomie de routage qui fragilise la production.

| Topologie | Coordination | Statut dans corparius |
| --- | --- | --- |
| Séquentielle déterministe | enchaînement défini par le code | playbook de chaque agent |
| Parallèle (sous-agents) | invocation simultanée d'agents apatrides | réservée aux analyses lourdes, hors MVP |
| Superviseur hiérarchique | routage pyramidal en couches | rôle léger tenu par l'agent CEO |
| Dynamique (routeur) | aiguillage adaptatif par le modèle | écartée, le routage reste dans le code |

## Les dix agents

| Agent | Cadence | Tier de modèle |
| --- | --- | --- |
| CEO (orchestrateur) | 12 h | normal |
| Médias sociaux | 2 h | très simple |
| Prospection | 3 h | normal |
| Support | 3 h | normal |
| Publicité | 6 h | très simple |
| Finance | 6 h | très simple |
| Stratégie | 24 h | lourd |
| Concurrence | 24 h | très simple |
| Design | 24 h | normal |
| Générateur de code | à la demande | lourd (modèle de code épinglé) |

## Routage LLM à trois tiers

Le routeur choisit un modèle selon le tier de difficulté. Les tâches très simples (publication sociale, veille, finance déterministe) tournent sur un petit modèle local, gemma4:e4b. Les tâches normales passent sur un modèle cloud. Les tâches lourdes (stratégie, code) prennent un modèle cloud adapté, et un agent peut épingler un modèle précis, tel un modèle de code local pour le générateur de code. Chaque modèle s'écrit "cible:nom", où la cible est "local", "cloud" (API Anthropic), "claudecode" (CLI Claude Code sur abonnement) ou l'un des providers gratuits OpenAI-compatibles du registre (groq, cerebras, openrouter, mistral et les autres, voir llm-providers.md), ce qui rend chaque tier reconfigurable sans toucher au code. Quand un appel distant échoue, le routeur déroule la chaîne CORP_LLM_FALLBACK puis bascule sur un modèle local de repli.

## Console opérateur

Une console web locale (corparius/webui.py) sert une page unique via la bibliothèque standard : pouls de la company, file d'approbations, backlog kanban, métriques de flux, panneau providers (bascules, tiers, clés en écriture seule) et conversation avec l'agent CEO. Elle écoute sur 127.0.0.1, partage le store SQLite du CLI et lance les runs dans le même firewall. Voir console.md.

## Persistance et exécution durable

Le MVP persiste l'horloge et le journal dans SQLite, ce qui suffit à reprendre une exploitation entre deux runs. Un flux d'entreprise réel s'étale sur des jours et rencontre des pannes en cours de route. La reprise fondée sur le seul historique conversationnel échoue souvent (8 % à 13 % de succès selon les mesures citées), là où un checkpoint conscient de la sémantique approche 100 %. La trajectoire de production passe par l'exécution durable (Temporal.io ou l'ADK de Google): journal d'événements immuable, rejeu déterministe qui réinjecte les résultats déjà obtenus au lieu de les recalculer, et mise en veille pendant les temps morts, par exemple l'attente d'une approbation ou d'un document signé. Le rejeu réduit aussi le coût d'optimisation des invites, puisque les étapes antérieures ne sont pas recalculées.

## Outils et MCP

Chaque outil métier est une fonction avec un effet mock dans le MVP (paiement, prospection, publication, code). Le remplacement par des intégrations réelles se fait outil par outil, sans toucher à la boucle. La cible de standardisation est le Model Context Protocol, qui expose des ressources, des outils et des invites via une topologie hôte, client et serveur sur JSON-RPC 2.0. Deux propriétés servent une entreprise autonome. La divulgation progressive fait exécuter un script dans le serveur MCP et ne renvoie que la synthèse au modèle, ce qui évite de charger toutes les données intermédiaires en contexte. L'isolation des données remplace les identifiants sensibles par des jetons anonymisés avant tout appel au modèle, les traitements se faisant de serveur à serveur.

## Comparaison de frameworks

Trois cadres dominent la mise en production. LangGraph modélise une machine à états typée avec persistance native et validation humaine configurable. CrewAI décrit des rôles et des tâches, rapide à prototyper mais fragile sur de longues chaînes de délégation dynamique. AutoGen coordonne des agents par conversation, fort pour l'exécution de code mais coûteux en jetons sans limites de terminaison. corparius n'adopte aucun des trois dans le MVP: un noyau déterministe minimal (ordonnanceur, exécuteur, garde-fous) évite la dépendance et garde le flux auditable. LangGraph est le portage naturel le jour où un graphe d'états et un retour dans le temps deviennent nécessaires.

## Sources

- https://www.langchain.com/blog/choosing-the-right-multi-agent-architecture
- https://temporal.io/blog/building-ai-agents-that-overcome-the-complexity-cliff
- https://www.anthropic.com/engineering/code-execution-with-mcp
- https://developers.googleblog.com/build-long-running-ai-agents-that-pause-resume-and-never-lose-context-with-adk/
- https://modelcontextprotocol.io/specification/2025-11-25
