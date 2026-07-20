# Console opérateur

La console web (corparius/webui.py, corparius/webui.html) sert une page unique sur http://127.0.0.1:8600 via la bibliothèque standard, sans dépendance ni étape de build. Elle lit le même store SQLite que le CLI et pilote le même Runtime.

## Lancement

```bash
python -m corparius.cli ui                # 127.0.0.1:8600
python -m corparius.cli ui --port 9000    # port choisi
CORP_UI_HOST et CORP_UI_PORT font la même chose depuis .env
```

## Onglets

Overview donne le pouls de la company. « En attente de vous » mène la ligne et se clique : le portail humain est le sujet du produit, il n'a pas à se chercher. Suivent l'avancement des tâches, la dépense par agent, les métriques de flux lean (débit, encours, goulot, défauts, attente), le site de vente et les paiements. Operations regroupe la file d'approbations HITL (décision inline avec note), le backlog kanban (arbitrage et édition de titre ou de priorité en place), la sauvegarde et le journal des actions. Providers expose les bascules d'exécution (mock, cloud, Claude Code), les tiers de routage et la saisie des clés par provider. CEO est une conversation avec l'agent CEO, alimentée par l'état réel de la company. Réglages contient l'éditeur de société et toute la configuration.

## Rien à éditer à la main

La console écrit tout ce que corparius lit. L'éditeur de société couvre chaque champ de `company.yaml` (offre, prix, lien de paiement, ICP, canaux, agents, budgets, outils sous approbation) ; enregistrer réécrit le fichier depuis ces champs, donc les commentaires ajoutés à la main ne survivent pas. La suppression exige de taper le slug et déplace la config dans `companies/.trash/` : rien n'est détruit. Un fichier cassé s'ouvre quand même, avec ses problèmes nommés, plutôt que de renvoyer une erreur qui laisserait l'opérateur sans moyen de le réparer.

L'onglet Réglages couvre le reste, groupe par groupe, piloté par le registre `corparius/settings_spec.py` : ajouter un réglage est une ligne, pas une modification du HTML. Chaque champ affiche la couche qui lui répond et se met en lecture seule quand l'environnement du processus le fixe (voir la table de précédence du README) — un réglage n'est jamais ignoré en silence.

## Compte mail

Un compte, dans les deux sens. Choisissez le fournisseur, donnez l'adresse et un mot de passe d'application : les serveurs et ports SMTP et IMAP sont déduits et repliés sous « Réglages déduits ». Le bouton « Tester ce compte » envoie un vrai message et lit vraiment la boîte, puis rapporte les deux moitiés séparément — elles échouent pour des raisons différentes. Les diagnostics nomment le remède, pas le protocole.

La lecture est en lecture seule : corparius ouvre la boîte en `readonly`, n'a jamais marqué un message comme lu, ne déplace rien et ne supprime rien. Elle sert à deux choses : le triage du support, et surtout savoir quels prospects ont répondu (`scan_replies`, agent outreach), ce qui ferme la boucle de la prospection.

## Icônes

Le logo corparius (organigramme pixel-art, un carré CEO au-dessus de trois agents) et les pictogrammes des rôles et des onglets sont des créations du propriétaire du projet (sources dans docs/icons/). Le logo sert de favicon et de marque du header ; le README utilise les bannières docs/banner.svg et banner-dark.svg (thème GitHub), qui embarquent le logo. Ils sont embarqués dans la page en data URI (PNG, fond rendu transparent, mise à l'échelle au plus proche voisin) sur une pastille ivoire lisible dans les deux thèmes.

## Première utilisation et diagnostics

Sans company existante, la console affiche un formulaire de création (nom et offre suffisent ; agents et budget ont des valeurs par défaut). L'option "+ Nouvelle société" du sélecteur rouvre ce formulaire ensuite. L'onglet Réglages embarque le diagnostic (équivalent de `python -m corparius.cli doctor`) : chaque vérification indique son niveau et l'action corrective.

## Site et paiements

La carte "Site de vente" de la vue d'ensemble montre un aperçu réduit du site généré (data/sites/<slug>/index.html, servi sur /site/<slug>/), avec génération et régénération en un clic ; le déploiement reste une action HITL. La carte "Paiements" lit les encaissements Stripe avec STRIPE_API_KEY (clé de lecture restreinte) et affiche des données d'exemple étiquetées sinon.

## API

GET `/api/companies`, `/api/overview?company=`, `/api/company?company=`, `/api/settings`, `/api/session`, `/api/providers`, `/api/doctor`, `/api/site?company=`, `/api/payments`, `/api/chat?company=`, `/site/<slug>/`.

POST `/api/companies` {name, product, agents, session_tokens}, `/api/company` {company, config}, `/api/company/delete` {company, confirm, purge_store}, `/api/settings` {values, unset}, `/api/providers` {values}, `/api/site` {company, headline}, `/api/deploy` {company}, `/api/backup`, `/api/run` {company, ticks, loop}, `/api/run/stop` {company}, `/api/approvals` {id, decision, note}, `/api/tasks` {id, decision | title, priority, target, tool}, `/api/chat` {company, message}, `/api/test/mail` {to}, `/api/test/payments`.

Toutes les réponses portent un champ `ok`, qui qualifie la requête et non son verdict : un test SMTP qui échoue renvoie `200 {ok: true, result: {ok: false, detail: ...}}`, et un déploiement qui ne publie rien renvoie `200 {ok: true, published: false}`. La distinction compte : un échec métier n'est pas une erreur d'API, et il ne doit pas non plus être maquillé en succès.

## Modèle de sécurité

Le serveur écoute sur 127.0.0.1 par défaut. Les secrets envoyés depuis la page sont en écriture seule : stockés, jamais renvoyés, l'API n'expose qu'un booléen `configured`. Seules les clés du registre sont modifiables ; toute autre variable est refusée. Si `CORP_UI_TOKEN` est défini, chaque appel mutateur doit porter l'en-tête `X-Corp-Token` — la page l'envoie et propose de le saisir sur un 401. Le doctor **échoue** si la console est exposée hors localhost sans token : elle peut dépenser de l'argent et publier.

Les secrets sont stockés en clair dans `data/corparius.sqlite` (comme ils l'étaient dans `.env`) et se retrouvent donc dans les archives de `backup` ; le panneau et le doctor le disent. Sur POSIX la base est passée en 0600 ; sur Windows c'est sans effet.

Un run lancé depuis la page tourne dans un thread du même processus et passe par le firewall habituel (budget, loop guard, circuit breaker, gate HITL). Une boucle lancée depuis la console vit dans le processus console : la fermer l'arrête, contrairement au profil docker `loop`. Le bouton Stop pose un drapeau que le runtime consulte à chaque tick — le thread n'est jamais tué, et seules les heures réellement jouées sont comptées.
