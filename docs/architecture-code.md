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

### Le sixième écart : deux chemins d'écriture de réglages, un seul qui validait

Trouvé en préparant l'onglet `Providers`, par la méthode habituelle — lire deux surfaces qui
prétendent faire le même travail. `POST /api/settings` passait par `app_settings.validate` : coercition
contre le registre de champs, refus motivé, effacement sur valeur vide. `POST /api/providers` avait sa
propre vérification, `key in settings_spec.WRITABLE` puis `str(value).strip()`, et rien d'autre.

Mesuré sur un vrai store :

| | clé inconnue | `"not-a-number"` pour un champ entier | valeur vide |
| --- | --- | --- | --- |
| `POST /api/settings` | refusée | **refusée, avec la raison** | **efface** le réglage |
| `POST /api/providers` | refusée | **stockée telle quelle** | stockée en `""` |

Et la conséquence : avec `CORP_SESSION_TOKEN_BUDGET` valant `"not-a-number"`, `cfg.get_int` répond
**le défaut de l'appelant**. Un budget de session qui devient silencieusement ce que le lecteur avait
deviné. N'importe quel client atteignait le chemin non validé, et toute la prémisse de l'étape 8 est
qu'un second client gèle ces routes : c'était un trou dans le contrat, pas une bizarrerie d'une page.

**Mais la colonne « valeur vide » n'est pas une dérive, et c'est la moitié intéressante.** Mesuré
aussi : une chaîne vide stockée **masque `.env`**. Avec `GROQ_API_KEY=from-dot-env` dans le fichier et
`""` dans la table, `cfg.get` lit `""` ; on supprime la ligne et le fichier réapparaît. Effacer sur
vide ferait donc **ressusciter une clé que l'opérateur vient de révoquer** — l'inverse de ce qu'il
demande. Un champ du registre est exactement l'opposé : il a un défaut, donc vide veut dire « reviens
au défaut ».

Deux règles, parce que les deux classes de clés diffèrent réellement — et les deux vivent maintenant
dans **une** fonction au lieu d'une par route. `app_settings.CREDENTIALS` est **dérivé**
(`WRITABLE - BY_KEY`, 28 des 108), pas listé à la main : une seconde liste tenue à la main pourrirait
dans la mauvaise direction, une nouvelle clé de fournisseur oubliée serait coercée contre un champ qui
n'existe pas et refusée comme inconnue.

Et un invariant que la donnée satisfaisait par hasard est maintenant affirmé : `BY_KEY ⊆ WRITABLE`.
`validate` accepte n'importe quel champ du registre, tandis que les tests de sécurité vérifient ce qui
*n'est pas* écrivable contre `WRITABLE` — deux vocabulaires qui doivent coïncider, sinon une clé serait
refusée par une liste et acceptée par l'autre. `CORP_UI_ALLOWED_HOSTS`, qui décide quels en-têtes
`Host` le serveur accepte, est vérifié absent des trois ensembles.

### Le quatrième onglet : chaque sonde est un bouton

`Providers` est l'onglet où la règle « jamais de sonde réseau depuis un point sondé » organise tout le
reste. Les lectures sont des vérifications de système de fichiers et des réglages stockés ; **rien
n'ouvre de socket avant qu'un opérateur appuie sur quelque chose.** C'est pour cela que la lecture
répond `claude_installed` depuis le disque et **omet délibérément le plan de tiers Claude** : le
construire demande de savoir si Ollama répond, ce qui sur une machine sans lui coûte un délai de
connexion par sondage — et sur un runner où le port est filtré plutôt que refusé, assez longtemps pour
faire échouer la suite.

Donc `probe`, `models`, `preflight` et `claude/setup` sont des POST. `test_the_reads_open_no_socket`
en fait une propriété et non une intention, en remplaçant `socket.socket.connect` par une exception —
et il appelle les services **directement** plutôt que par HTTP, parce que la première version passait
par le client de test et attrapait **la requête elle-même** : une requête *est* une socket, donc elle
mesurait le trajet.

Trois choses mesurées en écrivant cet onglet, et les trois ont corrigé une hypothèse que le test
portait déjà :

1. **`connected_providers()` répond `["ovh"]` sur une machine sans aucune clé.** OVH AI Endpoints est
   `key_optional` et porte une URL de base par défaut, donc « utiliser le routage recommandé » marche
   sur une installation neuve avant que l'opérateur ait collé quoi que ce soit. Le test affirmait un
   409 et a échoué — ce qui valait mieux que de passer.
2. **`os.environ` gagne, et le contrat est de le dire.** Écrire `CORP_LLM_MOCK=false` depuis la console
   ne peut rien contre un `CORP_LLM_MOCK=true` dans l'environnement du processus. C'est le bon
   classement — l'environnement appartient à qui a lancé le processus — et `persist` renvoie `shadowed`
   exactement pour ça : « enregistré, mais votre environnement l'écrase » plutôt qu'un interrupteur qui
   revient tout seul.
3. **Un test qui touchait vraiment `api.groq.com`.** Il est remonté en `ResourceWarning` sur une socket
   non fermée, que `filterwarnings = ["error"]` a transformé en échec **sur autre chose**. L'échec est
   injecté maintenant. Au passage : 20 appels `requests.get` nus dans le paquet contre un seul
   `with` — `requests.get` ferme bien sa session, donc ce n'est pas une fuite, mais l'idiome mérite un
   regard un jour.

### Deux opérations qui attendent les travaux durables

Le **pull** Ollama et le **balayage** preflight n'ont pas d'orthographe v1, et c'est une décision. Tous
deux suivent leur progression dans `UiState` — un dictionnaire en mémoire de processus — donc aucun ne
survit à un redémarrage de la console, ce qui est précisément l'état que le schéma 19 a construit la
table `jobs` pour remplacer. Une route v1 publiant un drapeau `pulling` publierait un champ qui mentira
à la seconde où la console redémarre, et un téléphone qui aurait lancé un balayage n'aurait aucun moyen
de le retrouver.

Ils passent en travaux durables d'abord, avec la preuve que le plan nomme déjà pour les tours : tuer le
serveur, le relancer, et le balayage est encore là — ou lit `interrupted`, ce qui est honnête là où une
reprise silencieuse est un mensonge sur ce qui s'est passé. `tests/test_v1_providers.py` échoue si une
route v1 pour l'un des deux apparaît avant.

### Le septième écart : une affirmation dans une docstring que le code ne tenait pas

Trouvé en lisant deux autres harnais d'agents — `yc-software/qm` et
`PrimeIntellect-ai/prime-agent` — pour voir ce qui s'y transposerait. Le classificateur d'injection de
qm a fait regarder ici, et ce qu'on y a trouvé n'était pas l'absence d'un mécanisme : c'était une
**affirmation fausse** à côté du mécanisme qui existe déjà.

`apps.py` disait :

> « An app is the only place in corparius where text from outside reaches a model, so it is the only
> place that needs this. »

Mesuré : **deux autres chemins**, et tous deux atterrissent dans le prompt **système**, pas dans un
tour utilisateur. `agents._messages` construit le système en concaténant des blocs sur
`spec.system_prompt`, ce qui est la position la plus privilégiée qui existe — sans clôture, une ligne
au fond d'un PDF est indistinguable de ce que corparius a écrit lui-même.

| bloc | d'où il vient | clôturé |
| --- | --- | --- |
| `knowledge` | un `SKILL.md` de l'entreprise, ou un pack importé | non — déclaré, avec la raison |
| `learned` | des faits que les agents de l'entreprise ont écrits | non — déclaré |
| `documents` | le dossier de l'opérateur | **oui, maintenant** |
| `language_line` | corparius lui-même | sans objet |

**Les documents ne sont pas les mots de l'opérateur.** Le dossier contient la page d'accueil d'un
concurrent, le tarif d'un fournisseur, un deck que quelqu'un lui a envoyé. Le fait qu'il les ait
déposés lui-même dit qu'il les a manipulés, pas qu'il les a écrits.

**Le pack de compétences importé n'est délibérément *pas* clôturé.** Une compétence *est* de
l'instruction procédurale par construction ; l'encadrer par « jamais des instructions » casserait ce à
quoi elle sert. Ce qui la borne, c'est qu'importer est un acte de l'opérateur et que `skillimport`
annonce en chiffres ce que le chargeur va couper. Le risque résiduel est nommé plutôt que masqué —
`skillimport` copie le corps d'un `SKILL.md` tiers **verbatim**.

Et le mécanisme est monté au rang 0 (`kernel.text.fence`) plutôt que copié, parce que **deux copies
d'un contrôle de sécurité sont deux occasions qu'une seule des deux soit la soigneuse** — ce que le
déplacement a immédiatement démontré : le premier brouillon du helper partagé prenait *un* marqueur et
dérivait le fermant, en ne retirant que l'ouvrant. Une charge utile contenant le marqueur fermant
aurait clôturé sa propre clôture et continué dehors, dans la voix de l'hôte. C'est exactement le trou
que la fonction existe pour empêcher. Les deux marqueurs sont des paramètres et les deux sont retirés.

`tests/test_untrusted_blocks.py` tient les deux bouts : chaque bloc qui entre dans le prompt système
est nommé, chacun est soit clôturé soit **déclaré non clôturé avec sa raison**, et un bloc qui
apparaît sans entrée échoue. Plus la preuve de non-vacuité : retirer la clôture fait échouer deux
tests, dont celui qui vérifie qu'un fichier ne peut pas forger sa propre sortie.

**C'est une atténuation, pas une garantie**, et le fichier le dit. Ce qui borne réellement un document,
c'est la porte de permissions : un appel d'outil qu'un fichier a réussi à souffler passe toujours par
`ask_above`, et `hitl_tools` ne peut être fait taire par rien de ce qu'un fichier raconte.

## L'étape 10 : la preuve, pas l'application

Le plan dit qu'il n'y a rien à inventer une fois l'étape 8 faite. Ce que corparius doit n'est donc pas
un projet iOS dans un dépôt Python : c'est **la preuve que la surface v1 suffit au périmètre annoncé**,
exercée comme un appareil le ferait. `tests/test_thin_client.py` est ce client — il s'apparie, lit,
décide et pilote un tour, et **chaque appel passe par une socket** avec `Authorization: Bearer`. Aucun
import de `app/`, aucune poignée de store dans le client : si une requête avait besoin de quelque chose
que v1 n'offre pas, le fichier échoue, et c'est la seule définition utile de « l'étape 10 est possible ».

Ce qu'il établit, et qui ne se déduit pas des tests unitaires :

* **Deux portées, et la seconde veut dire quelque chose.** Un téléphone apparié en `read` lit le
  résumé et le backlog, et se voit refuser `forbidden` sur approuver, lancer et arrêter — puis
  l'approbation est vérifiée encore `pending`, parce qu'un refus qui a déjà écrit est pire qu'un refus
  qui mentirait.
* **Révoquer un appareil n'en déconnecte pas un autre.** La propriété que le jeton partagé ne pouvait
  pas avoir, et la raison du schéma 20.
* **Le tour n'est pas dans l'application.** Il est une ligne de `jobs` sur le cœur, donc fermer le
  téléphone ne l'arrête pas et le rouvrir le retrouve. C'est la version honnête de « piloter sa société
  depuis son téléphone », et pourquoi le plan refuse de promettre l'exécution en arrière-plan sur
  l'appareil : aucun des deux OS ne la garantit.
* **Un réessai en 4G ne lance pas deux tours.** Même `Idempotency-Key`, même travail, `created: false`.
* **Le téléphone arrête un tour que la console a lancé**, parce que `cancel_requested` est une colonne
  et non un `threading.Event` — et un tour interrompu se lit `interrupted` avec la ligne de progression
  qu'il avait atteinte, pas silence et pas reprise.

Deux gardes tiennent le fichier honnête : aucun chemin autre que `/api/v1/` n'y apparaît (un client
mince qui toucherait un chemin legacy figerait la forme interne de la console, ce que le versionnement
existe pour empêcher), et le helper `Device` n'importe ni `app/` ni `store/`.

## Un vrai tour, sur la vraie configuration

La liste de vérification du plan demande « un vrai tour sur la vraie entreprise ». Lancé sur une
copie de `vigil` en mode mock — pour ne rien dépenser ni toucher à l'état du propriétaire —
24 ticks, dix agents, aucune erreur. Ce que ça a prouvé et qu'aucun test unitaire ne prouve :

Relancé à la fin du chantier, sur une copie de `vigil` en mode mock — 24 ticks, dix agents, aucune
erreur, 59 619 jetons :

| | à l'étape 4 | à la fin |
| --- | --- | --- |
| Schéma | 18 | **21**, migré en place sur un store neuf |
| Actions | 73 | **73**, dont 62 portant une trace de routage |
| Actions sans trace | 61 | **11** — celles qui n'ont appelé aucun modèle, `NULL` comme prévu |
| `promesse-clinique` | 24 usages en 24 ticks | **24 en 24**, inchangé |

Et ce que seule la fin du chantier pouvait montrer : **le tour est une ligne de `jobs`** en état `done`,
`chat_turns` est vide (personne n'a parlé au CEO, donc aucune ligne fantôme), et le fil d'accueil lit
`(model ✓, run ✓, decide ✗ — en tête)` avec une approbation en attente. Les trois jugements de
`app/onboarding.py` donnent la bonne réponse sur des données réelles.

Le compte d'actions identique de part en part n'est pas une coïncidence à célébrer : c'est le mode mock
qui est déterministe. Ce qui a changé, c'est le nombre d'actions **portant leur trace** — 62 contre 12
tours rédigés à l'étape 4, parce que `record_action` enregistre désormais le détail de routage pour
chaque effet et non pour les seuls tours qui ont rédigé.

Les deux dernières lignes valent d'être lues ensemble. `routing_health` répond enfin à « qui a
répondu » — `haiku` 6 fois, `gemma4:e4b` 5, `sonnet` 1 — et c'est précisément la visibilité dont
l'absence a coûté 365 026 jetons. Et `promesse-clinique` à 24 sur 24 confirme sa déclaration
`always:` par la mesure : elle est bien sur chaque prompt. Le curateur a donc de vraies données,
et n'archivera aucune des trois compétences de `vigil`, qui sont toutes en usage.

Un tour contre de vrais fournisseurs reste à l'opérateur : il dépense ses jetons.

## Les trois cliquets sont à zéro

C'est le compteur public d'avancement que le plan nomme, et il est arrivé au bout :

| Cliquet | Au départ | Maintenant |
| --- | --- | --- |
| Violations de rang | ~60 arêtes | **0** |
| Cycles d'import | 5 composantes | **0** |
| Impuretés du domaine | 3 | **0** |

Les trois dernières impuretés sont parties comme les cycles : non pas en supprimant l'arête, mais en
déplaçant ce qui n'était pas à sa place.

**`("apps", "requests")` ne coûtait rien.** L'import ne servait qu'à nommer
`requests.RequestException` dans un `except` qui contenait **déjà `OSError`** — et toute exception de
`requests` en dérive. Mesuré, pas supposé : `RequestException.__mro__` est
`(RequestException, OSError, Exception, ...)`. `(ProviderError, OSError)` est le même ensemble, minimal,
et mypy en voit les membres — ce qu'il refusait pour un `(*UNREACHABLE, OSError)` étoilé.

**`("orchestrator", "requests")` n'avait pas d'`OSError` à côté.** Élargir aurait donc étiqueté une
erreur de fichier en « LLM injoignable ». C'est le rang 3 qui nomme le tuple :
`llm.UNREACHABLE = (ProviderError, requests.RequestException)`. La couche qui possède le transport
possède ce que « injoignable » veut dire, et changer de client HTTP devient une ligne au lieu de chaque
appelant qui attrape ses exceptions.

**`("orchestrator", "time.sleep")` était porteur.** C'est le plancher de cadence à la frontière de
journée d'un run `--loop` : une journée dont tous les rôles sont en pause se termine en millisecondes,
et sans lui la boucle tourne à vide à plein régime. Le supprimer pour satisfaire la règle aurait échangé
une règle contre une boucle folle. Il est passé dans `kernel/clock.pace()` — **exactement l'argument que
`kernel/proc.py` fait pour `subprocess` : l'emballage existe pour que l'interdiction puisse exister** —
et cela rend un test de `--loop` possible : on remplace une fonction au lieu de payer une seconde réelle
par journée simulée.

Et écrire cette interdiction a trouvé un **second** propriétaire que rien ne surveillait :
`providers/sitecheck` attend la propagation d'un CDN avant la vérification unique de déploiement.
`KNOWN_IMPURE` ne couvrait que le rang 4, donc il n'avait jamais figuré sur aucune liste. Ce n'est ni un
plancher de boucle ni une reprise — les octets ne sont pas encore servis, et c'est l'affaire du rang 3.
Borné par `MAX_WAIT`, réglé par `wait_seconds()`, journalisé, et contournable par le paramètre `wait`
pour qu'un test n'attende jamais. Les deux sont déclarés ; un troisième échoue.

## Les deux décisions qui restaient

**Le framework du front : Svelte 5 + Vite**, tranché à l'étape 9 comme le plan le prévoyait. L'argument
React Native ne tient pas à l'examen : React DOM et React Native ne partagent pas de composants, et ce
qui se partage réellement avec un client mobile — le client d'API et les tables i18n en JSON — est
agnostique du framework. Le poids du bundle voyage dans le binaire PyInstaller, et 80 champs de réglages
favorisent `bind:` sur une bibliothèque de formulaires.

**Le bug de slug : rien à migrer, et la prémisse du plan était fausse.** Mesuré à l'étape 1 :
`company.load` dérive le slug du **nom du dossier** avant toute validation, donc pour une entreprise déjà
sur le disque les deux orthographes sont idempotentes. La seule orthographe cassée ne produisait un
dossier qu'à un seul endroit — l'assistant de création, où aucun slug n'est donné. Donc pas de migration
de renommage : `slugify` dérive, `slugify_loose` préserve, et aucune entreprise installée n'est touchée.

## Le drapeau tombe : `/` sert la console Svelte

Le plan gardait l'ancienne page sur `/` « jusqu'à ce que le nouveau bundle passe le test d'égalité
des jeux de clés i18n ». Il passe, les sept onglets sont refaits, donc la condition est remplie et le
drapeau a fini son travail. `/` sert le shell construit ; `start-windows.bat` le construit avant de
servir quand Node est là, de sorte qu'un double-clic donne la nouvelle console sans qu'on tape un
chemin.

**Un détail a mordu, et il rendait un 200 indistinguable d'une console cassée.** `base` valait `./`
dans la configuration Vite, avec un commentaire disant qu'un base relatif « fait que le bundle ne se
soucie pas du chemin sous lequel il est servi ». C'est le contraire dès qu'il est servi sous **deux**
chemins : `./console.js` se résout contre celui que le navigateur a demandé, donc la copie servie
sur `/` réclamait `/console.js` et recevait un 404. Une page blanche, avec un statut 200. `base` vaut
maintenant `/app/` — absolu — donc les ressources sont au même endroit quel que soit le chemin du
shell, et c'est ce qui rend possible de le servir depuis plus d'un chemin.

La justification qui accompagnait l'ancienne valeur — un base relatif permettrait d'ouvrir le bundle
depuis `file://` — n'était **exercée par aucun test**, et ne pouvait pas l'être : c'est un module ES
qui importe dynamiquement le morceau français, et un navigateur refuse le chargement de modules sur
`file://`.

**Le repli n'est pas un réglage, c'est un fait sur la copie de travail.** `corparius/api/static/`
n'existe qu'après `npm run build`. Sans lui, `/` sert la page d'un seul fichier — une console
entière, sans étape de build — et `/app/` répond 404 en nommant la commande. Construit veut dire
nouvelle, non construit veut dire ancienne, et aucun des deux états n'est une console cassée. C'est
pourquoi les deux jambes de CI l'affirment séparément : `/app/` et `/` diffèrent d'un seul
branchement, et le repli répond 200 avec l'ancienne page, donc un aiguillage cassé ressemble à un
succès.

La page d'origine garde un chemin à elle, **`/legacy`**. Un chemin plutôt qu'une variable
d'environnement : quelqu'un qui tombe sur un défaut de la nouvelle console a besoin d'un endroit où
cliquer, pas d'une variable à poser et d'un redémarrage pour le faire.

**Et `start.py` est testé pour la première fois.** Aucun test ne l'importait, ce qui était tolérable
tant qu'il ne faisait qu'un venv et un `pip install` — une panne y est bruyante. Construire la
console ne l'est pas : son mode de défaillance est de **servir un vieux bundle pour toujours**, ce
qui ressemble exactement à du code qui n'a pas changé. La comparaison de fraîcheur est donc épinglée
dans les deux sens — une source éditée reconstruit, un arbre intact n'invoque pas npm — et la
non-vacuité est prouvée en inversant l'opérateur : trois tests tombent.

Ce que le lanceur affiche est une ligne, choisie parmi quatre, et `tests/test_start_script.py` tient
les deux bouts du fil dessus comme partout ailleurs : tout état que `build_console` renvoie a une
ligne, et toute ligne déclarée est atteignable. Sans ça, un état sans ligne est un `KeyError` sur la
dernière instruction avant le démarrage du serveur — après le venv, l'installation et le doctor, au
premier lancement de quelqu'un.

Quatre plutôt que trois pour une raison qui tient en une phrase : « construite à l'instant » et
« déjà à jour » sont la même console et pas la même affirmation, et un lanceur qui dit « à l'instant »
à chaque démarrage apprend à ne pas être lu. Le cas `--no-build` ne prétend rien non plus : il a
sauté la vérification qui aurait su.

**La version de Node est lue, pas écrite.** Le message est adressé à quelqu'un qui va installer
quelque chose, donc il ne peut pas être un chiffre rond de mon invention : `engines` dans
`web/package.json` vaut `^20.19 || ^22.12 || >=24` — l'exigence de Vite 7 elle-même, mesurée dans le
`package.json` installé — et « Node 20+ » aurait envoyé quelqu'un vers 20.0, qui s'installe puis
refuse de construire. Le lanceur affiche un chiffre à suivre, 24, et la plage réelle en dessous ; un
test affirme que la plage accepte le chiffre, parce que 23 est exactement le piège — plus récent que
22 et exclu.

## La console avait des jetons, pas un design

Le premier passage a porté `tokens.css` — les rampes oklch mesurées — et **la couche de composants
n'est pas venue avec.** Le résultat, sur capture : sept onglets de rectangles bleu marine identiques
dans une colonne de 46rem, chaque titre de carte en petites capitales grises de 0,82rem, chaque bouton
du même bleu plein, aucune icône, aucune profondeur, aucune hiérarchie. **Les jetons sont une palette.
Ce n'est pas un design.**

`web/src/console.css` est cette couche : 856 lignes globales, et les huit composants passent de 767
lignes de CSS propre à 248 — parce que chacun avait fait pousser son propre `.card`, `.badge`,
`.banner` et `button`, qui dérivaient d'un pixel ici et d'un rayon là. Le `<style>` d'un composant est
pour ce qu'il a en propre.

### Six revues à l'aveugle

À chaque tour, un agent qui n'avait jamais vu le produit, à qui on demandait de juger comme il
jugerait les captures d'un concurrent, et de ne pas ménager. Verdict demandé en OUI ou NON strict.

| Tour | Note | Ce que la revue a nommé en premier |
| --- | --- | --- |
| 1 | 4/10 | fonds de cartes ragged, le nombre du bandeau peint en gris de légende, Réglages à 45 % de vide, des booléens rendus en champs texte contenant `false` |
| 2 | 5,5/10 | chemins absolus sur quatre lignes comme corps de texte, le paragraphe de Réglages en ruban de 145px, la case à cocher #3b3b3b de Chromium sur du marine, les portraits lus comme des emoji |
| 3 | 5/10 | **les cartes empilées se touchent** — 2px de bordure et aucun écart —, le contenu « centré » décalé de 250px, aucun système d'élévation |
| 4 | 6/10 | Réglages en mur de 5 100px, le panneau CEO flottant au-dessus de 290px de vide, l'en-tête du Backlog seul dans une carte |
| 5 | 6/10 | libellés de boutons tronqués, les pastilles dans les étiquettes décalant chaque ligne française de 30px, deux curseurs bruts |
| 6 | 6/10 | le logo raster, aucune hiérarchie de page, l'état actif invisible, un tiers de chaque écran mort |

Quatre de ces revues ont trouvé ce qu'aucun test ne pouvait :

**Les marges automatiques de `.wrap` annulaient l'étirement transversal du flex.** `main` était donc
dimensionné par son contenu. Les onglets larges tapaient dans le plafond de 1200px et paraissaient
corrects ; l'onglet CEO sortait à 827px, centré — passer dessus déplaçait toute l'interface de 162px de
chaque côté. Mesuré dans un navigateur, pas deviné.

**Le thème de l'exploitant ne s'appliquait qu'après ouverture de Réglages.** `applyTheme` vivait dans
cet onglet : un exploitant en clair obtenait du sombre partout ailleurs, puis du clair partout — la
console avait l'air de changer d'avis. C'est `theme.js` maintenant, appelé par la coque au démarrage.
Le test qui épinglait l'ancienne adresse affirme les deux moitiés, parce que l'une sans l'autre est le
bug.

**Six chaînes françaises du registre avaient perdu tous leurs accents** — « Chaque dossier de company
comme depot prive independant », « Portee 'repo' », « si vous y etes deja connecte » — et « companies »
figurait dans des étiquettes françaises. Du français sans accent est du Python valide et de l'UTF-8
valide : rien dans le dépôt ne pouvait le voir. `tests/test_french_spec.py` le voit, et **dit ce qu'il
ne voit pas** : un accent perdu sur quatre. Prouvé en retirant exactement celui-là et en le regardant
passer.

**Une phrase à moitié traduite par construction.** Le verdict est en français, la mesure derrière est
produite en anglais par `providers/hardware.py`, qui rapporte des nombres et n'a pas à connaître une
langue. Les deux étaient collés en une phrase ; la mesure a sa propre ligne, dans la fonte que la
console réserve aux valeurs machine.

### Le thème clair : une rampe mesurée, corrigée par la mesure

Page 0,975 contre carte 0,99 mettait une carte à **1,044:1 sur sa propre page** — le sombre est à
1,121:1. Le clair avait donc la moitié de la structure et se lisait comme un filaire : en-tête,
navigation, bandeau et cartes en une seule feuille blanche indifférenciée. Page 0,955 et carte blanche
donnent **1,140:1**, texte sur carte 14,6:1, atténué sur carte 7,5:1, atténué sur page 6,5:1. Changé
dans les deux copies, avec les nombres dans le commentaire.

### Deux choses retirées, et pourquoi

**Les onze portraits en pixel art.** Trois revues indépendantes les ont lus comme des emoji de
substitution — « un cœur rouge pour l'agent social » — à 36px comme à 20px. Les garder parce qu'ils me
plaisent, ce serait préférer mon goût à la preuve. Le paquet reperd les 45 Ko de base64 au passage.

**La texture de points derrière le panneau Plugins.** Les bandeaux de cette page utilisent une teinte
à 20 % d'alpha, donc les points se voyaient **à travers** et se lisaient comme un défaut de rendu. Une
texture qui se bat avec le contenu devant elle est pire qu'une surface plane.

### Où ça s'arrête, dit franchement

**La revue à l'aveugle dit encore NON, à 6/10.** Ce qu'elle demande ensuite est au dossier : une marque
en SVG, une véritable échelle de couleurs d'état employée à l'identique partout, la ligne Providers
reconstruite, et la fin de la passe terminologique française (palier/tier, PDG/CEO, jetons/tokens). Je
ne prétends pas que c'est beau ; je prétends que c'est mesurablement mieux qu'avant et que la liste de
ce qui reste est écrite plutôt que devinée.

**Une correction de méthode.** Le premier banc de captures utilisait `fullPage`, qui compose mal ce qui
est sous la ligne de flottaison quand une carte porte un `mix-blend-mode` : il a rendu un panneau entier
à ~10 % d'opacité, et une revue a légitimement conclu à une page cassée. Vérifié dans un vrai viewport
— où le panneau est intact — avant de toucher à quoi que ce soit. Le banc agrandit le viewport
maintenant.

## Treize revues à l'aveugle, et où la note s'arrête

Après le premier passage (4/10), douze tours de plus, chacun jugé par un agent qui n'avait jamais vu le
produit et à qui l'on demandait un verdict OUI/NON strict et de ne rien ménager.

| Tour | Note | Ce qui a été corrigé ensuite |
| --- | --- | --- |
| 1 | 4/10 | la couche de composants entière, portée depuis la page livrée |
| 2 | 5,5/10 | cases à cocher dessinées, mesure de 68 caractères, chemins tronqués, états vides |
| 3 | 5/10 | **l'écart entre cartes empilées** — il n'y en avait aucun —, l'élévation, le centrage |
| 4 | 6/10 | Réglages en sections, `theme.js` au démarrage, les accents français |
| 5 | 6/10 | Réglages en une section à la fois, pastilles hors des étiquettes, pastilles de teinte |
| 6 | 6/10 | la marque en SVG, un titre par page, l'échelle d'état, la marque désaturée refusée |
| 7 | 5/10 | **une régression de ma main** : la grille appariée rendait une aide sur un caractère par ligne |
| 8 | 6,5/10 | trois composants partagés — `Empty`, `Toggle`, `Segmented` — employés sans exception |
| 9 | 7/10 | le puits des champs, la hiérarchie des boutons, le drapeau de danger sur les plugins |
| 10 | 6/10 | cartes à la hauteur de leur contenu, une gouttière, cinq tailles de texte |
| 11 | 6/10 | pastilles qui reviennent à la ligne au lieu d'être coupées, en-tête de tableau |
| 12 | 6/10 | l'accent redevient « la chose à faire », les nombres passent en taille d'affichage |
| 13 | 6,5/10 | le panneau CEO à la taille de son invitation, l'aperçu du site, les onze glyphes d'agent |

**La note plafonne, et la treizième revue dit pourquoi mieux que moi.** Question posée directement :
l'écart qui reste jusqu'à 9/10 est-il une liste de défauts, ou de l'ambition de conception ? Réponse
citée : « **Ambition, not a defect list.** On peut corriger chaque point ci-dessus et atterrir à 7,5 —
plus propre, toujours oubliable. » Ce qui manque n'est pas une correction mais une composition : une
stratégie de densité pour Providers, une échelle d'affichage pour les nombres, une raison pour qu'une
page ne ressemble pas à la suivante.

**Deux revues se contredisent, et il fallait trancher.** Le tour 3 exigeait que les fonds de cartes
d'une même rangée s'alignent ; les tours 10 et 11 exigeaient que chaque carte s'arrête où s'arrête son
contenu. Les deux ne peuvent pas être vrais. Choix retenu : la hauteur du contenu, parce que
l'alternative rembourre les cartes courtes de 150 px de vide, et qu'une rangée de cartes inégales est
une composition alors qu'une rangée de cartes à moitié vides est une erreur.

**Et un refus, dit avec sa raison.** Trois revues ont demandé de désaturer les surfaces vers un gris
ardoise. Mesuré : cela améliore chaque contraste de texte. Refusé quand même — « tout est bleu » est une
décision de marque écrite dans `tokens.css` avec la palette du propriétaire, et `--ui-chroma` est déjà
le bouton de l'exploitant, désormais en quatre pas nommés (Aucune / Discrète / Moyenne / Pleine). Une
revue esthétique ne renverse pas une décision documentée du propriétaire ; elle la rend réglable.

### Ce que les revues ont trouvé qu'aucun test ne pouvait

Les marges automatiques de `.wrap` annulant l'étirement du flex (l'onglet CEO 330 px plus étroit que les
autres). Le thème de l'exploitant appliqué seulement après ouverture des Réglages. Six chaînes
françaises du registre sans un accent. Une phrase à moitié traduite par construction. Et, la plus
instructive, **la spécificité que Svelte ajoute à un sélecteur de composant** : trois fois j'ai corrigé
la pastille sélectionnée dans le mauvais fichier, parce que `.rail button` scopé bat `.chip.on` global.
Le gagnant doit être écrit là où vit le perdant.

### Ce que l'aperçu et les glyphes rendent au produit

Deux choses demandées pendant le chantier, et les deux étaient des régressions de ma part plutôt que des
souhaits : **l'aperçu du site de vente** existait sur la page livrée — une iframe de `/site/<slug>/`
rendue à 400 % et réduite au quart, de sorte qu'une page entière tient dans une carte — et la carte
refaite montrait une date et deux boutons en parlant d'un site. Et **les onze glyphes d'agent** : les
portraits en pixel art ont été retirés parce que trois revues les lisaient comme des emoji, ce qui
laissait les rôles nommés en texte seulement. `AgentIcon.svelte` est la réponse que les revues
demandaient réellement — un jeu monochrome sur la même grille de 24 unités, la même graisse de trait et
la même taille optique que `TabIcon.svelte`, de sorte qu'un agent dans le journal et un onglet dans la
navigation appartiennent au même dessin.

### L'état « serveur injoignable » est un état, pas un bandeau

Quand le cœur ne répond pas, il n'y a rien d'autre sur la page : un liseré rouge dans le coin supérieur
gauche d'une fenêtre vide était donc toute la conception de la panne la plus courante qu'un exploitant
verra. C'est une page centrée maintenant — la marque, ce qui s'est passé, ce que c'est probablement, la
raison brute en rouge, et un bouton — **et elle réessaie toute les trois secondes.** Un serveur qui
redémarre revient de lui-même ; devoir presser F5 pour l'apprendre, c'est la console qui fait de son
problème celui de l'exploitant. Seulement quand l'échec est un échec de transport : un 401 ou une
version incompatible sont des réponses, et réessayer une réponse est une boucle.

## La boucle de revue, appliquée au site des sociétés

La console vient de passer treize tours de *générer, faire juger, corriger, refaire juger*. Ce que ce
chantier a appris sur la boucle elle-même vaut plus que les corrections : **les revues qui servent
portent un nombre.** « La carte est à 1,044:1 sur sa propre page » a produit un correctif en quelques
minutes ; « il manque une intention de composition » a produit quatre tours de tâtonnement. Une boucle
qui mélange les deux apprend à son lecteur à ignorer les deux.

`corparius/sitegen/critique.py` est donc la moitié déterministe de cette boucle pour la page générée, et
elle n'a le droit de dire que ce qu'elle peut prouver :

* **le contraste, sur les paires que la page peint vraiment** — corps sur fond, secondaire sur fond,
  corps et secondaire sur le bandeau de prix inversé, corps sur le lavis du héros, libellé sur l'accent.
  Nommées depuis les clés de `palette_for` plutôt que devinées, et un test affirme que **tout ce que la
  palette résout comme texte apparaît dans une paire mesurée** : un contrôle de contraste ignore ce qu'on
  ne lui a pas donné, ce qui est exactement la forme du bug d'origine — le bandeau sombre à **1,16:1**,
  presque noir sur presque noir, que rien dans le dépôt ne pouvait voir ;
* **les défauts de texte démontrables** : un H1 absent, un H1 devenu paragraphe, un `[mock:` arrivé sur
  la page depuis un brouillon hors ligne, une page trop maigre pour décider quoi que ce soit.

**Et la distinction qui fait marcher la boucle : `fixable_by_copy`.** Une reformulation peut réparer un
titre ; elle ne peut pas relever un ratio de contraste qu'elle ne voit pas, ni écrire un prix que la
société n'a pas configuré. Le compte rendu du build dit tout ; le brief envoyé au tour suivant ne porte
que ce qu'une reformulation peut corriger. Envoyer un modèle réparer une couleur produit des excuses,
pas un correctif.

### Le juge doit être un autre modèle, et c'est vérifiable ici

Décision prise pendant ce chantier : dans la boucle, **le modèle qui juge n'est pas celui qui a écrit.**
La machinerie existe déjà — `structured.ask(..., model=)` épingle un modèle, les paliers de routage en
nomment plusieurs, et depuis le schéma 18 `record_action` enregistre `source`, donc « qui a répondu » est
une colonne et non une supposition. Un juge disjoint est donc non seulement possible mais **contrôlable
après coup** : le journal dit quel fournisseur a rédigé et quel fournisseur a jugé.

Ce qui reste à écrire est la moitié modèle, et sa forme est déjà contrainte par l'architecture : un effet
d'outil atteint `company`, `data_path`, `leads`, `store` et `structured` — **délibérément pas de poignée
de modèle**, parce que l'exécuteur possède le routage, le budget de jetons et la comptabilité. Un tour de
critique par un modèle est donc soit une capacité de l'exécuteur (un outil qui déclare « juge-moi »,
l'exécuteur dépense un second appel et rejoue l'effet), soit — moins cher et plus dans l'esprit du projet
— **un outil de revue à part, sur la cadence qui existe déjà**, dont les conclusions attendent le
prochain tour design. C'est l'argument que le plan tient déjà pour le curateur de compétences : ça
s'accroche à la frontière de journée qui existe, pas à un fork par tour.

## La moitié du défaut « 22 sur 24 » qui restait ouverte

`executable_fields` a été écrit contre une mesure : **24 tâches pour un rôle sans outil, 22 fermées
« done (no tool mapped) »** sans rien avoir fait. Il corrige le cas où un rôle a un outil par défaut.

**Cinq rôles sur dix n'en avaient aucun** — ads, coder, competitor, finance et le CEO — donc une
proposition visant l'un d'eux était approuvée, n'exécutait rien, et se fermait comme faite. La condition
qui l'avait produite survivait, l'agent la reproposait. Le défaut mesuré était donc encore vivant pour
la moitié du roster, et rien ne pouvait le voir.

**La table n'est pas dérivable du playbook, et c'est la découverte utile.** Trois des cinq entrées
existantes *contredisent* le premier pas du playbook de leur rôle : `find_targets`, `review_kpis` et
`triage_inbox` viennent en tête pour outreach, strategy et support, et les trois ne font que *regarder*.
Une tâche approuvée sur l'une d'elles finit sans rien produire — le même rien que pas d'outil du tout.
**La règle est donc : le défaut est un outil qui produit.** Quatre entrées ajoutées sur ce principe, et
chacune est l'outil produisant que son rôle peut lancer *sans portail* : `adjust_bids` est externe,
`send_financial_transaction` est de l'argent, `publish_production_code` est du code — les trois
gareraient la tâche sur le portail humain à l'instant de l'approbation, ce qui n'est pas approuver, c'est
mettre en file.

**Et une seconde distinction, apprise en écrivant le test qui l'affirmait à l'envers.** J'avais posé
« le défaut doit figurer dans le playbook du rôle » : c'est faux. `write_note` est le défaut de strategy
et ne figure pas dans son playbook. Un **playbook est une cadence** — ce que le rôle fait chaque tour,
sans qu'on le lui demande ; **l'outil d'une tâche est ce qu'une tâche approuvée exécute.** La docstring
de strategy portait déjà le coût de les confondre : sans `write_note`, une tâche stratégie atteignait un
agent sans outil pour la porter et restait tenue pour l'exploitant, deux fois.

Le CEO n'a toujours pas de défaut, **volontairement** : il arbitre le backlog, il ne le travaille pas.
`unrunnable_reason` le dit à voix haute plutôt que de laisser l'omission passer pour un oubli — et les
deux chemins qui approuvent l'appellent, le bouton de la console via `app.tasks.edit` et le tour du CEO
via `review_proposals`, parce que la première version de ce correctif n'en avait attrapé qu'un.

Non-vacuité prouvée dans les deux sens : retirer les quatre défauts fait tomber deux tests, retirer le
refus en fait tomber un troisième.

## Le juge, et pourquoi ce n'est pas un second appel dans le build

La moitié modèle de la boucle est écrite, et sa forme a été dictée par une contrainte réelle plutôt que
par un goût : **un effet d'outil atteint `company`, `data_path`, `leads`, `store` et `structured` — pas
de poignée de modèle.** L'exécuteur possède le routage, le budget de jetons et la comptabilité. Un tour
de critique à l'intérieur de `build_sales_site` aurait donc exigé une nouvelle capacité de l'exécuteur.

`review_generated_site` est un **outil séparé sur un autre rôle** : design écrit la page, strategy la
relit. Rien de nouveau dans l'exécuteur, et la séparation des modèles vient de la machinerie qui existe
déjà — un rôle porte son propre `model` (coder est déjà épinglé sur `local:qwen2.5-coder:14b`), donc
épingler le rôle relecteur ailleurs que design fait littéralement juger un autre modèle.

**Et l'outil ne prétend pas que la séparation a eu lieu.** Sans épingle, les deux tours routent
indépendamment, ce qui n'est pas une garantie. Il lit donc `source` sur les deux actions et **dit quand
c'était le même fournisseur** — le schéma 18 a fait de « qui a répondu » une colonne et non une
supposition. Un second avis du même modèle est un avis deux fois.

La boucle se ferme sans nouvelle table : le prochain `build_sales_site` lit le verdict dans **la ligne
de journal que la revue a déjà écrite**. Pas de migration, pas de champ, et ça survit à un redémarrage
parce que le journal d'actions y survit.

Trois principes repris du chantier console, parce qu'ils ont été payés cher :

1. **Le mesuré entre dans le prompt.** Un juge à qui l'on dit « le H1 fait 214 caractères » écrit un
   titre plus court au lieu de discuter de sa longueur — et cesse de dépenser sa réponse sur ce qu'une
   règle a déjà attrapé, ce qui est l'essentiel de ce qu'un second avis gaspille.
2. **Le juge ne parle que de ce qu'il voit.** Le prompt lui interdit la couleur, la mise en page et les
   images : il lit du texte, et un jugement sur ce qu'on ne voit pas ne vaut rien. C'est la même règle
   que `fixable_by_copy` applique dans l'autre sens.
3. **Le cas silencieux doit rester silencieux.** « Rien à changer » ne remonte rien au prochain
   brouillon. Une boucle qui parle à chaque cadence apprend au modèle que les revues sont du bruit.

Non-vacuité prouvée : débrancher la boucle du prochain brouillon fait tomber un test, faire taire la
comparaison des `source` en fait tomber un autre.

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

## L'emballage, vérifié depuis un wheel installé

La liste du plan demande « l'installation du wheel dans un venv neuf, servie **sans Node installé** ».
Refait à la main à la fin du chantier, depuis un répertoire neutre pour que le checkout ne puisse pas
masquer l'installation :

```text
Requires-Dist: pyyaml>=6.0
Requires-Dist: requests>=2.31          <- la règle des deux dépendances, depuis les métadonnées du wheel
console files carried:  index.html, console.css, console.js, console-fr.js
corparius run --company example --ticks 4   ->  "ticks_run": 4
GET /app/                                  ->  <div id="app">
GET /app/console.js                        ->  200, 155 519 octets
GET /api/v1/meta                           ->  api_version 1, schema_version 21, durable_jobs true
```

`paths.console_built()` est la ligne qui compte : c'est le mode où se tromper est le plus difficile à
remarquer depuis un checkout, et toute la raison pour laquelle le build écrit **dans** le paquet plutôt
qu'à côté.

**Une réserve, dite plutôt qu'enjolivée** : cette machine a Node installé, donc l'exécution locale ne
prouve pas l'absence de Node comme la CI le fait avec `which node`. Ce qu'elle prouve : le venv ne
contient que corparius, les deux dépendances d'exécution et leurs transitives, et il sert la console.
La jambe CI reste la mesure de l'affirmation « sans Node ».

Et le binaire gelé, la jambe où une analyse PyInstaller qui rate un import différé se voit :

```text
GET /api/companies    ->  ["example"]                    (le home de test, pas celui de l'opérateur)
GET /api/v1/meta      ->  schema_version 21              tout sous-paquet s'importe, en une requête
GET /app/console.js   ->  200, 155 519 octets            la console livrée depuis l'intérieur du .exe
POST /api/v1/preflight ->  409 conflict                  l'enveloppe v1 refuse une sonde payante en mock
```

**La première tentative n'a rien prouvé, et c'est la procédure qui était fausse, pas le produit.** Le
binaire a refusé de démarrer — « port 8600 is already in use », avec la commande pour en choisir un
autre — et les requêtes sont donc parties vers la console que l'opérateur avait déjà ouverte. Elles ont
répondu `schema_version: 20` et listé `vigil` : deux signatures qui n'appartenaient pas à un binaire
fraîchement construit sur un home vide, et c'est ce désaccord qui a révélé l'erreur. Refait sur un port
libre, avec l'assertion que la liste des sociétés est bien celle du home de test.

## La couverture par fichier

`coverage report --fail-under=72` lit **un** nombre pour tout le paquet, et un nombre ne voit
pas un module passer de 88 % à 30 % pendant que la moyenne tient. Chaque fichier porte donc
son propre plancher dans `tests/coverage-baseline.json`, vérifié par
`packaging/coverage_ratchet.py` — que la CI lance juste après la porte globale.

Un fichier sans plancher **échoue** : quand un module se découpe, ses morceaux pourraient être
à 0 % sans que rien ne le remarque. Il faut passer `--update`, ce qui met les nouveaux
chiffres dans un diff qu'un humain lit.
