# 0002 — Une connexion au store, sérialisée par un `RLock`

## Contexte

Un même `Store` est partagé par les threads par-requête de la console et par la boucle de
run en arrière-plan. `sqlite3` sérialise ses appels C individuels — mais pas la paire
`execute`/`commit` que chaque méthode effectue.

## Décision

Une connexion longue durée par `Store`, et un décorateur `@_locked` sur **chaque** méthode,
avec un `threading.RLock`.

## Ce qui a été mesuré

Sans le verrou, sur **douze écrivains concurrents** : `cannot start a transaction within a
transaction`, et **414 lignes gardées sur 3 200**, en silence. Le verrou est porteur, pas
défensif.

`RLock` et non `Lock` parce que ces méthodes sont réellement réentrantes : `status()` appelle
`list_approvals()` et `list_tasks()`, `flow_metrics()` appelle `status()` et `list_tasks()`.
Un `Lock` simple s'auto-bloque au premier `status()`.

Et une connexion par appel avait son propre coût, mesuré ailleurs : `makedirs` + `connect` +
`SCHEMA` + `chmod` + migration **à chaque sondage** de la console, plus — sur Windows — un
handle ouvert qui empêche de déplacer ou sauvegarder le fichier.

## Coût

Toute méthode ajoutée au `Store` doit porter `@_locked`, et c'était une convention plutôt
qu'une vérification. Le découpage en mixins ajoute le test qui l'exige.

## Où c'est appliqué

`corparius/store.py:368-388` (le décorateur et son raisonnement), `webui.py:178-190` (la
connexion prêtée par la console).
