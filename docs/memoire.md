# Mémoire

Une entreprise corparius a deux mémoires, et elles ne servent pas à la même chose.

**Hier**, ce sont les trois derniers résumés de fin de journée, relus à chaque frontière de jour. C'est ce qui empêche une entreprise en `--loop` de planifier chaque matin comme si elle venait de naître. Le garde-fou est correct, et il est testé (`tests/test_memory.py`).

**Ce qui reste vrai**, c'est la mémoire durable décrite ici. Un horizon de trois jours efface tout ce qu'une entreprise apprend sur son marché: quel segment renouvelle, quelle objection revient, quelle promesse ne tient pas. Ces faits-là n'ont pas de raison d'expirer un mardi.

Les deux sont volontairement séparées. `ctx.memory` reste la liste des résumés, lue positionnellement par `set_daily_plan`; y fondre les faits durables aurait fait de `memory[0]` un fait au lieu d'hier, et cassé cet outil sans casser de test.

## Qui écrit

L'outil `remember` figure dans les playbooks du PDG et de la stratégie. Il déclare un schéma, donc ce qui est stocké est un `fact` et un `why` validés, pas la prose que le modèle a produite. C'est le seul endroit où le modèle décide de *quoi* retenir; *quand* retenir reste dans le playbook, comme tout le reste du flux de contrôle.

L'outil est de classe de risque `read`: il écrit dans le magasin de l'exploitant et rien ne sort du processus.

## Comment un fait revient

À chaque invite, `recall` classe les faits: épinglés d'abord, puis par pertinence pour l'invite sur le point d'être envoyée, puis par récence. Les `CORP_MEMORY_TOP_K` premiers (5 par défaut) entrent dans l'invite système.

Le classement se fait en Python sur quelques centaines de lignes plutôt qu'en SQL: l'ordre est sémantique, et le pousser dans la requête aurait imposé soit une extension vectorielle, soit un `LIKE` qui compare des mots au lieu d'un sens.

## Ce que la déduplication attrape, et ce qu'elle n'attrape pas

Un agent à qui l'on pose la même question tous les jours reformule une même observation. Une mémoire qui se remplit de reformulations est une mémoire qui chasse ce qui comptait, donc `remember` refuse un fait qu'elle tient déjà.

La comparaison est un cosinus sur `safety.hash_embed`, le plongement sac-de-mots sans dépendance déjà écrit pour le garde-boucle, après normalisation de la casse et de la ponctuation. Elle reconnaît donc une observation redite dans un autre ordre, avec d'autres majuscules ou une autre ponctuation.

Elle **ne fait pas** de détection de paraphrase. « les coachs renouvellent » et « nos clients accompagnés restent » sont deux faits de son point de vue. Descendre le seuil jusqu'à les confondre reviendrait à fusionner des faits qui se ressemblent seulement, ce qui perd de l'information au lieu d'économiser de la place. Attraper cela demanderait un vrai modèle d'embedding, et donc une dépendance que ce projet n'a pas.

Aucun magasin vectoriel n'est utilisé. Le service pgvector du profil `extras` de `docker-compose.yml` reste inutilisé.

## Le plafond

`CORP_MEMORY_MAX` (200 par défaut) plafonne les faits **non épinglés**, les plus anciens supprimés en premier. Un fait épinglé n'est ni compté ni supprimé par le plafond: le compter voudrait dire qu'épingler assez de faits arrête silencieusement l'entreprise d'apprendre.

## Ce que l'exploitant peut faire

La console liste la mémoire dans l'onglet Operations, chaque ligne épinglable et supprimable. En ligne de commande:

```bash
corparius memory --company <slug>              # lister, les épinglés marqués *
corparius memory --company <slug> --pin 12     # garder toujours
corparius memory --company <slug> --forget 12  # ce que l'agent a eu faux
```

Un fait faux doit pouvoir disparaître sans ouvrir la base. L'exploitant possède la mémoire de son entreprise au même titre que ses secrets.

`CORP_MEMORY_ENABLED=false` coupe l'ensemble, écriture comme rappel.
