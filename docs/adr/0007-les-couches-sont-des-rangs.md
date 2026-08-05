# 0007 — Les couches sont des rangs, tenus par un test

## Contexte

Le paquet a atteint **23 050 lignes sur 53 modules, complètement à plat**, sans un seul
sous-paquet. Rien ne surveillait rien : pas de règle qu'un relecteur puisse citer, et aucun
échec quand un module atteint un endroit qu'il ne devrait pas.

## Ce qui a été mesuré

- Le graphe d'imports **au niveau module est un DAG**, et les **cinq cycles du paquet
  n'existent que par ~60 imports locaux dans des fonctions**. Ces imports différés sont
  porteurs : les retirer casse le chargement.
- Contre la structure cible, il n'y a que **4 arêtes montantes** :
  `secretbox→cfg`, `settings_spec→llm`, `backup→webui`, `doctor→appserver`.
- Lire le registre de réglages charge `requests`, `subprocess` et `ssl`. Importer `agents`,
  qui n'a aucune dépendance hôte propre, charge `smtplib` et `imaplib`.

## Décision

Chaque module porte le **rang** de sa couche — kernel 0, config 1, store 2, providers 3,
domain 4, app 5, interfaces 6 — et n'importe que son rang ou moins.

Cinq clauses rendent la règle réelle, et la première est celle qui compte :

1. **Les imports différés sont vérifiés à l'identique.** Une règle qui les ignorerait
   manquerait chacun des cinq cycles qu'elle existe pour empêcher.
2. Le rang 0 n'importe **rien** de corparius.
3. Le rang 4 ne touche aucun hôte — ni `requests`, ni `subprocess`, ni `sqlite3`, ni
   `smtplib`, ni `imaplib`, ni `socket`, ni `time.sleep`.
4. Une capacité hôte a **un propriétaire déclaré** : `sqlite3` dans `store/**`, `subprocess`
   dans `kernel/proc.py`, `http.server` dans `api/**`.
5. **Les composantes fortement connexes sont leur propre cliquet.** Ajoutée à l'étape 1,
   après avoir constaté que les quatre premières ne suffisaient pas : les rangs
   n'interdisent pas un cycle **à l'intérieur** d'un rang. `secretbox` étant devenu rang 1,
   une arête vers `cfg` — rang 1 — redevenait légale, et le cycle que l'étape 1 venait de
   tuer pouvait rentrer par la règle censée l'en empêcher. Non-vacuité prouvée : cycle
   réintroduit, `new import cycles: [('cfg', 'secretbox')]`, cycle retiré.

## Le cliquet

Chaque règle embarque l'ensemble exact des violations d'aujourd'hui et affirme
`constaté == déclaré`. Une violation nouvelle échoue, **et une violation corrigée sans être
rayée de la liste échoue aussi** — sinon la liste pourrit en vœu et le prochain lecteur ne
sait plus ce qui est encore vrai. C'est la mécanique des autres registres du projet
(`tests/test_registries.py`), appliquée à l'architecture.

Ces listes sont aussi le compteur d'avancement de la restructuration : elles ne peuvent que
raccourcir.

## Coût

Une table de 53 entrées à tenir à jour, et un test qui échoue quand on déplace un module sans
mettre la table à jour. C'est le but.

## Où c'est appliqué

`tests/test_layers.py`, `tests/test_import_cost.py`, `docs/architecture-code.md`.
