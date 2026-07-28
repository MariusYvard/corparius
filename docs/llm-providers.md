# Providers LLM gratuits

Le routeur accepte un modèle sous la forme "cible:nom". La cible "local" désigne Ollama, "cloud" l'API Anthropic, "claudecode" le CLI Claude Code et chaque entrée du registre OPENAI_COMPAT_PROVIDERS (corparius/llm.py) un service distant au dialecte OpenAI chat-completions. Un provider est actif quand CORP_CLOUD_ENABLED vaut true et que sa clé est définie dans l'environnement. Sans clé, il est absent du pool et le routeur l'ignore sans erreur.

Quand un appel distant échoue (rate limit, panne, réseau), le routeur déroule la chaîne CORP_LLM_FALLBACK en ordre, puis termine sur le modèle local CORP_LOCAL_MODEL. Le local reste donc toujours disponible en dernier recours.

## Brancher sans toucher un fichier

Tout se règle depuis l'onglet Providers de la console, sans éditer `.env` :

- **Abonnement Claude** — la carte « Utiliser votre abonnement Claude » teste le CLI `claude`, puis bascule mock/cloud/Claude Code et pointe les tiers sur `claudecode:` en un clic. Pas de clé, pas de crédits ; il suffit d'avoir fait `claude login`.
- **Fournisseurs gratuits** — chaque ligne a un bouton **Tester** : un vrai appel minimal qui distingue une bonne clé d'une faute de frappe et nomme le correctif, pas le code HTTP.
- **Ollama** — la carte « Modèles locaux » montre ce qui est installé et tire en arrière-plan les modèles que vos tiers exigent.
- **Serveur local (LM Studio, Jan, llama.cpp, vLLM, LocalAI)** — un préréglage remplit l'endpoint de la cible `custom:` ; démarrez le serveur, choisissez-le, pointez un tier sur `custom:<modèle>`.

Quel que soit le fournisseur ou le modèle, les sorties destinées aux agents passent par le harness `corparius/structured.py` : même schéma en entrée, même dict validé en sortie. Un modèle bavard, un fence markdown ou une prose sans JSON donnent tous la même structure, avec un repli déterministe qui garde le tour de l'agent en vie.

## Registre

Limites relevées en juin et juillet 2026. Elles évoluent, la documentation du provider fait foi.

| Cible | Endpoint | Clé (variable) | Free tier | Note |
| --- | --- | --- | --- | --- |
| groq | api.groq.com/openai/v1 | GROQ_API_KEY | 30 req/min, 14 400 req/jour sur la plupart des modèles | Sans carte bancaire. Inférence LPU rapide |
| cerebras | api.cerebras.ai/v1 | CEREBRAS_API_KEY | 30 req/min, 1 M tokens/jour, contexte plafonné à 8K | Sans carte bancaire. Inférence très rapide |
| openrouter | openrouter.ai/api/v1 | OPENROUTER_API_KEY | modèles suffixés ":free", 20 req/min, 50 req/jour (1 000 req/jour après un versement unique de 10 $) | Agrégateur, large choix de modèles ouverts |
| mistral | api.mistral.ai/v1 | MISTRAL_API_KEY | plan Experiment, 1 req/s, 500 000 tokens/min, environ 1 milliard tokens/mois | Hébergeur français. Le plan gratuit implique l'usage des prompts pour l'entraînement |
| gemini | generativelanguage.googleapis.com/v1beta/openai | GEMINI_API_KEY | 5 à 15 req/min, 100 à 1 000 req/jour selon le modèle | Free tier indisponible dans l'UE, au Royaume-Uni et en Suisse |
| nvidia | integrate.api.nvidia.com/v1 | NVIDIA_API_KEY | environ 40 req/min, plus de 100 modèles ouverts | Vérification téléphonique demandée |
| github | models.github.ai/inference | GITHUB_TOKEN | 10 à 15 req/min, 50 à 150 req/jour selon le modèle, entrées 8K et sorties 4K max | Un compte GitHub suffit (token classique) |
| cohere | api.cohere.ai/compatibility/v1 | CO_API_KEY | 20 req/min, 1 000 appels/mois | Clé d'essai réservée à un usage non commercial |
| huggingface | router.huggingface.co/v1 | HF_TOKEN | crédits mensuels Inference Providers, faibles | Route vers plusieurs hébergeurs |
| ovh | oai.endpoints.kepler.ai.cloud.ovh.net/v1 | OVH_AI_ENDPOINTS_ACCESS_TOKEN | 2 req/min par IP et par modèle en anonyme | Fonctionne sans clé. Hébergement UE |
| zhipu | open.bigmodel.cn/api/paas/v4 | ZHIPU_API_KEY | modèles GLM Flash gratuits, 1 requête concurrente | Données traitées en Chine |
| siliconflow | api.siliconflow.cn/v1 | SILICONFLOW_API_KEY | 3 modèles gratuits, 30 req/min, 50 req/jour | Données traitées en Chine |
| cloudflare | CF_AI_BASE_URL (endpoint du compte) | CLOUDFLARE_API_TOKEN | 10 000 neurons/jour | Endpoint propre au compte, format dans .env.example |
| custom | CORP_CUSTOM_LLM_URL | CORP_CUSTOM_LLM_KEY | selon le service | OmniRoute, LiteLLM, vLLM, LM Studio ou tout endpoint OpenAI-compatible |
| claudecode | CLI local "claude -p" | aucune (connexion du CLI) | limites de l'abonnement Claude | Aucun crédit API. CLI installé et connecté requis. CORP_CLAUDE_CODE=true |
| cloud | api.anthropic.com | ANTHROPIC_API_KEY | payant (crédits API) | Provider historique du tier hard |

## Obtenir les clés

groq : console.groq.com/keys. cerebras : cloud.cerebras.ai. openrouter : openrouter.ai/keys. mistral : console.mistral.ai/api-keys. gemini : aistudio.google.com/app/apikey. nvidia : build.nvidia.com/settings/api-keys. github : github.com/settings/tokens (modèles sur github.com/marketplace/models). cohere : dashboard.cohere.com/api-keys. huggingface : huggingface.co/settings/tokens. ovh : endpoints.ai.cloud.ovh.net. zhipu : open.bigmodel.cn/usercenter/apikeys. siliconflow : cloud.siliconflow.cn/account/ak. cloudflare : dash.cloudflare.com/profile/api-tokens.

## Exemple de configuration

```bash
CORP_LLM_MOCK=false
CORP_CLOUD_ENABLED=true

# Tiers: trivial local, normal gratuit rapide, hard raisonnement gratuit.
CORP_TRIVIAL_MODEL=local:gemma4:e4b
CORP_NORMAL_MODEL=groq:llama-3.3-70b-versatile
CORP_HARD_MODEL=openrouter:deepseek/deepseek-r1-0528:free

# Repli en cascade, le local ferme toujours la chaîne.
CORP_LLM_FALLBACK=cerebras:gpt-oss-120b,mistral:mistral-small-latest,ovh:gpt-oss-120b

GROQ_API_KEY=gsk_...
OPENROUTER_API_KEY=sk-or-v1-...
CEREBRAS_API_KEY=csk-...
MISTRAL_API_KEY=...
```

## Abonnement Claude

Un abonnement Claude (Pro ou Max) fait tourner corparius sans clé API et sans crédits, en passant par la connexion que le CLI Claude Code détient déjà. Deux prérequis, une fois : installer Claude Code, puis `claude login`.

Ensuite, une commande :

```bash
corparius claude            # teste la connexion, puis bascule tous les paliers
corparius claude --check    # teste seulement, ne modifie rien
```

Elle applique exactement le même plan que le bouton « Utiliser votre abonnement Claude » de la console (onglet Providers), et refuse d'écrire quoi que ce soit si le test échoue : laisser « cloud activé, mock désactivé » sur un CLI qui ne répond pas mettrait l'exploitant dans un état pire qu'avant.

### Le gratuit d'abord, l'abonnement pour le difficile

Un abonnement Claude se mesure en fenêtres d'usage, pas en jetons. Le dépenser sur `draft_social_post` — palier TRIVIAL, toutes les deux heures — est l'erreur coûteuse. Donc quand un fournisseur gratuit est connecté, il garde les paliers trivial et normal, et l'abonnement ne prend que HARD, c'est-à-dire la stratégie et le codeur : les deux rôles où la différence vaut une fenêtre.

L'abonnement devient aussi le dernier maillon distant de `CORP_LLM_FALLBACK`, avant le repli local. Un gratuit qui tombe escalade donc vers l'abonnement au lieu de retomber sur un modèle local qui n'est peut-être pas installé.

```bash
CORP_LLM_MOCK=false                        # sortir du mode hors ligne
CORP_CLOUD_ENABLED=true                    # la porte maîtresse de tout distant
CORP_CLAUDE_CODE=true                      # autoriser la cible claudecode:
CORP_TRIVIAL_MODEL=local:gemma4:e4b        # Ollama si disponible
CORP_NORMAL_MODEL=groq:llama-3.3-70b-versatile
CORP_HARD_MODEL=claudecode:opus
CORP_LLM_FALLBACK=openrouter:...,claudecode:opus
```

Il en faut quatre à la fois — mock, cloud, Claude Code, paliers — et c'est cette conjonction cachée qui rendait la chose difficile à activer à la main.

Sans aucun gratuit connecté il n'y a rien à préférer : l'abonnement sert alors tous les paliers. Pour l'imposer malgré tout :

```bash
corparius claude --all-tiers
```

et dans la console, le bouton « L'utiliser pour tous les paliers » à côté du principal.

Les paliers visent des alias (`haiku`, `sonnet`, `opus`) et non des identifiants datés : c'est le CLI qui les résout vers la version courante, donc rien ici n'est à remettre à jour quand un modèle sort.

**Opus sur le palier difficile.** C'est la cadence qui le rend soutenable. HARD ne sert que deux rôles — la stratégie, toutes les 24 heures, et le codeur, à la demande — c'est le palier le moins fréquent du roster. Le modèle qui coûte le plus par appel est donc celui qu'on appelle le moins, ce qui est exactement à quoi servent des paliers. Mettre Opus sur `normal` ferait partir une fenêtre d'usage dans la rédaction de réponses au support.

En mode « tous les paliers » (`--all-tiers`), l'échelle est complète : haiku, sonnet, opus. Un abonnement s'y consomme nettement plus vite ; c'est le compromis assumé de ce mode.

Rappel du découpage : TRIVIAL sert social, publicité, finance et concurrence ; NORMAL sert le PDG, la prospection, le support et le design ; HARD sert la stratégie et le codeur.

Si le CLI est installé mais la cible inactive, `corparius doctor` le signale et donne la commande : quelqu'un qui a déjà l'abonnement paie sinon une inférence qu'il pourrait obtenir d'une connexion qu'il possède. Le lanceur `start.py` le dit aussi au premier démarrage.

## Confidentialité et conformité

Plusieurs free tiers exploitent les prompts pour l'entraînement ou la journalisation : Mistral (plan Experiment), Google AI Studio, une partie des modèles ":free" d'OpenRouter, zhipu et siliconflow traitent les données en Chine. Ne pas router vers ces cibles les tours qui contiennent des données personnelles de prospects (RGPD) : garder ces flux sur "local", ou sur un hébergeur UE (ovh, mistral) après lecture de ses conditions. La clé d'essai Cohere interdit l'usage commercial.

## Sources

- github.com/cheahjs/free-llm-api-resources
- github.com/mnfst/awesome-free-llm-apis
- github.com/open-free-llm-api/awesome-freellm-apis
- github.com/diegosouzapw/OmniRoute (gateway auto-hébergé, à brancher via la cible "custom")

## Le coût réel

OpenRouter renvoie le coût de chaque appel dans le bloc `usage` de la réponse, sur le même endpoint `/chat/completions` que corparius appelle déjà. Il est lu, accumulé dans le budget de session, enregistré par agent et affiché dans la console.

Les treize autres fournisseurs compatibles OpenAI n'envoient rien. Leur coût vaut donc 0, et **0 veut dire « non rapporté », pas « gratuit »** : la console n'affiche un montant que si au moins un appel en a rapporté un, sinon elle le dit. Afficher « 0,00 » pour un fournisseur muet reviendrait à annoncer à un exploitant sur clé payante qu'il n'a rien dépensé.

`CORP_SESSION_COST_BUDGET` plafonne la dépense dans la devise du fournisseur, et `cost_budget` fait la même chose par entreprise dans `company.yaml`. Le défaut est 0, c'est-à-dire désactivé : le budget de jetons reste le plafond qui s'applique partout, puisque tous les fournisseurs comptent des jetons.
