# 0006 — Sept coutures de greffons, consommées paresseusement

## Contexte

Un greffon doit pouvoir étendre corparius sans toucher au cœur, et sans que le cœur paie
quoi que ce soit quand aucun greffon n'est installé — ce qui est le cas par défaut.

## Décision

Sept registres au niveau module, chacun consommé **au moment de l'appel** et non à l'import :
fournisseurs LLM, fournisseurs de déploiement, sources de prospects, enrichisseurs, outils,
dossiers de skills, modèles d'entreprise. Plus la personnalisation d'un agent existant.

Un greffon reçoit une façade, `PluginAPI`, dont chaque méthode importe le module cible **dans
son corps** — de sorte que le chargeur n'est jamais appelé par un simple
`import corparius`.

## Ce qui est délibérément absent

`customize_agent` peut modifier une entrée de `ROSTER` mais **pas ajouter un rôle** :
`AgentRole` est une énumération fermée. Un rôle qu'aucun code ne connaît est un rôle dont
rien ne peut lire les résultats.

## Coût

Ce sont les seuls imports différés du paquet qui ne cassent pas un cycle — et donc les seuls
que le test de couches doit laisser passer en les distinguant. C'est pour ça que le motif est
écrit ici.

## Où c'est appliqué

`corparius/plugins.py:1-28` (le raisonnement), `:53-105` (les sept méthodes).
