# Comparatif

Positionnement de corparius face aux plateformes de référence. Les figures sur NanoCorp, Polsia, Uclic, OpenWorker et Hermes Agent sont détaillées dans les fiches dédiées.

| Solution | Approche | Hébergement | Garde-fous et validation humaine | Souveraineté des données |
| --- | --- | --- | --- | --- |
| NanoCorp | création ex nihilo de micro-entreprises | SaaS hébergé | orchestrateur CEO, contrôle documenté limité | données chez le tiers |
| Polsia | exploitation autonome de bout en bout | SaaS hébergé | neuf agents, fiabilité contestée (1,8 sur 5) | données chez le tiers |
| Pancake | autonomisation d'entreprises existantes | connecté à la stack du client | dépend de la stack raccordée | selon la stack |
| Uclic | dispositifs d'acquisition sur mesure | mixte, agents Claude et n8n | défini par mission | selon le montage |
| OpenWorker | agent de bureau généraliste, livrables finis | auto-hébergé, clés de l'utilisateur | modes de permission, classes de risque, boîte de réception | totale, sauf la poignée de main OAuth |
| Hermes Agent | un agent très outillé, qui apprend de ses sessions | auto-hébergé, sept back-ends de terminal | approbation d'édition, compétences protégées, curateur qui archive sans effacer | totale, sauf les magasins de mémoire tiers |
| corparius | création et exploitation locale | auto-hébergé | budget, boucle, coupe-circuit, validation humaine native | totale, local par défaut |

## Ce que corparius prend à chacun

De NanoCorp, le signal de récompense unique et la boucle d'agents planifiés, sans la dépendance à une plateforme tierce. De Polsia, le catalogue des rôles et leurs cadences décalées, mais avec des garde-fous en tête et un flux déterministe plutôt qu'une délégation dynamique. De Pancake, l'idée de se brancher sur la stack réelle, reprise via des outils remplaçables un par un. D'Uclic, l'ingénierie d'acquisition par signaux d'intention et l'inversion de persona, portées par l'agent de prospection. De Hermes Agent, la **boucle d'apprentissage fermée** : un agent qui écrit ses propres compétences, la règle négative qui l'empêche de graver une panne passagère en croyance permanente, et surtout le curateur qui entretient la bibliothèque — sans son fork après chaque tour, qui doublerait les appels d'une boucle où personne n'attend devant l'écran. D'OpenWorker, quatre sous-systèmes plus mûrs que leurs équivalents locaux: les permissions par classe de risque, les compétences en prose à divulgation progressive, la mémoire persistante et la boîte de réception typée, mais sans sa boucle ReAct ni ses sous-agents, qui rendraient le routage au modèle.

## Sources

- https://getpancake.ai/blog/pancake-vs-nanocorp
- https://www.nanocorp.so/
- https://github.com/andrewyng/openworker
- https://github.com/NousResearch/hermes-agent
- https://preuve.ai/blog/polsia-review
- https://uclic.fr/cas-clients/avanoo-22-signaux-intention-sam-finops
