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

Étapes 1 à 7 faites, l'étape 8 commencée par son contrat. Les sept dossiers du plan existent —
`kernel/`, `config/`, `store/`, `providers/`, `tools/`, `app/`, `api/` — plus `cli/`. Mesuré :

| Compteur | Au plan | Aujourd'hui |
| --- | --- | --- |
| **Arêtes montantes** | 4 | **0** |
| **Cycles d'imports** | 5 | **0** |
| Modules important `subprocess` | 4 | **1** (`kernel/proc.py`) |
| Ce que charge la lecture d'un réglage | `requests`, `subprocess`, `ssl`, `sqlite3` | **`sqlite3`** |
| Ce que charge la lecture de la liste des outils | + `smtplib`, `imaplib` | **rien** |
| Modules à plat | 53 | **27** |
| Choses que la console sait faire et la CLI non | 11 | **3**, toutes cosmétiques |
| Commandes CLI | 27 | **33** |
| Routes sous contrat versionné | 0 | **1** sur 55 |
| Registres avec les deux bouts tenus | 1 | **3** (outils, routes, commandes) |
| Instructions non testées de la CLI | 216 | **65** |

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

Neuf services sont descendus et neuf paires sont sous cliquet. Les trois écarts qui restent
sont cosmétiques ou déjà couverts autrement : le thème de la console, les charges utiles de
rendu (`settings_payload`, `providers_payload`, `company_payload`), et `ollama_pull` /
`claude_setup`, dont les cousins `bench` et `claude` existent déjà côté ligne de commande.

Le motif qui a produit ces neuf déplacements vaut d'être noté, parce qu'il s'est répété
identiquement : **la barrière n'a jamais été la logique, toujours un paramètre.**
`persist(ui, …)` prenait un `UiState` ; `chat` lisait `ui.chats` ; `overview` lisait
`ui.runs`. Trois fois, un objet de console dans une signature était la seule raison qu'un
terminal ne puisse pas appeler la fonction. `app_mail.check` n'en avait aucun et son extraction
a coûté un fichier et une commande.

### La seconde moitié : `webui.py` n'existe plus

1 881 lignes en six modules qui s'importent en ligne droite et jamais en arrière :

| Module | Lignes | Ce qu'il porte |
| --- | --- | --- |
| `api/state.py` | 84 | `UiState` — et rien de ce qu'il tient ne survit à un redémarrage |
| `api/contracts.py` | 75 | `Ctx` et `Route`, deux formes de données |
| `api/adapters.py` | 551 | la moitié console de chaque cas d'usage |
| `api/handlers.py` | 877 | 57 fonctions, une par point d'entrée |
| `api/routes.py` | 120 | la table |
| `api/server.py` | 302 | le serveur stdlib et les contrôles avant un gestionnaire |

**Par couche, pas par page.** Un `handlers/settings.py` et un `handlers/site.py` auraient
recréé le fichier-dieu une fois par onglet ; ce qui garde `handlers.py` lisible, c'est que la
réflexion est dans `app/` et que les points d'entrée sont des adaptateurs.

`contracts` est un module séparé de `routes` pour une seule raison, et elle est structurelle :
un `Route` défini à côté de `ROUTES` ferait importer par `handlers` la table qui l'importe.
C'est la forme des cinq cycles que ce chantier a supprimés — et **à l'intérieur d'un même rang,
les rangs ne l'auraient pas vu**, ce qui est exactement pourquoi `KNOWN_CYCLES` existe.

Trois choses que le déplacement a rendues plus vraies que « déplacées » :

**Le tiret bas des 57 gestionnaires est parti.** Il n'existait que parce que tout vivait dans
un fichier de 2 468 lignes, où `_route_meta` distinguait un gestionnaire de ses voisins. Dans
un module dont chaque fonction est un gestionnaire, c'était le nom du module, répété 57 fois.
Et le cliquet en est plus fort : `tests/test_route_table.py` ne cherche plus un motif de nom,
il compare « défini ici » à « dans la table », et lit le **module** au lieu d'un chemin — sa
première version lisait `Path("corparius/webui.py")`, ce qu'un déplacement transforme en scan
vide. Trois tests de cette suite lisaient un chemin au déplacement précédent et les trois ont
cassé ; c'est la deuxième fois, et c'est le correctif qui la termine.

**Sept alias sont morts.** `MAX_BODY`, `_LOOPBACK`, `_host_only` étaient des ré-exports de
`kernel/httpkit` ; `_CEO_ACTIONS`, `_CEO_SCHEMA`, `PAUSABLE`, `_apply_directives` de
`app/directives`. Chacun existait parce qu'un appelant l'épelait ainsi. Les appelants bougeant
dans le même commit, ils épellent maintenant la vraie maison.

**`state` ne désigne plus qu'une chose.** Dans `api/`, `state` est le module et `ui` est l'objet
de la console — parce que `fresh_settings`, `companies` et `load_company` sont monkeypatchés par
les tests, et **un nom importé dans trois modules a trois points de patch** : on en patche un et
les deux autres gardent la vraie fonction, en silence. Les atteindre par `state.X` n'en laisse
qu'un. C'est la même classe de défaut que le reste du chantier a trouvée ailleurs, mais dans un
test au lieu du produit : une garantie qui s'affaiblit sans un mot.

## L'étape 7 : la CLI devient un registre

1 120 lignes, 29 commandes, et un `main()` de **203 lignes** qui était l'arbre argparse entier.
Découpé par groupe de commandes, nommé par ce que le groupe *fait* :

| Module | Commandes |
| --- | --- |
| `cli/lifecycle.py` | `new` `init` `repo` `delete` — quelles entreprises existent |
| `cli/operate.py` | `run` `status` `flow` `board` `ceo` |
| `cli/backlog.py` | `tasks` `task` `approvals` `approve` `reject` `inbox` |
| `cli/publish.py` | `site` `deploy` |
| `cli/configure.py` | `set` `memory` `rules` |
| `cli/prove.py` | `preflight` `bench` `claude` `mail` — une clé posée n'est pas un modèle qui répond |
| `cli/maintain.py` | `doctor` `backup` `restore` `update` — agit sur l'installation, pas sur une entreprise |
| `cli/console.py` | `ui` |

**Chaque groupe enregistre ses propres parseurs**, et c'est ça le gain, pas le compte de lignes.
Un groupe se lit de bout en bout — les commandes, leurs drapeaux et leurs textes d'aide dans un
seul fichier — là où l'implémentation d'une commande et ses drapeaux étaient quatre cents lignes
plus loin. C'est comme ça que `--company` a fini écrit vingt fois.

**Et la CLI devient le troisième registre dont les deux bouts sont tenus**, après les outils et
la table de routes. `tests/test_cli_registry.py` : chaque `cmd_*` qu'un groupe définit est
atteignable depuis la table des parseurs, et chaque parseur nomme un `cmd_*` qui existe. Les deux
défaillances sont celles que ce projet a déjà trouvées neuf fois ailleurs — une commande que
personne n'a enregistrée est du code mort que rien ne signale ; un `set_defaults(fn=…)` oublié est
un `AttributeError` pour la première personne qui tape cette commande, dans un terminal.

Rien de tout ça n'était vérifiable avant. `main()` construisait l'arbre et parsait d'un seul
souffle, donc la seule façon de voir ce qui était enregistré était de lancer une commande.
`build_parser()` est toute la différence.

### Le test d'acceptation : `--help` des 33 commandes, octet pour octet

Capturé avant le découpage, comparé après. La sortie d'argparse porte le nom du programme, chaque
drapeau, chaque valeur par défaut et chaque texte d'aide, donc un dump identique est une
affirmation plus forte que n'importe quelle assertion que j'aurais pensé à écrire : **c'est le
même arbre**. Les 33 aides par commande sont identiques ; la seule différence est l'ordre du
listing de haut niveau — et il est maintenant *choisi*. L'ancien était l'ordre d'accrétion, ce
qui plaçait `new`, la première commande que quiconque tape, vingt-cinquième sur vingt-neuf.

### Ce que le cliquet par fichier a rendu visible

`cli.py` mesurait 52 % en un bloc, ce qui ne disait rien de *quelle* moitié. Découpé :

| Module | Avant | Après |
| --- | --- | --- |
| `cli/maintain.py` | 25,9 % | **99,1 %** |
| `cli/prove.py` | 50,0 % | **88,8 %** |
| `cli/configure.py` | 53,9 % | **89,6 %** |
| `cli/backlog.py` | 66,4 % | **96,8 %** |

**25,9 % pour les deux commandes qui remplacent le binaire en cours et remplacent les entreprises
et le store.** Les modules dessous étaient testés ; ce qui ne l'était pas, c'est la *commande* —
l'ordre dans lequel elle fait les choses, ce qu'elle refuse, et ce qu'un shell voit. Trois
propriétés, chacune avec une façon d'être fausse qu'un test de module ne peut pas attraper :

1. **Un refus sort non-zéro.** `corparius deploy` a imprimé « no provider succeeded » et sorti 0
   pendant des mois. Un script autour de `update` lit le code de sortie, pas la prose.
2. **L'invite vient après le rapport et avant l'écriture.** On confirme une restauration en ayant
   lu ce que l'archive contient ; demander d'abord serait la confirmation de rien.
3. **Répondre non n'appelle rien.** Pas « annule » — ne commence jamais. Affirmé en faisant
   échouer le test si la fonction destructrice est atteinte du tout.

Et une propriété d'honnêteté, reprise mot pour mot d'un commentaire de `cmd_preflight` : dire
« retenu » après n'avoir rien appelé « prétendrait à une connaissance qui n'existe pas, ce qui est
la défaillance que toute cette commande existe pour terminer ». Le commentaire est maintenant un
test. Même chose pour la garde par nom de `approve --always` : un outil listé dans `hitl_tools`
continue de demander quel que soit le nombre d'approbations — un seul `if`, non testé, et ce
qu'il protège est la table des règles permanentes, celle qui survivait à la suppression d'une
entreprise.

**Non testé, dit plutôt que passé sous silence** : `cli/lifecycle.py` reste à 66,1 %, et c'est
`cmd_repo` — quatre chemins qui appellent `git` par `companyrepo`. Total de la CLI : 216
instructions non testées avant, **65** après.

## L'étape 8 a commencé par sa brique la moins spectaculaire

`GET /api/v1/meta` est la première route versionnée du produit, et c'est celle qu'un second
client ne peut pas ne pas avoir. Elle est dans `app/meta.py` — rang 5, donc appelable par un
terminal autant que par un socket — et le transport n'en tient que la ligne qui l'enregistre.

Ce qu'elle rend possible tient en deux phrases. Un client compare `api_version` et **refuse**
un cœur trop vieux pour lui, au lieu d'échouer une requête à la fois. Et il lit
`capabilities` pour cacher un bouton, au lieu de découvrir un 404 — ce qui n'est utile que
parce que chaque capacité est *résolue* depuis la configuration : `mail` est vrai quand un
compte est configuré, pas quand le code sait envoyer un courriel.

**Et ce fichier a failli casser une règle du projet.** Sa première version demandait à
`stripe_check()` si les paiements marchaient — c'est-à-dire lisait le solde Stripe en direct,
depuis un point conçu pour être sondé. La règle contre la sonde réseau depuis un point sondé a
justement été écrite après que `/api/providers` ouvrait une socket à chaque rafraîchissement.
Corrigé avant le commit en une question de configuration ; savoir si une clé posée *marche*
reste la question de `corparius doctor`, qui est posée quand un exploitant la pose.

Le test l'a d'abord mal défendue, et l'erreur mérite d'être écrite parce que c'est la
huitième fois de ce chantier que j'écris l'invariant avant de regarder ce qui se passe :
`test_the_capabilities_open_no_socket` passait par le client HTTP de test et attrapait **la
requête elle-même**. Une requête *est* une socket. Il appelle maintenant le service
directement, ce qui est le seul endroit d'où la propriété est mesurable.

Le reste de l'étape est déclaré, pas fait : 54 routes non préfixées sont un ensemble *déclaré*
dont `tests/test_api_version.py` épingle le compte, donc une 55e hors de `v1` est une ligne
délibérée. `durable_jobs` répond `false` — la chose dont un second client a le plus besoin et
qu'il ne peut pas encore avoir, dite plutôt qu'omise.

Et le smoke du binaire gelé touche cette route. C'est de l'économie de garde : `capabilities`
résout depuis `providers`, `config` et `store`, donc **une requête prouve que les sept
sous-paquets s'importent** sous PyInstaller — un import paresseux que son analyse a manqué
échoue en CI et non au premier clic d'un exploitant.

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
