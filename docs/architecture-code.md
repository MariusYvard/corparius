# Architecture du code : sept dossiers, cinq rangs, une règle

`docs/architecture.md` décrit la topologie **d'exécution** — la boucle de ticks, les dix
agents, les paliers de modèles, la console. Ce document-ci décrit la structure **du code** :
qui a le droit d'importer qui, et comment cette règle est tenue.

Elle est tenue par un test, pas par de la bonne volonté : `tests/test_layers.py`. Voir
l'[ADR 0007](adr/0007-les-couches-sont-des-rangs.md) pour la décision et sa mesure.

## Pourquoi

Le paquet a atteint 23 050 lignes sur 53 modules, à plat. Rien ne surveillait rien. Mesuré à
ce moment-là :

- le graphe d'imports **au niveau module est un DAG**, et les **cinq cycles du paquet
  n'existent que par ~60 imports locaux dans des fonctions** ;
- contre la structure cible ci-dessous, il n'y a que **quatre arêtes montantes** ;
- lire un réglage charge `requests`, `subprocess` et `ssl` ; importer `agents` charge en plus
  `smtplib` et `imaplib`.

La deuxième mesure est la bonne nouvelle : le code est beaucoup plus proche de la structure
visée que sa forme plate ne le laisse croire.

## Les rangs

Un module de rang *n* n'importe que des rangs **≤ n**. Jamais au-dessus.

| Rang | Dossier | Ce qui y vit | Ce qui n'y a pas le droit |
| --- | --- | --- | --- |
| 0 | `kernel/` | **fait** — `paths`, `records`, `i18n`, `text`, `dotenv`, `crypto`, `vectors`, `proc`, `httpkit` | **tout import corparius**, même d'un rang inférieur — il n'y en a pas |
| 1 | `config/` | **fait** — `cfg`, `store_layer`, `settings`, `settings_spec`, `provider_table`, `permissions`, `secretbox` | le store, les fournisseurs, le domaine |
| 2 | `store/` | **fait** — schéma, migrations, un mixin par table, la façade | tout ce qui est au-dessus |
| 3 | `providers/` | **fait** — 17 modules : modèles, routage, courrier, déploiements, dépôts, prospects, matériel | le domaine, l'app, le transport |
| 4 | `domain/` | `roster` ✅, exécuteur, `tools/{spec,effects,registry}` ✅, entreprise, documents, orchestrateur, site | **toute dépendance hôte** : `requests`, `subprocess`, `sqlite3`, `smtplib`, `imaplib`, `socket`, `time.sleep` |
| 5 | `app/` | **10 services** — `settings`, `tasks`, `publish`, `companies`, `chat`, `directives`, `mail`, `skills`, `overview`, `errors` | le transport, et **jamais un paramètre `Ctx`** |
| 6 | `api/`, `cli/` | HTTP, CLI, MCP | — rien n'importe ces dossiers |

Le rang 0 porte aussi la seule strictesse mypy du paquet : `disallow_untyped_defs` s'applique
à `corparius.kernel.*` en joker, pas en liste, pour qu'un nouveau module du kernel naisse
annoté au lieu d'être ajouté après coup.

Trois exceptions, chacune avec sa raison écrite dans le test : `corparius/__init__.py` (c'est
la racine de composition), `config/store_layer.py` (la couche de réglages en lecture seule —
on ne peut pas demander à la base où est la base), et `plugins/` (dont le métier est de
composer, voir l'[ADR 0006](adr/0006-sept-coutures-de-greffons.md)).

## Les cinq clauses qui rendent la règle réelle

1. **Les imports différés comptent.** C'est la clause porteuse. Un `from . import x` dans un
   corps de fonction est vérifié exactement comme un import en tête de fichier — sinon la
   règle manque chacun des cinq cycles qu'elle existe pour empêcher. Différer redevient une
   optimisation de démarrage, plus une échappatoire.
2. **Le rang 0 n'importe rien de nous.** C'est ce qui le rend sûr à importer de partout.
3. **Le rang 4 ne touche aucun hôte.** `agents.py` était déjà sans dépendance hôte et rien ne
   le disait ; c'est devenu une porte — qui attrape aussi l'inverse, un module de domaine qui
   se met discrètement à ouvrir une socket.
4. **Une capacité, un propriétaire.** `sqlite3` dans trois modules, c'est trois endroits qui
   peuvent verrouiller la base ; `subprocess` dans quatre, c'est quatre façons différentes de
   se tromper sur le quoting Windows.
5. **Les cycles se comptent à part.** Les rangs n'interdisent pas un cycle *à l'intérieur*
   d'un rang, et ce trou était réel : dès que `secretbox` est passé au rang 1, une arête vers
   `cfg` redevenait légale. Les composantes fortement connexes ont donc leur propre liste,
   `KNOWN_CYCLES`, avec l'étape qui dissout chacune. **Cinq au départ, zéro aujourd'hui.**

## Où en est le chantier

Étapes 1 à 5 faites, l'étape 6 faite pour sa moitié qui compte. Mesuré :

| Compteur | Au plan | Aujourd'hui |
| --- | --- | --- |
| **Arêtes montantes** | 4 | **0** |
| **Cycles d'imports** | 5 | **0** |
| Modules important `subprocess` | 4 | **1** (`kernel/proc.py`) |
| Ce que charge la lecture d'un réglage | `requests`, `subprocess`, `ssl`, `sqlite3` | **`sqlite3`** |
| Ce que charge la lecture de la liste des outils | + `smtplib`, `imaplib` | **rien** |
| Modules à plat | 53 | **29** |
| Choses que la console sait faire et la CLI non | 11 | **3**, toutes cosmétiques |
| Commandes CLI | 27 | **33** |

**Zéro arête montante**, et c'est pour ça que la liste est écrite en cliquet plutôt qu'en
commentaire : chacune des quatre a été rayée par l'étape qui la nommait, et l'ensemble vide
n'est pas un permis — `constaté == déclaré` tient toujours, donc le prochain import vers le
haut échoue sans rien derrière quoi se cacher.

**Le gain le moins cher, étape 2.** `settings_spec` importait `llm` à **une ligne sur 1 380**,
pour lire `OPENAI_COMPAT_PROVIDERS`. Le registre est maintenant `config/provider_table.py` au
rang 1, avec `split_target` (l'ancien `llm._split`, privé et atteint depuis onze modules) —
parce que décider si `groq:` est un préfixe de fournisseur demande de savoir lesquels sont
enregistrés. Effet de bord non prévu : `hardware` et `agents` n'importaient `llm` que pour
cette fonction.

**Le gain le plus gros, étape 3.** Le registre plat portait quarante déclarations et quarante
effets dans un même littéral, donc **six de ses huit consommateurs chargeaient un client SMTP
pour lire une liste de chaînes** : `company` validant les `hitl_tools` de l'opérateur, `doctor`
et `skills` vérifiant les `allowed-tools` d'une compétence, `skillcli`, le catalogue de la
console, la CLI pesant une approbation. `tools/spec.py` porte les données, `tools/registry.py`
lie les effets, et `permissions` lisant un outil par `getattr` fait qu'un `ToolSpec` se pèse
exactement comme un `Tool`.

Une correction au plan, inscrite dans `COST` : l'étape 3 devait alléger `agents`. Elle ne le
fait pas et ne doit pas — `agents` **est** l'exécuteur, et dérouler un playbook suppose
d'avoir les effets. Ce qui est devenu libre, c'est `roster` (les 150 premières lignes
d'`agents.py`) et `tools/spec`.

**Les cinq cycles sont morts, et aucun par la rupture d'une arête.** Chacun est parti quand
la chose qui n'y appartenait pas a bougé :

| Cycle | Ce que le module portait en trop | Étape |
| --- | --- | --- |
| `{cfg, secretbox}` | la cryptographie **et** la politique | 1 |
| `{appserver, backup, doctor, selfupdate, webui}` | un serveur HTTP **et** des primitives HTTP | 1 |
| `{agents, company, tools}` | une table de données **et** la machine qui la consomme | 3 |
| `{claudecli, llm, preflight}` | un fournisseur **et** la décision de l'utiliser | 5 |
| `{appcli, cli, secretscli}` | une CLI **et** le seul endroit qui ouvre le store | 7 |

Le dernier tenait à **deux lignes** : `cli._store` était le seul endroit qui résolvait un chemin
de données, donc deux sous-CLI allaient le chercher dans le module qui les importe. Le motif est
donc constant sur les cinq : **le cycle n'était jamais le problème, c'était le symptôme d'un
module qui portait deux choses.**

Trois écarts au plan, tous pour la même raison — ses noms propres entrent en collision avec
la bibliothèque standard ou avec le vocabulaire de ce codebase. `models` est devenu
`kernel/records` et non `kernel/types` (`types` est un module stdlib que cinq fichiers de
tests utilisent) ; `settings_spec` et `secretbox` gardent leur nom dans `config/` (`spec` est
une variable locale 77 fois ici, `secrets` est stdlib et `secretscli` avait déjà un
`import secrets as _secrets`). Et `modeltarget` n'est pas dans le kernel : il a besoin du
registre de fournisseurs, donc il vit avec lui au rang 1.

## L'étape 6, et ce qu'elle a trouvé

Le plan résume son intérêt en une phrase : la logique métier vit dans les gestionnaires HTTP,
donc **la console sait faire des choses que la ligne de commande ne sait pas**. Six services sont
descendus dans `app/`, et trois capacités qui n'existaient pas dans un terminal sont apparues :
`corparius set` (écrire un réglage), `corparius new` (créer une entreprise), `corparius ceo`
(parler au CEO, avec ses pouvoirs).

Deux règles font que `app/` est une couche et pas un dossier de gestionnaires renommés, et
`tests/test_app_layer.py` tient les deux : **jamais de paramètre `Ctx`** — annoté ou non, et la
version non annotée compte plus, parce que chaque gestionnaire de ce codebase l'appelle `ctx`
sans annotation — et **jamais d'erreur de transport levée**. Un service qui lève le 400 de la
console ne peut être appelé que par la console. Il lève l'échec ; la route le traduit.
`tests/test_route_table.py` affirme l'inverse pour les gestionnaires, et c'est la paire qui rend
le découpage réel.

**Deux bugs vivants sont sortis de là**, tous deux trouvés en lisant un gestionnaire à côté de sa
commande et en comparant ce que chacun savait :

- le **backlog** : la console validait l'agent et l'outil et appelait `executable_fields` à
  l'approbation ; `cmd_task` appelait `store.update_task` directement et n'avait rien de tout ça.
  Approuver depuis un terminal laissait la tâche sans outil, donc elle se fermait « done (no tool
  mapped) » sans rien faire — 24 tâches pour un rôle, 22 ainsi ;
- la **publication** : la console honorait `paths.owned_site(slug)` ; `cmd_deploy` construisait
  toujours le chemin généré. Sur l'entreprise du propriétaire, la console publiait
  `companies/vigil/site/public` et la ligne de commande `data/sites/vigil`, en annonçant un
  succès.

Les trouver à la main a marché deux fois et **ne passe pas à l'échelle** :
`tests/test_two_callers_agree.py` déclare les paires qui doivent partager un service, affirme que
les deux atteignent *ce* service, et plafonne la taille d'un adaptateur — parce qu'un adaptateur
qui reprend de la logique est exactement comment les deux côtés ont divergé, un commit à la fois.

### Ce qui reste de l'étape 6

Neuf services sont descendus et neuf paires sont sous cliquet. Les trois écarts qui restent
sont cosmétiques ou déjà couverts autrement : le thème de la console, les charges utiles de
rendu (`_settings_payload`, `_providers_payload`, `_company_payload`), et `_ollama_pull` /
`_claude_setup`, dont les cousins `bench` et `claude` existent déjà côté ligne de commande.

La seconde moitié de l'étape — déplacer le transport de `webui.py` vers `api/` — est purement
structurelle : 56 gestionnaires, la table de routes et le serveur. Elle n'ouvre plus aucune
capacité, et les deux gardes qui la protégeront existent déjà
(`tests/test_route_table.py` pour les deux bouts de la table, `tests/test_app_layer.py` pour
la règle inverse).

Le motif qui a produit ces neuf déplacements vaut d'être noté, parce qu'il s'est répété
identiquement : **la barrière n'a jamais été la logique, toujours un paramètre.**
`_persist(state, …)` prenait un `UiState` ; `_chat` lisait `state.chats` ; `_overview` lisait
`state.runs`. Trois fois, un objet de console dans une signature était la seule raison qu'un
terminal ne puisse pas appeler la fonction. `app_mail.check` n'en avait aucun et son extraction
a coûté un fichier et une commande.

## Un vrai tour, sur la vraie configuration

La liste de vérification du plan demande « un vrai tour sur la vraie entreprise ». Lancé sur une
copie de `vigil` en mode mock — pour ne rien dépenser ni toucher à l'état du propriétaire —
24 ticks, dix agents, aucune erreur. Ce que ça a prouvé et qu'aucun test unitaire ne prouve :

| | |
| --- | --- |
| Schéma | **18**, migré en place sur un store neuf |
| Tours rédigés portant leur trace | **12**, avec le modèle qui a répondu |
| Actions sans trace | 61 — celles qui n'ont appelé aucun modèle, `NULL` comme prévu |
| `promesse-clinique` | **24 usages en 24 ticks** |

Les deux dernières lignes valent d'être lues ensemble. `routing_health` répond enfin à « qui a
répondu » — `haiku` 6 fois, `gemma4:e4b` 5, `sonnet` 1 — et c'est précisément la visibilité dont
l'absence a coûté 365 026 jetons. Et `promesse-clinique` à 24 sur 24 confirme sa déclaration
`always:` par la mesure : elle est bien sur chaque prompt. Le curateur a donc de vraies données,
et n'archivera aucune des trois compétences de `vigil`, qui sont toutes en usage.

Un tour contre de vrais fournisseurs reste à l'opérateur : il dépense ses jetons.

## Le cliquet

Chaque règle embarque l'ensemble exact des violations d'aujourd'hui et affirme
`constaté == déclaré`. Une violation nouvelle échoue, **et une violation corrigée sans être
rayée de la liste échoue aussi** — sinon la liste pourrit en vœu. C'est la mécanique des
autres registres du projet, appliquée à l'architecture.

Ces listes sont le compteur d'avancement de la restructuration. Elles ne peuvent que
raccourcir, et l'état courant se lit d'une commande :

```bash
python -m pytest tests/test_layers.py tests/test_import_cost.py -q
```

## Le coût d'import, séparément

`tests/test_import_cost.py` mesure ce que chaque module **traîne derrière lui**, dans un
interpréteur neuf — parce que `sys.modules` est global et qu'un test qui a déjà importé
`requests` passerait pour la mauvaise raison.

C'est le test d'acceptation de trois étapes de la restructuration : les lignes de
`settings_spec`, d'`agents` et de `llm` doivent maigrir, et le test dit exactement de combien.

## La couverture par fichier

`coverage report --fail-under=72` lit **un** nombre pour tout le paquet, et un nombre ne voit
pas un module passer de 88 % à 30 % pendant que la moyenne tient. Chaque fichier porte donc
son propre plancher dans `tests/coverage-baseline.json`, vérifié par
`packaging/coverage_ratchet.py` — que la CI lance juste après la porte globale.

Un fichier sans plancher **échoue** : quand un module se découpe, ses morceaux pourraient être
à 0 % sans que rien ne le remarque. Il faut passer `--update`, ce qui met les nouveaux
chiffres dans un diff qu'un humain lit.
