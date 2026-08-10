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
| Modules à plat | 53 | **26** |
| Choses que la console sait faire et la CLI non | 11 | **3**, toutes cosmétiques |
| Commandes CLI | 27 | **33** |
| Routes sous contrat versionné | 0 | **13** sur 67 |
| Registres avec les deux bouts tenus | 1 | **4** (outils, routes, commandes, codes d'erreur) |
| Divergences entre appelants trouvées | — | **4**, toutes fermées par un service partagé |
| Chaînes d'interface | 516 dans le HTML | **525 en JSON**, deux langues, jeux de clés égaux |
| Collisions de préfixe i18n | 3 | **0**, et c'est une assertion |
| Instructions non testées de la CLI | 216 | **65** |
| Octets de la ressource sondée | 48 530 | **2 859** (et 0 si rien n'a changé) |
| Ce qui survit à un redémarrage de la console | rien | **les tours**, schéma 19 |
| Identifiants d'accès | 1 partagé | **un par appareil**, révocable, avec portée |
| Schéma | 16 | **20** |

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

## L'étape 8, deuxième et troisième briques : l'enveloppe et les ressources étroites

### Ce que 57 charges utiles disaient

Mesuré sur `api/` : **57 charges utiles portent une clé `error`, et les 57 portent une phrase en
anglais.** 32 sont des littéraux (« no run in progress »), 11 sont `str(exc)`, 8 des f-strings. Un
second client ne peut rien en faire sauf comparer des sous-chaînes, ce qui casse dès qu'on
reformule un message — et reformuler un message pour une personne, ce projet le fait souvent et
exprès.

`{"ok": false, "error": {"code", "message", "detail"}}` sépare les trois destinataires : le code
est pour le client, le message pour la personne, et `detail` porte les particularités
(quelle entreprise, quelle clé, combien d'octets) au lieu qu'elles soient soudées dans la prose.

**Les 54 routes historiques gardent la chaîne plate, et c'est une décision.** La page livrée lit
`data.error` comme une chaîne à quatorze endroits — `throw new Error(data.error || …)` — donc un
objet s'y afficherait « [object Object] » précisément sur les échecs qu'un exploitant a le plus
besoin de lire. Reconstruire cette page, c'est l'étape 9. Une forme qui diffère par version,
c'est *la définition* du versionnement.

Le vocabulaire est fermé et les deux bouts sont tenus. **Et la deuxième moitié a servi tout de
suite** : la première version de la liste contenait aussi `refused` et `conflict`, et le test les
a signalés comme jamais envoyés — à raison, aucune route v1 n'accepte encore de POST. C'était un
vocabulaire écrit pour des routes imaginaires. Deux mots de plus ont failli passer autrement :
`invalid` et `too_large` étaient calculés dans une variable, donc invisibles au scan — un code
que l'AST ne voit pas est un code que personne ne peut grepper non plus. Écrits en clair.

### 48 530 octets toutes les cinq secondes

Mesuré clé par clé sur la vraie entreprise, trois clés font **94 %** :

| Clé | Octets | Part |
| --- | --- | --- |
| `tasks` | 21 115 | 43,5 % |
| `memory` | 17 706 | 36,5 % |
| `recent_actions` | 6 765 | 13,9 % |
| les 26 autres ensemble | 2 944 | 6,1 % |

D'où quatre parties dans `app/overview.py` — `summary`, `tasks`, `memory`, `activity` — et
`summary` fait **2 859 octets**, soit **17,0× moins** que ce que la page sonde. Vérifié sur la
machine réelle, pas déduit.

**La mesure a changé la forme du découpage.** Le plan nommait `/approvals` et `/inbox` comme
ressources séparées ; mesurées, elles font 613 octets à deux, et ce sont les deux choses qu'un
exploitant ne doit pas avoir à redemander. Découper sur la supposition du plan plutôt que sur le
nombre aurait coûté deux allers-retours pour ne rien gagner.

`build` est inchangé et vaut exactement l'union des quatre parties. **Et le premier test qui
l'affirmait était vide** : `build` *est* `{**summary, **tasks, **memory, **activity}`, donc
comparer ses clés à l'union des parties compare une chose à elle-même — il passait pendant que
`activity` renvoyait `{}`. Trouvé en réintroduisant le défaut, ce qui est la seule raison pour
laquelle les jeux de clés sont maintenant *déclarés* au lieu d'être dérivés.

### L'ETag, et ce qu'il économise vraiment

Chaque GET v1 porte un validateur ; `If-None-Match` répond 304 sans corps. Sur la vraie
entreprise : `/api/v1/memory` passe de 17 754 octets à **0**.

Ce que ça économise est **la bande passante, pas le travail** : la charge est construite puis
hachée, donc un 304 a quand même fait la requête. C'est écrit à côté du code, parce que « un
client au repos ne paie rien » serait la surenchère facile. Ce qui rend la requête petite, c'est
de réduire ce que le client sonde.

Un détail qui compte : `Cache-Control` passe à `no-cache` sur les GET v1 et reste `no-store`
ailleurs. `no-store` interdit de garder la copie, ce qui rendrait la revalidation impossible — le
client n'aurait rien à revalider et l'ETag serait de la décoration. `no-cache` veut dire « garde
et redemande avant de réutiliser ».

### Deux défauts trouvés en fumant les nouvelles routes

**`/api/overview?company=nope` répondait 200** avec une charge complète décrivant une entreprise
au tick 0 sans rien fait : « il n'y a pas d'entreprise comme ça » et « cette entreprise n'a rien
fait » étaient la même réponse. `corparius status` a toujours refusé cette entrée, donc les deux
appelants du même savoir divergeaient — et `test_two_callers_agree` ne pouvait pas l'attraper,
parce qu'il demande quel service chaque côté atteint et les deux atteignent celui-là. La forme
reste la phrase historique ; seul le statut change.

**Un test de sécurité intermittent.** La suite a échoué une fois sur deux mille sur
`test_rebinding_is_blocked_on_writes_too`. Le contrôle de Host refusait sans lire le corps
annoncé, et fermer sur des données non lues envoie un RST qui peut emporter la réponse — le
danger exact que le code énonce deux lignes plus bas, pour le 401. Un refus de sécurité que le
client ne reçoit parfois pas est le pire genre d'intermittent. Corrigé, et la première version du
test qui l'affirmait ne mesurait rien : elle envoyait deux requêtes sur une connexion en supposant
du keep-alive, et ce serveur est en **HTTP/1.0**. Neuvième fois de ce chantier que j'écris
l'invariant avant de regarder ce que le produit fait.

### Un cliquet corrigé plutôt que contourné

Le plafond « un adaptateur de console reste petit » comptait des **lignes**, et il a sauté à 33
sur une fonction de **quatre instructions** dont la docstring explique le défaut ci-dessus. Un
plafond qui punit le fait de l'écrire pousse contre la règle du projet : les docstrings portent
les mesures, et les perdre est la seule chose que le plan interdit explicitement. Il compte des
instructions maintenant, seuil 20 — mesuré : les neuf paires vont de 1 à 17, et le 17 est
`start_run`, qui est du vrai travail de console.

## L'étape 8, quatrième brique : le travail survit au processus

`UiState.runs` est un dictionnaire dans le processus de la console. Un tour lancé depuis un
téléphone disparaissait au redémarrage **sans trace qu'il ait existé**, et
`capabilities.durable_jobs` répondait `false` pour exactement ça. Schéma 19 : une table `jobs`, et
le drapeau répond `true`.

### Trois refus de deviner

**Un travail interrompu est `interrupted`, jamais repris.** Au démarrage, un travail encore marqué
`running` que ce processus ne possède pas passe à `interrupted`. Le reprendre en silence
revendiquerait les ticks qu'il n'a pas faits et la frontière de journée qu'il n'a pas banquée. Et
la console le dit en mots : « The console stopped while this run was in progress. Nothing was
resumed; start it again when you are ready. »

**La propriété est un jeton par processus, pas le PID.** Le plan disait `owner_boot` ; il n'y a pas
d'identifiant de démarrage portable dans la bibliothèque standard — `/proc/sys/kernel/random/boot_id`
n'a pas d'équivalent Windows, et ce projet livre sur trois OS. Le PID seul est *pire que rien* ici :
les PID sont réutilisés, donc une nouvelle console qui hérite du numéro de l'ancienne déciderait que
l'orphelin est le sien et rapporterait un tour mort comme vivant, indéfiniment. `owner_token` est un
jeton aléatoire frappé une fois par processus, ce qui répond exactement à « est-ce le mien ».
`owner_pid` reste à côté, pour une personne qui lit la table, et n'est jamais ce qu'on compare — et
il n'est pas publié dans l'API, parce qu'une valeur qui commande une transition d'état n'a rien à
faire dans une réponse.

**L'annulation est durable, et l'`Event` en mémoire reste.** `cancel_requested` est une colonne
parce que le client qui arrête un tour n'est pas le processus qui le fait tourner. `should_stop` lit
les deux : l'événement arrive en microsecondes pour le bouton de la console, la colonne en un tick
pour tout le monde d'autre. Ce paramètre était **déjà** injecté — `orchestrator.run` le sonde à
chaque tick et à chaque frontière de journée — donc ça a coûté un lambda.

### Ce que le test a trouvé avant les utilisateurs

**L'ordre de la clé d'idempotence était inversé.** `start_run` vérifiait d'abord la garde « un tour
est déjà en cours », puis la clé. Donc un téléphone qui réessayait la requête qu'il venait de faire
se faisait répondre « un tour est déjà en cours » — *par son propre tour*. Exactement la situation
que la clé existe pour rendre inoffensive, répondue avec l'erreur qu'elle existe pour éviter. La
clé se consulte maintenant en premier, et `job_for_key` existe pour ça.

**Et le premier test du redémarrage ne pouvait pas marcher.** Il montait deux serveurs dans le même
interpréteur, ce qui ne prouve rien : `OWNER` est frappé par processus — à raison, puisque
`shutdown()` sur un objet serveur ne tue pas le thread qui fait tourner les ticks. Deux
`build_server` dans un interpréteur sont **un** propriétaire. Le test tue maintenant un vrai
sous-processus, ce qui est la seule version honnête de « la console a disparu » — et c'est mot pour
mot la cinquième vérification du plan.

Conséquence qui vaut d'être notée : ce test, le plus soigneux du fichier, **ne contribue rien à la
couverture** — ses assertions tournent dans un autre interpréteur, donc la branche `interrupted`
de `app/runs.py` se lisait comme non testée. Les mêmes propriétés sont donc aussi affirmées en
processus, un niveau plus bas. `app/runs.py` 100 %, `store/jobs.py` 99,1 %.

### Une capacité gagnée dans les deux sens

`corparius run` enregistre son travail comme n'importe quel autre. Sans la ligne, `corparius status`
dans un autre terminal — ou la console, ou un téléphone — rapporterait « pas en cours » pendant que
ce processus est en plein tick : le même fantôme que le travail v1 a retiré de `/api/overview`. Et
un tour lancé au terminal est maintenant arrêtable depuis n'importe où, parce que `should_stop` lit
la colonne. Deux terminaux ne peuvent plus lancer la même entreprise en même temps non plus — ce
n'était vérifié nulle part : la console vérifiait sa propre mémoire et la CLI ne vérifiait rien.

`app/runs.py` est au rang 5 et pas dans `api/adapters.py` précisément pour ça : la vue durable est
la même pour les deux appelants, ce qui est le motif de l'étape 6 appliqué à une capacité neuve.

## L'étape 8, dernière brique : un appareil, pas un secret partagé

`CORP_UI_TOKEN` est un secret partagé sans nom, sans portée, et qu'on ne peut pas retirer à un
téléphone sans le changer pour le portable. Schéma 20 : une table `clients`. Mais la table n'est pas
la partie intéressante — c'est ce qui a dû se resserrer autour d'elle.

### Le palier qui devenait porteur

Le contrôle d'origine avait trois paliers et le troisième disait « ni `Sec-Fetch-Site` ni `Origin`
⇒ autorisé ». Le code disait pourquoi, et il avait raison : c'est ce qui fait marcher curl, le smoke
de la CI, le `HTTPConnection` de la suite et le serveur MCP sans configuration.

**Mais une application native n'envoie ni l'un ni l'autre non plus.** Dès qu'un second client est
réel, ce palier cesse de vouloir dire « pas un navigateur, donc local » et devient la porte par
laquelle passe une écriture distante. Il exige maintenant le loopback — vérifié sur l'adresse du
pair, que l'appelant ne peut pas fabriquer — ou un appareil appairé.

Un test qui aurait vérifié ça de bout en bout n'aurait rien vérifié : sur cette suite la connexion
*est* en loopback, donc elle fournit elle-même la chose testée. `_same_origin` est donc interrogé
directement avec une adresse de pair distante. C'est le même piège que le drain du corps deux
commits plus tôt, reconnu à vue cette fois.

### SHA-256 et pas scrypt — [ADR 0009](adr/0009-sha256-pour-un-jeton-d-appareil.md)

Le plan disait scrypt, « la primitive que `secretbox` utilise déjà ». Mesuré avant de choisir :

```text
scrypt n=2**14 r=8 p=1    87,1 ms    ~16 MiB par appel
sha256                     0,0014 ms
```

Un facteur 62 000, à chaque requête authentifiée d'une API sondée. Une KDF mémoire-dure existe pour
rendre chères les devinettes à **faible entropie** ; l'entrée ici est `token_urlsafe(32)` — 256 bits
— générée par nous et **jamais acceptée d'un appelant**. scrypt n'achète rien contre 2^256, et ce
qu'il coûterait est un levier de déni de service offert à un appelant non authentifié : 87 ms et
16 MiB par tentative. `secretbox` garde scrypt et doit le garder, parce que là l'entrée est une
passphrase humaine. Même primitive, question différente.

### TLS : non, et un échec du doctor pour que ce soit honnête

`http.server` plus un certificat auto-signé est une catastrophe d'expérience sur iOS et apprendrait
aux exploitants à cliquer à travers les avertissements. La décision du plan est le tunnel — et une
décision de ne pas faire quelque chose n'est honnête que si quelque chose vérifie. Le doctor
**échoue** quand un appareil appairé coexiste avec une écoute hors loopback sans TLS : un jeton
d'appareil est un identifiant porteur, donc il est dans chaque requête sur le fil.

`CORP_UI_BEHIND_TLS` est une **affirmation** de l'exploitant, pas une détection, et le docstring le
dit : vu de l'intérieur du processus, une requête venue d'un proxy local et une venue d'un portable
au fond d'un café sont identiques. Prétendre détecter serait mentir.

Les deux nouvelles clés sont des clés d'amorçage, et la phrase que `CORP_UI_ALLOWED_HOSTS` portait
déjà se reprend mot pour mot : **un contrôle de sécurité ne doit pas être modifiable par la surface
qu'il protège.** Une écriture inter-sites réussie sur `/api/settings` qui pourrait ajouter sa propre
origine désactiverait la défense définitivement.

## L'étape 9, première moitié : `sitegen/`

1 339 lignes en un module, huit maintenant, et les imports vont dans un sens :
`base` ← `palette`, `copy` ← `style`, `head`, `sections` ← `companions` ← `build`.

| Module | Lignes | Ce qu'il porte |
| --- | --- | --- |
| `base` | 7 | `esc` et `norm`, les deux que tous les autres appellent |
| `palette` | 181 | la couleur, et le contraste **calculé** plutôt que supposé |
| `copy` | 239 | ce que la page dit, et les deux choses qu'elle refuse d'écrire |
| `style` | 182 | la feuille de style, émise depuis une palette |
| `head` | 129 | les balises qu'un visiteur ne voit jamais et qu'un robot lit d'abord |
| `sections` | 174 | les blocs optionnels, absents sauf si la config les fournit |
| `companions` | 114 | `robots.txt` et `sitemap.xml`, qui sont des fichiers et pas des balises |
| `build` | 241 | une page, assemblée |

**L'étape 9 refait la console, pas ça.** Une page de vente générée n'a pas de framework et n'en
veut pas : elle est lue par un inconnu sur un téléphone en un aller-retour, et chaque octet est
inline exprès. La décision Vite + Svelte concerne `webui.html`, qui est un autre programme qui se
trouve être écrit dans le même langage.

### Le test d'acceptation : la même page, au bit près

Le site de `vigil` construit par le module de 1 339 lignes et par le paquet de huit :
**17 499 octets, `sha256 5c5c3f64ab84889e33ecf7632102bc5c`**, les deux. Construit dans deux arbres
séparés — l'ancien extrait de `git archive HEAD` — parce que comparer un artefact au même artefact
est le piège que ce chantier a déjà attrapé une fois.

### Des imports de noms, pas de modules — et c'est l'inverse de `api/`

Dans `api/`, `handlers.overview` et `adapters.overview` étaient deux vraies fonctions avec un même
nom : le préfixe de module était la seule façon de les distinguer. Ici, chaque nom est unique sur
les huit fichiers — et **trois des noms de modules (`base`, `head`, `palette`) sont déjà des
variables locales** dans le code déplacé, donc qualifier aurait fait résoudre `head.opening(...)`
contre une chaîne de caractères. Mesuré sur l'original avant de choisir, plutôt que découvert une
erreur mypy à la fois.

### Trois fois la même leçon sur la prose

L'outil de découpage a lu du commentaire comme du code, trois fois, et chaque fois d'une manière
différente :

1. une substitution par regex a réécrit `/* The signature: bars whose heights... */` en
   `/* The palette.signature: ... */`, et « earn the same contrast through tracking » en « the
   same palette.contrast through » ;
2. la détection des imports a demandé à `base` d'importer `strings` depuis `copy`, parce que la
   docstring de `norm` contient « whether two strings say the same thing » ;
3. puis elle a demandé `opening` à `copy`, parce que `_unwrap` contient
   `for opening, closing in _WRAPPERS` — un local qui partage un nom n'est pas une référence.

Les trois sont corrigés par la même chose : **tokeniser, et retirer ce que le corps lie lui-même.**
C'est la leçon du renommage `state` → `ui` dans `api/`, apprise là-bas et oubliée ici le temps
d'une itération. Les commentaires portent les mesures qui justifient les décisions — c'est
précisément pourquoi ce découpage déplace des plages de lignes au lieu de réémettre un AST, donc
les abîmer annulerait la méthode.

### Ce que le cliquet par fichier a trouvé, encore

`sitegen.py` mesurait 84,5 % en un bloc. Découpé, `sections.py` sortait à **56,2 %** — et la moitié
non testée était celle qui **écrit des affirmations sur une page qu'un client lit**. C'est là que
vivent les deux règles dures du générateur, et les deux ont été écrites après qu'une page les a
enfreintes en production :

- une affirmation sans source est déposée — « la forme lisible par machine du témoignage inventé :
  ça ressemble à une preuve et ça n'en est pas » ;
- une citation sans nom est déposée — « une citation non attribuée sur une page commerciale est une
  fabrication avec des guillemets autour ».

Aucune des deux n'était testée. 97,7 % maintenant, et les deux prouvées non vides en republiant ce
qu'elles refusent. Une de mes assertions décrivait au passage une commodité que le produit refuse
exprès : un slug de page manquant n'est **pas** dérivé du titre, parce qu'un slug est une URL et un
nom de fichier — le dériver du titre ferait bouger l'adresse à la prochaine réécriture du titre.

## L'étape 9, deuxième moitié : les 525 chaînes deviennent des données

Le plan est explicite sur l'ordre : les chaînes d'interface partent **verbatim et avant** le
framework, parce qu'une clé perdue pendant une reconstruction ressemble à un bug de style.
`web/i18n/en.json` et `fr.json` sont la source de vérité ; la page livrée en garde une copie
générée depuis eux, et `tests/test_i18n.py` les tient ensemble tant que les deux existent.

525 clés par langue — le plan disait 516, elle a grossi — et les deux jeux étaient déjà égaux.

### La collision qui a envoyé « Diagnostics » sur la carte Documents

Le plan la cite comme la classe de bug que ce travail supprime, trouvée seulement par une vraie
capture d'écran. Mesurée sur la table réelle, elle était toujours là :

| Espace de noms | Sens | Clés |
| --- | --- | --- |
| `doc.` | **Diagnostics** | 5 |
| `docs.` | **Documents** | 40 |
| `co.` | l'éditeur d'entreprise | 36 |
| `col.` | les colonnes du kanban | 10 |
| `conn.` | l'erreur de connexion | 1 |

Trois paires où l'une commence l'autre : `co`/`col`, `co`/`conn`, `doc`/`docs`. Deux espaces à une
lettre près, voulant dire des choses entièrement différentes — quelqu'un chargé de changer « le
titre de Documents » attrape `doc.title` une fois sur deux, et un regroupement par préfixe sans le
point ramasse les deux ensembles à la fois.

`doc.` → `diag.`, `co.` → `company.`. 43 espaces de noms, aucun préfixe d'un autre, **et c'est
l'assertion** — la confusion ne peut plus revenir, elle n'est pas seulement corrigée.

### Ce qu'un cliquet ne peut pas être ici

128 clés ne sont référencées nulle part littéralement, et ce n'est **pas** une trouvaille : douze
recherches construisent leur clé à l'exécution — `t("ib." + m.kind)`, `t("col." + key)`,
`t("prov.pf." + p.state)`. Un scan statique les compterait mortes. Donc il n'y a pas de cliquet
« chaque clé est utilisée », et c'est écrit dans le fichier de test : **une garde qui sur-rapporte
se fait ignorer, et une garde ignorée est pire que pas de garde.** Ce qui est vérifiable l'est :
chaque clé littérale que la page demande existe dans les deux langues, et chaque préfixe calculé a
au moins une clé.

### Le premier test que Python ne pouvait pas écrire

Le bloc `const I18N` est maintenant **généré**. Un générateur qui émet une virgule en trop produit
une page dont tout le script échoue à s'analyser — la console s'affiche en balisage nu, sans aucun
comportement — et **toute** la suite Python passerait quand même, parce qu'aucun test n'exécute de
JavaScript.

`tests/test_page_javascript.py` : `node --check` sur les 3 325 lignes de script, puis le `t()` de la
page évalué par le vrai moteur pour vérifier qu'aucune chaîne ne s'afficherait comme une clé brute.
Écrire cette expression une deuxième fois en Python aurait voulu dire lui faire confiance pour
rester en phase avec celle qui est livrée.

Sauté là où node est absent, et ce n'est pas un compromis : **l'exécution ne doit jamais en avoir
besoin.** Le wheel et le binaire gelé servent cette page sans Node installé, ce que le plan exige
explicitement. Node est un outil de développement et de CI.

Deux corrections en passant. Deux tests affirmaient `"col.proposedCeo":"Proposed, for the CEO"` —
sans espace après les deux-points — donc ils épinglaient l'orthographe minifiée du bloc et non la
chaîne ; ils lisent les données maintenant. Et `subprocess` a besoin de `encoding="utf-8"`
explicite : `text=True` décode avec la page de code locale, cp1252 sur Windows, qui ne peut pas
lire le français — l'échec n'est pas une exception dans le test, c'est un thread lecteur qui meurt
dans `subprocess` et `stdout` qui arrive à `None`.

## L'étape 9, troisième moitié : le premier onglet, et le quatrième écart

L'onglet Vue d'ensemble est reconstruit avant le shell et les tokens, délibérément : un cadre vide
mais stylé dit moins sur la justesse de la direction qu'une page qu'un opérateur peut lire.

Il lit `summary` (**2 859 octets**, contre les 48 530 que l'ancienne page allait chercher toutes les
cinq secondes) et `jobs`, et il écrit vers `approvals`, `inbox` et `runs`. Ces trois écritures sont
passées en v1 **parce que cet onglet en avait besoin**, ce qui est la règle du plan — les lectures
d'abord, parce que c'est là qu'était le coût ; les écritures quand un client v1 a une décision à
prendre. Il y en a un maintenant.

### Le quatrième écart, et c'est celui qui coûtait le plus cher

En descendant `POST /approvals` dans `app/approvals.py`, la comparaison des trois surfaces a donné
ceci — mesuré, pas supposé :

| | poser le statut | accorder la règle permanente | libérer les tâches en attente |
| --- | --- | --- | --- |
| gestionnaire console | oui | oui | **non** |
| `corparius approve` | oui | oui (toujours seulement) | oui |
| `decide_approval` (MCP) | oui | **non** | **non** |

Cinq appelants atteignent `release_waiting_tasks` dans le paquet, et **le chemin d'approbation de la
console n'en était pas un**. Conséquence pour l'opérateur : il approuve depuis la console, le tableau
continue d'afficher « Retenu, on vous attend », et rien ne bouge avant qu'un tour tique.

C'est le quatrième écart vivant trouvé par la même méthode — lire deux surfaces qui prétendent faire
le même travail et comparer ce que chacune sait. `tests/test_two_callers_agree.py` et
`tests/test_api_version.py` tiennent maintenant les deux orthographes de chaque point d'entrée sur
**un** `app_*`, ce qui est ce qui rend vraie la phrase « l'ancien chemin est un alias ».

Trois faits reviennent au lieu d'un, parce que trois choses valent d'être dites à un opérateur :
`remembered` (une règle a été accordée), `gated` (elle ne l'a **pas** été, parce que son propre
fichier d'entreprise nomme cet outil dans `hitl_tools`) et `released`. Le `gated` n'est pas du
confort : sans lui, « Approuver, ne plus demander » refuse silencieusement sa seconde moitié, et un
bouton qui ne fait rien sans le dire est pire que pas de bouton.

### Un cliquet de rigueur qui ne s'appliquait à rien depuis l'étape 2

`[[tool.mypy.overrides]]` nommait `corparius.settings_spec` avec `disallow_untyped_defs`. Le module
est `corparius/config/settings_spec.py` depuis l'étape 2 : **sept étapes d'un cliquet appliqué à
aucun fichier.** mypy le dit — `unused section(s)` — mais le dit en note, parmi trois autres, sur un
lancement dont la dernière ligne est `Success`.

C'est exactement le défaut n° 1 du plan (le `glob` plat) dans un autre fichier : **une garde qui
cesse de s'appliquer sans échouer.** Cette classe a maintenant mordu deux fois ici, donc elle reçoit
un test — `test_every_declared_strictness_target_still_exists` résout chaque motif contre l'arbre —
et non une résolution de mieux lire les notes. Remis en place, les deux jambes mypy passent toujours :
le module était bien annoté, la garantie était simplement éteinte.

### Le deuxième onglet, et le cinquième écart

`Operations` porte le tableau, les règles permanentes, la mémoire, les brouillons et le journal.
Quatre écritures de plus en v1, et **trois d'entre elles ont gagné un service en même temps**, parce
que l'endroit où l'on écrit le second appelant est l'endroit où l'on voit que le premier n'était pas
complet. Mesuré sur `corparius memory` :

| | `--pin` | `--unpin` | `--forget` |
| --- | --- | --- | --- |
| gestionnaire console | oui | oui | oui |
| `corparius memory` | oui | **non** | oui |

Un fait épinglé par erreur depuis un terminal ne pouvait être désépinglé que depuis le navigateur.
Plus petit que l'écart des approbations — personne n'est bloqué — mais c'est la même forme, et la
forme est ce à quoi sert le service : un seul endroit qui connaît le vocabulaire, pour qu'une surface
ne puisse pas en implémenter les deux tiers.

Et la garde qui le tient n'est pas le test de comportement. `test_the_terminal_can_now_unpin`
**passe** quand on retire `--unpin` du parseur, parce qu'il construit son `Namespace` à la main :
c'est `test_every_memory_action_has_a_flag` qui échoue, en comparant `app_memory.ACTIONS` aux options
qu'argparse offre réellement. Les deux bouts du fil, encore — la même forme que `write_skill`
atteignable et jamais atteint.

`rules` **n'a pas** de service, et c'est audité et non oublié : révoquer une règle permanente est un
seul appel au store, et rien n'attend à côté. Rien n'est garé sur une règle — révoquer veut dire que
l'outil redemande au prochain tour — donc la forme « deux appels, un appelant en oublie un » ne peut
pas naître ici. Un service serait de l'indirection pure, et l'invariant déclaré est le vrai, plus
faible : les deux orthographes atteignent `drop_rule`.

**Un adaptateur a disparu au passage.** `adapters.edit_task` ne portait qu'un `try/except` traduisant
`Refused` en 400 — la seule partie de cette opération qui *soit* du HTTP — et avec deux orthographes
du point d'entrée, un adaptateur au milieu empêchait `tests/test_api_version.py` de lire les deux
corps et de les voir se rejoindre. La garantie passait de « affirmée » à « supposée » pour une
indirection. Les deux gestionnaires appellent `app_tasks.edit` directement.

### Une garde d'i18n qui ne voyait qu'une partie de ce qu'elle scannait

`test_every_component_label_is_a_key_that_exists` cherchait `t\("clé"\)` — une clé suivie
immédiatement de la parenthèse fermante. Le deuxième onglet utilise huit fois la forme
`t(fact.pinned ? "mem.unpin" : "mem.pin")` : aucune des deux clés n'est suivie de `)`, donc **aucune
des deux n'était vérifiée**, et la garde annonçait un fichier propre en en contrôlant une fraction.

Troisième instance de la même classe que le `glob` plat et l'entrée mypy périmée : *un scanner qui
sous-rapporte passe.* Élargi aux littéraux de tout appel `t(` sans appel imbriqué — et il a
immédiatement signalé `approved`, qui venait de
`t(decision === "approved" ? "toast.approved" : "toast.rejected")`, un opérande de comparaison et non
une clé. La règle qu'il impose est donc qu'un appel `t()` ne contient que des clés, ce qui est bon à
prendre : l'alternative est un scanner qui devrait comprendre JavaScript.

### Le troisième onglet, et la capacité que le terminal n'avait pas du tout

`Documents` porte la zone de dépôt, l'inventaire et la lecture d'un fichier. Quatre points d'entrée
en v1, **aucun sur un sondage** : `inventory` ouvre et extrait chaque fichier qu'il liste — PDF, docx,
xlsx, csv — et mettre ça sur un timer de cinq secondes est la même faute qu'une sonde réseau sur un
point sondé, interdite ici depuis que `/api/providers` ouvrait une socket à chaque rafraîchissement.

La distinction qui traverse les quatre : **un fichier refusé n'est pas une requête en échec.**
Demander à stocker un `.zip` est parfaitement bien formé ; la réponse est `stored: false` avec un code
`reason`. L'enveloppe d'erreur est donc réservée aux requêtes *fausses* — société inconnue, corps qui
n'est pas du base64 — et le résultat d'une requête correcte voyage dans la charge utile. C'est ce qui
permet à un dépôt de sept fichiers d'annoncer six enregistrés et un ignoré en une passe, au lieu d'une
bannière disant que l'envoi a échoué.

**Mesuré avant d'écrire quoi que ce soit : aucun module de `cli/` ne référençait `documents`.** Pas
une divergence — il n'y avait pas deux implémentations — mais le trou que l'étape 6 existe pour
combler, encore ouvert : un opérateur sur une machine sans écran ne pouvait pas voir que dix de ses
douze fichiers étaient au-delà du budget de prompt, et ne pouvait pas relire une note que son propre
agent design avait écrite. `corparius docs` lit le même `documents.inventory` que la console.

Et **il n'y a pas de `--add`**, délibérément : copier un fichier dans le dossier que `--list` affiche
*est* l'envoi, `load()` relit le répertoire à chaque appel, et un fichier illisible se signale tout
seul en `no-extractor`. Une commande qui ferait `cp` pour l'opérateur serait de la cérémonie sur un
chemin qu'il a déjà. Épinglé par un test, pour que personne ne l'ajoute par réflexe.

### Une troisième catégorie de contrat : le point d'entrée *renommé*

`ALIASED` trouve les paires par intersection de suffixes, donc un point d'entrée dont le chemin v1
s'écrit autrement lui est **invisible** : la garde signalait les deux moitiés comme non appariées et
n'affirmait rien sur aucune des deux. `/api/document/text` est au singulier parce que la page livrée
lit un document ; en v1 c'est `/api/v1/documents/text`, une sous-ressource de la collection, ce qu'il
est réellement. `RENAMED` déclare le triplet et exige la même propriété : les deux moitiés existent et
atteignent une seule fonction.

### La collision `doc.`/`docs.`, deux fois de plus, un niveau plus bas

`test_no_namespace_is_a_prefix_of_another` découpe **au premier point**. Il compare `docs` à `diag` et
ne regarde jamais à l'intérieur. Le nouveau test a trouvé deux instances de la même forme, dès la
première exécution :

| Famille calculée | Clé complète qui la masque | Renommé en |
| --- | --- | --- |
| `docs.no.` (7 refus) | `docs.none` | `docs.refused.` |
| `prov.pf.` (5 états de sonde) | `prov.pfNothing`, `prov.pfSkippedWhy` | `prov.probeNoTier`, `prov.probeSkipReason` |

Aucune des deux n'était vivante : la recherche porte le point final, donc seul `reason == "ne"` ou
`state == "Nothing"` aurait atteint la mauvaise chaîne. **La moitié humaine l'était depuis le premier
jour** — et c'est de cette moitié que le bug d'origine était fait. `prov.pfSkippedWhy` est
*l'explication de `prov.pf.skipped`* : deux noms aussi confusables que possible, pour deux choses dont
l'une explique l'autre.

Le scanner lit maintenant **la page et `web/src/*.svelte`**, parce qu'une garde qui ne couvre que
l'ancien front cesserait de couvrir le nouveau un fichier à la fois. C'est la même leçon que le `glob`
plat, l'entrée mypy périmée et le scanner de clés : *une garde qui sous-rapporte passe.* Quatrième
instance comptée dans ce chantier.

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
