# NVIDIA labs — Object-Oriented Agents (NOOA)

NOOA n'est pas un produit concurrent : c'est une **bibliothèque pour écrire des agents**,
publiée par NVIDIA. Elle n'exploite pas d'entreprise, elle ne se compare pas à corparius sur
la souveraineté, et la moitié de son dépôt est un visualiseur de traces en React. Elle mérite
d'être lue quand même, parce que sa thèse est nette et qu'elle contredit celle de corparius
frontalement.

## La thèse

Une phrase, de son README : **« Agents are Python objects. »** L'état devient des champs
typés, les capacités des méthodes, **les invites des docstrings**, et les contrats des
annotations de type — tout dans une seule classe Python. Trois abstractions en découlent :

- **Generation methods.** Une méthode dont le corps est `...` est *implémentée par le modèle à
  l'exécution*. La signature et la docstring forment à la fois le contrat et l'invite.
- **State as fields.** Les capacités et les données sont des attributs typés, donc l'outillage
  Python habituel — tests, refactoring — s'applique.
- **Code as action.** Pas de schéma d'outil : le modèle **exécute du Python** dans un REPL de
  style Jupyter, avec accès à `self` et aux méthodes typées.

Plus, en propriétés annexes : arguments passés **par référence** et non sérialisés, E/S typées
avec réessai automatique, traçage de **tous** les appels de modèle par défaut, et des
garde-fous par validation AST et liste de modules interdits — dont le README dit lui-même
qu'ils ne remplacent pas un bac à sable au niveau de l'OS.

## Ce qui est refusé, et ce n'est pas un détail

**Code as action.** C'est le troisième refus de la même chose, et le plus net. `docs/openworker`
consigne le refus de la boucle ReAct (« le modèle choisit ses outils. C'est la différence
structurante avec corparius, dont le flux de contrôle reste dans le code »).
`docs/hermes-agent` consigne le refus du fork après chaque tour. Ici il s'agit de donner au
modèle un interpréteur Python avec `self` — le maximum d'agence qu'un cadre puisse accorder.

La docstring d'`agents.py` dit l'inverse en trois lignes : *« Control flow is deterministic:
code decides which tools runs, and in what order. The LLM only drafts content. Routing stays
out of the model. »* Et ce n'est pas une préférence de style : corparius fait tourner dix rôles
**sans personne devant l'écran**, avec une porte humaine par classe de risque
(`config/permissions.py`) qui n'a de sens que si l'ensemble des effets possibles est fini et
déclaré. Quarante outils énumérés dans `tools/spec.py` sont pesables ; un REPL ne l'est pas.

Le README de NOOA le concède d'ailleurs à sa manière, en disant qu'un vrai confinement demande
un bac à sable OS. Corparius n'en a pas et n'en veut pas — il tourne sur le poste de
l'opérateur, sur ses clés.

**Les generation methods** tombent avec, pour une raison plus terre à terre : une docstring est
statique. Les invites de corparius interpolent l'entreprise — son nom, son offre, sa langue,
ses derniers échecs — et se composent à l'exécution. Une docstring ne peut pas porter ça.

## Ce que corparius en tire

Une chose, mesurée, et une petite en prime.

### 1. Le traçage ne doit pas être facultatif

C'est la propriété annexe de NOOA qui compte : *« Default tracing: all LLM calls and executions
traced automatically. »* **Automatiquement**, c'est-à-dire pas au choix de l'appelant.

Corparius produit exactement les bonnes données. `structured.ask` renvoie un objet qui porte
`ok`, `fell_back`, `attempts`, `source` et `errors`. Compté sur le paquet :

| Champ | Lecteurs |
| --- | --- |
| `.data` | **12** |
| `.ok` | 3 |
| `.source` | 1 |
| `.fell_back` | 1 |
| `.errors` | 0 |
| `.attempts` | 0 |

Douze appelants lisent la charge utile, un seul lit d'où elle vient. Ce n'est pas une
découverte : la docstring de `_empty_draft` l'a déjà écrit, avec son coût — *« The harness has
always carried the answer — ok, fell_back, attempts, source, errors — and this is the fourth
caller to read only one field of it »*, après qu'un opérateur ait lu « Nothing usable drafted »
comme un générateur de site cassé alors que groq et cerebras répondaient 429, **et dépensé
365 026 jetons pour y arriver**.

`_empty_draft` a été écrit comme le correctif : un helper partagé qui distingue « le modèle
n'avait rien à ajouter » de « aucun fournisseur n'a répondu ». Mais il est **facultatif** — un
outil doit penser à l'appeler. Et le journal, lui, n'en garde rien :

```python
def record_action(self, company, agent, tool, parameters, output, ok) -> None:
```

Six colonnes, dont un booléen. `agents.py` a l'objet complet sous la main au moment où il
appelle ça — il lui passe `result.ok` et jette les quatre autres champs. Une fois le tour
terminé, savoir *quel fournisseur* a répondu, *combien* de tentatives il a fallu et *s'il y a
eu repli* n'existe plus nulle part.

C'est la forme exacte du défaut que `tests/test_registries.py` existe pour attraper —
**produit et jamais consommé** — appliquée à la donnée de diagnostic la plus chère du produit.
Et c'est la même leçon que `kernel/proc.py` : sept sites répétaient les cinq mêmes arguments et
un seul disait pourquoi le cinquième était porteur.

La reprise n'est pas un helper de plus. C'est **l'exécuteur qui enregistre le détail de
routage, une fois, là où il l'a déjà** — pas chacun des douze effets. Une colonne, une ligne.

### 2. Trois déclarations, un seul appariement gardé

L'idée « une seule déclaration » de NOOA pose une question vérifiable ici. Un outil de
corparius se déclare en trois endroits — `needs_draft` (un modèle est appelé), `schema` (la
réponse doit valider), `prompt` (ce qu'on demande) — et ils doivent s'accorder. Mesuré : **les
trois s'accordent aujourd'hui, et un seul des appariements était testé.**

Celui qui manquait est le pire, parce qu'il est silencieux. Un `schema` sans `needs_draft`
signifie que `ctx.structured` n'est jamais posé, donc l'effet lit `None`, tombe dans
`_empty_draft` et annonce « aucun modèle n'a renvoyé de structure utilisable » — **alors
qu'aucun modèle n'a été appelé**. L'opérateur est envoyé vérifier ses fournisseurs pour une
erreur de déclaration.

Le test existait déjà pour le quatrième champ, dans `test_images.py`, avec la bonne phrase :
*« un drapeau mort se lit comme une fonctionnalité par la prochaine personne qui le grep »*.
C'était la même phrase quatre fois ; elle est maintenant écrite une fois, dans
`tests/test_tool_declarations_agree.py`.

## Où ça s'inscrit

Le premier point est une colonne et une ligne dans l'exécuteur, donc **l'étape 4** du plan de
refonte, avec le reste de `store/` — au même endroit que les compteurs d'usage des compétences
et le rappel FTS5, pour la même raison : ce sont des changements de schéma, et le plan les
regroupe là où les migrations vivent.

Le second est fait, parce qu'un test de registre ne dépend d'aucune étape.
