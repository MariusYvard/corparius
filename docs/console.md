# Console opérateur

La console web (app/webui.py, app/webui.html) sert une page unique sur http://127.0.0.1:8600 via la bibliothèque standard, sans dépendance ni étape de build. Elle lit le même store SQLite que le CLI et pilote le même Runtime.

## Lancement

```bash
python -m app.cli ui                # 127.0.0.1:8600
python -m app.cli ui --port 9000    # port choisi
CORP_UI_HOST et CORP_UI_PORT font la même chose depuis .env
```

## Onglets

Overview donne le pouls de la company : tick courant, actions, tokens cumulés, travail ouvert, avancement des tâches, dépense par agent, métriques de flux lean (débit, encours, goulot, défauts, attente) et l'activité récente. Operations regroupe la file d'approbations HITL (décision inline avec note), le backlog kanban (les propositions s'arbitrent en un clic) et le journal des actions. Providers expose les bascules d'exécution (mock, cloud, Claude Code), les tiers de routage et la saisie des clés d'API par provider. CEO est une conversation avec l'agent CEO, alimentée par l'état réel de la company et servie par le routage configuré (en mode mock, la réponse est déterministe et hors ligne).

## Icônes

Le logo corparius (organigramme pixel-art, un carré CEO au-dessus de trois agents) et les pictogrammes des rôles et des onglets sont des créations du propriétaire du projet (sources dans docs/icons/). Le logo sert de favicon et de marque du header ; le README utilise les bannières docs/banner.svg et banner-dark.svg (thème GitHub), qui embarquent le logo. Ils sont embarqués dans la page en data URI (PNG, fond rendu transparent, mise à l'échelle au plus proche voisin) sur une pastille ivoire lisible dans les deux thèmes.

## API

GET /api/companies, /api/overview?company=, /api/providers, /api/chat?company=. POST /api/approvals {id, decision, note}, /api/tasks {id, decision}, /api/run {company, ticks}, /api/providers {values}, /api/chat {company, message}. Toutes les réponses portent un champ ok.

## Modèle de sécurité

Le serveur écoute sur 127.0.0.1 par défaut. Les clés envoyées depuis la page sont en écriture seule : appliquées au processus, persistées dans .env, jamais renvoyées (l'API n'expose qu'un booléen key_set). Seules les variables du registre et les variables CORP_ de routage sont modifiables ; toute autre variable est refusée. Si CORP_UI_TOKEN est défini, chaque appel mutateur doit porter l'en-tête X-Corp-Token, ce qui protège un déploiement derrière un reverse proxy. Un run lancé depuis la page tourne dans un thread du même processus et passe par le firewall habituel (budget, loop guard, circuit breaker, gate HITL).
