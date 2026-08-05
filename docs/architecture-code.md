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
| 0 | `kernel/` | chemins, types, i18n, texte, dotenv, crypto, vecteurs, processus, HTTP brut | **tout import corparius**, même d'un rang inférieur — il n'y en a pas |
| 1 | `config/` | résolution des réglages, registre de champs, permissions | le store, les fournisseurs, le domaine |
| 2 | `store/` | schéma, migrations, un dépôt par table | tout ce qui est au-dessus |
| 3 | `providers/` | modèles, courrier, déploiements, dépôts, prospects, matériel | le domaine, l'app, le transport |
| 4 | `domain/` | roster, exécuteur, outils, entreprise, documents, orchestrateur, site | **toute dépendance hôte** : `requests`, `subprocess`, `sqlite3`, `smtplib`, `imaplib`, `socket`, `time.sleep` |
| 5 | `app/` | les cas d'usage que l'API **et** la CLI appellent | le transport |
| 6 | `api/`, `cli/` | HTTP, CLI, MCP | — rien n'importe ces dossiers |

Trois exceptions, chacune avec sa raison écrite dans le test : `corparius/__init__.py` (c'est
la racine de composition), `config/store_layer.py` (la couche de réglages en lecture seule —
on ne peut pas demander à la base où est la base), et `plugins/` (dont le métier est de
composer, voir l'[ADR 0006](adr/0006-sept-coutures-de-greffons.md)).

## Les quatre clauses qui rendent la règle réelle

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
