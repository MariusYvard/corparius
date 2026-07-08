# Feuille de route 90 jours

Un déploiement d'agent ou d'entreprise autonome suit un cadre en six étapes sur douze semaines, conçu pour sécuriser la mise en production et obtenir un retour rapide.

| Étape | Semaines | Contenu |
| --- | --- | --- |
| 01 Cadrage et architecture | 1 | ROI attendu, 1 à 3 cas d'usage à fort retour, arbitrage local ou cloud selon la sensibilité des données |
| 02 Modèle et provisionnement | 2 | choix du LLM, déploiement de l'inférence (vLLM, Ollama, GPU) |
| 03 Ingestion et RAG | 2 à 3 | connexion aux sources (Notion, Confluence, S3, SQL), index vectoriel (pgvector, Qdrant), reranking |
| 04 Agent et outils | 4 à 7 | compétences de l'agent, intégrations API (CRM, Slack, Stripe), validations Pydantic strictes |
| 05 Observabilité et tests | 8 à 10 | suivi des jetons et des coûts (Langfuse, Helicone), tests sur jeu de référence de 50 à 200 cas |
| 06 Production et transfert | 11 à 12 | formation des équipes, runbook, garantie de production, transfert |

## Choix de la stack

La structure logicielle dépend de la sensibilité des données, des volumes d'appels et du budget. Les frameworks code-aware comme le SDK Claude Code servent les agents d'infrastructure et de DevOps, de la revue de code à l'analyse de journaux. Les frameworks Python persistants comme LangChain, LlamaIndex et Pydantic AI conviennent aux logiques métier à validation stricte, un schéma Pydantic garantissant un format typé pour les API d'entreprise. Les frameworks TypeScript natifs comme le SDK IA de Vercel et Mastra visent les agents intégrés à des applications Next.js. Les modèles ouverts autogérés comme Mistral, Llama et Qwen se déploient en local ou sur GPU privé pour garder les données soumises au RGPD hors des tiers.

## Trajectoire d'évolution de corparius

Le MVP couvre la boucle, les garde-fous et la validation humaine. Quatre chantiers le portent vers la production. L'exécution durable (Temporal.io ou l'ADK de Google) remplace la persistance SQLite simple par un journal d'événements et un rejeu déterministe, pour survivre aux pannes sur des flux longs. Les outils passent en serveurs MCP, avec divulgation progressive et masquage des identifiants sensibles avant tout appel au modèle. Le générateur de code s'exécute dans un bac à sable éphémère (Modal, E2B, Daytona), provisionné par le workflow et détruit à la clôture. Le service local d'inférence passe sur vLLM, avec des modèles quantifiés et affinés par adaptation à bas rang, et un RAG hybride combine recherche vectorielle et lexicale BM25 avec reranking.

Côté livraison de code, l'agent adopte le modèle des GitHub Agentic Workflows: exécution en lecture seule par défaut, écritures filtrées par un sous-système de sorties sécurisées, invite décrite en Markdown puis compilée en workflow GitHub Actions.

## Sources

- https://uclic.fr/expertise/agents-ia-custom
- https://temporal.io/blog/temporal-sandbox-orchestration-harness-the-missing-layer-for-running-agents
- https://www.anthropic.com/engineering/code-execution-with-mcp
- https://developers.googleblog.com/build-long-running-ai-agents-that-pause-resume-and-never-lose-context-with-adk/
