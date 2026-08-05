# 0004 — Trois modes de distribution, un seul résolveur

## Contexte

Corparius se distribue de trois façons : un checkout source, un binaire gelé PyInstaller, et
un wheel pip. Les trois placent les fichiers livrés et l'état de l'exploitant à des endroits
différents, et confondre les deux est une erreur qui ne se voit qu'à l'installation.

## Décision

Un module, `corparius/kernel/paths.py`, et **tout passe par lui**. Il distingue :

- les **ressources livrées**, en lecture seule — racine du dépôt, `sys._MEIPASS` gelé, ou
  `corparius/_data/` dans un wheel ;
- l'**état de l'exploitant**, inscriptible — `$CORP_HOME` s'il est posé, sinon le dossier par
  OS quand on est gelé ou installé, sinon la racine du dépôt.

Le dossier par OS suit chaque plateforme : `%LOCALAPPDATA%` sur Windows,
`~/Library/Application Support` sur macOS, `$XDG_DATA_HOME` ailleurs.

## Ce qui a été mesuré

`<data_path>/sites/<slug>` était épelé **à neuf endroits**. C'est la raison écrite dans la
docstring du module : un chemin dupliqué est un chemin qui divergera.

Écrire l'état à côté du code est faux dans deux des trois modes — un bundle en lecture
seule, ou `site-packages`.

## Coût

Une indirection de plus pour lire un chemin, et un module à fan-in 21. En échange, ajouter
une plateforme est **une branche dans `_platform_home()`**, pas une chasse dans tout le code.

## Où c'est appliqué

`corparius/kernel/paths.py:1-36` porte le raisonnement ; le job `wheel-smoke` de la CI le vérifie
dans un venv neuf, depuis un répertoire courant neutre.
