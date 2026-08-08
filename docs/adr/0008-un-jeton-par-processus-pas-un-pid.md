# 0008 — La propriété d'un travail est un jeton par processus, pas un PID

## Contexte

Schéma 19 ajoute une table `jobs` pour que le travail survive au processus qui l'a lancé —
`UiState.runs` était un dictionnaire en mémoire, donc un tour lancé depuis un téléphone
disparaissait au redémarrage de la console **sans trace qu'il ait existé**.

Une table durable pose immédiatement une question que la version en mémoire n'avait pas : au
démarrage, comment savoir si un travail encore marqué `running` tourne vraiment, ou s'il est le
reste d'un processus mort ? La réponse décide d'une transition d'état, donc se tromper n'est pas
cosmétique : un tour mort qui se lit `running` bloque tous les suivants, indéfiniment.

Le plan nommait la colonne `owner_boot`, l'idée étant PID + identifiant de démarrage de la machine.

## Ce qui a été mesuré

- **Il n'y a pas d'identifiant de démarrage portable dans la bibliothèque standard.**
  `/proc/sys/kernel/random/boot_id` existe sur Linux et n'a pas d'équivalent Windows accessible
  sans dépendance. La CI de ce projet livre sur **trois OS** et la règle des deux dépendances
  d'exécution interdit `psutil`.
- **Le PID seul est pire que rien pour cette question.** Les systèmes réutilisent les numéros. Une
  nouvelle console qui hérite du numéro de l'ancienne conclurait que l'orphelin est le sien, ne le
  balaierait pas, et rapporterait un tour mort comme vivant — pour toujours, puisque plus personne
  ne le finira.
- Le test qui prouve la propriété n'a pas pu être écrit en processus, et l'échec a été instructif :
  monter deux serveurs dans un interpréteur ne prouve rien, parce que `shutdown()` sur un objet
  serveur **ne tue pas** le thread qui fait tourner les ticks. Deux `build_server` dans un
  interpréteur sont un seul propriétaire, et c'est correct.

## Décision

Une colonne `owner_token`, valant un `secrets.token_hex(8)` frappé **une fois par processus**
(`store.jobs.OWNER`). C'est la seule chose comparée par le balayage de démarrage :

```sql
UPDATE jobs SET state='interrupted' WHERE state='running' AND owner_token <> ?
```

`owner_pid` reste dans la table, à côté, pour une personne qui la lit et qui voudrait aller voir le
processus. Il n'est **jamais** ce qu'on compare, et il n'est pas publié par l'API — une valeur qui
commande une transition d'état n'a rien à faire dans une réponse, et `owner_token` non plus.

Un travail orphelin devient `interrupted`, **jamais repris**. « Ça s'est arrêté, relance-le » est
honnête ; le reprendre en silence revendiquerait les ticks qu'il n'a pas faits et la frontière de
journée qu'il n'a pas banquée.

## Ce que ça coûte

Le jeton ne survit pas à un redémarrage du *processus* — c'est précisément le point — mais il ne
distingue pas non plus deux processus vivants qui partageraient le même store et se seraient
lancés en parallèle. Le contrôle de port l'empêche pour la console, et rien ne l'empêche pour deux
`corparius run` simultanés : c'est `running_job` qui refuse le second, pas ce jeton.

Un travail dont le processus est vivant mais bloqué reste `running` sans limite : il n'y a pas de
battement de cœur. C'est délibéré pour l'instant — un `heartbeat_at` demanderait une écriture
périodique par travail, et le cas mesuré est le processus mort, pas le processus pendu.

`tests/test_durable_jobs.py` tient les deux bouts : un travail dont le jeton est étranger est
balayé même si le PID correspond à ce processus, et le travail de ce processus est laissé
tranquille. Les deux ont été prouvés non vides en réintroduisant le défaut.
