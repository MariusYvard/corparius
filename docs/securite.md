# Sécurité et validation humaine

Laisser un agent appeler des API sans contrôle de bas niveau expose à des coûts d'emballement et à des actions irréversibles. corparius place trois garde-fous devant chaque tour d'agent, plus une validation humaine sur les actions sensibles.

## Budget de jetons

Un plafond par session est vérifié avant chaque appel au modèle et mis à jour après. Quand le solde est consommé, l'agent s'arrête et l'incident est journalisé. Le plafond par défaut est de 100 000 jetons, ajustable par entreprise. Le risque visé est la boucle qui reformule la même requête après une erreur, chaque itération concaténant l'historique et augmentant le coût unitaire.

## Détection de boucle

Deux signaux arrêtent un agent qui bégaie. Le premier est la similarité sémantique, mesurée par la similarité cosinus entre les représentations vectorielles des sorties successives. Si elle reste au-dessus de 0,95 sur trois itérations, l'exécution est suspendue. La formule est cos(theta) = (A . B) / (||A|| ||B||). Le second signal est l'appel d'outil répété: le même outil avec des paramètres identiques plus de deux fois de suite déclenche l'arrêt.

## Coupe-circuit de vélocité

Un agent normal alterne appels au modèle et attentes d'entrée-sortie, sous quelques milliers de jetons par minute. Une consommation continue au-dessus du seuil (10 000 jetons par minute par défaut) fait basculer le mode de fonctionnement, selon une cascade de dégradation calquée sur l'ingénierie de fiabilité des agents. Le mode NORMAL est le fonctionnement nominal. Le mode CONSERVATEUR réduit la posture et journalise une alerte. Le mode SECURISE gèle la session, aucun agent n'est plus lancé et une action d'alerte est enregistrée pour l'astreinte. Cette cascade est active dans le code, le passage en SECURISE interrompt le run et laisse l'exploitant reprendre après examen.

## Configuration à deux niveaux

Deux fichiers séparent la règle dure de la règle comportementale. Un fichier d'orchestration force l'arrêt système si un outil est appelé avec des paramètres identiques plusieurs fois de suite. Un fichier d'instructions impose à l'agent d'examiner son propre historique de planification à chaque tour et de s'arrêter s'il ne progresse pas vers l'état visé.

### Le coupe-circuit ne se dé-escalade pas

`CircuitBreaker.record` faisait auparavant `SAFE si mode == CONSERVATEUR sinon CONSERVATEUR`, ce qui rendait le mode SECURISE réversible à la dépense suivante. Le mode dans lequel une session terminait un tour dépendait donc de la parité du nombre de dépenses, et une journée emballée pouvait sortir du gel qu'elle venait de mériter en dépensant davantage. Ajouter un outil à un playbook suffisait à déplacer cette parité. L'escalade est désormais monotone tant que la vélocité dépasse le plafond; le retour à NORMAL reste possible quand la fenêtre glissante de 60 secondes repasse sous le plafond, sans quoi un seul pic condamnerait l'entreprise définitivement.

## Indicateurs de sécurité

L'ingénierie de fiabilité des agents suit des indicateurs de conformité, par exemple la part des actions financières et des écritures système qui ont respecté la pré-approbation et l'audit. Dans corparius, le journal des approbations et le journal des actions fournissent cette trace. Chaque action porte l'agent qui l'a déclenchée, chaque outil sensible laisse une demande d'approbation datée.

## Validation humaine

Certaines actions ne s'exécutent jamais sans accord. Tout outil listé dans CORP_HITL_TOOLS (par défaut send_financial_transaction, publish_production_code et deploy_site) met le flux en pause et dépose une demande d'approbation avec le nom de l'outil et ses paramètres. L'exploitant approuve ou rejette depuis la console, la CLI, le serveur MCP, ou via un canal externe comme n8n, Slack, Telegram ou courriel. Un rejet est rendu à l'agent comme une erreur d'outil récupérable, avec le message "Tool execution denied: Approval rejected by administrator."

### Ce qui décide de demander

Une liste de noms ne répond qu'à « est-ce que ça s'arrête », jamais à « pourquoi celui-là est passé ». Depuis les classes de risque, la décision se compose de trois éléments, résolus par `corparius/permissions.py`.

Chaque outil déclare une classe de risque décrivant son effet sur le monde extérieur, pas son sujet: `read` (lit, rédige, calcule, rien ne sort du processus), `write_local` (écrit sous le répertoire de données), `external` (appelle un tiers, ou quelqu'un reçoit quelque chose), `code` (livre du code à un endroit qui l'exécute), `money` (déplace l'argent de l'exploitant). Rédiger une note de prix est `read`; envoyer un seul courriel froid est `external`.

L'exploitant choisit un mode et un seuil. `CORP_PERMISSION_MODE` vaut `discuss` (répétition à blanc: rien de conséquent ne s'exécute, et rien ne s'empile dans la file), `interactive` (défaut: tout ce qui dépasse le seuil demande), `auto` (rien ne demande, sauf les outils nommés) ou `custom` (interactive plus la liste `CORP_AUTO_ALLOW`). `CORP_ASK_ABOVE` fixe le seuil, `external` par défaut: combiné aux trois outils nommés, cela reproduit exactement le comportement d'avant les classes de risque, donc une mise à jour ne change rien tant que l'exploitant ne le demande pas. Passer le seuil à `read` fait confirmer chaque effet de bord.

L'ordre de résolution est explicite et une interdiction déclarée l'emporte toujours. Un outil nommé dans `hitl_tools`, ou portant `hitl=True`, demande quelle que soit la suite: ni le mode `auto`, ni `auto_allow`, ni une règle permanente ne peuvent le taire. Sans cela, la seule garantie que le produit donne dépendrait de l'ordre dans lequel l'exploitant a cliqué.

Une règle permanente est un « approuver, et ne plus demander » accordé depuis la console ou par `corparius approve --always`. Sa portée est une entreprise et un outil; `run` expire avec l'exécution qui l'a accordée, `always` persiste jusqu'à révocation (`corparius rules --revoke`). Le journal des actions porte désormais, à côté de chaque appel, la classe de risque, le motif de la décision et la règle qui l'a produite.

### Demander, et prévenir

Une approbation répond à « puis-je faire ceci ». Deux choses n'avaient jusqu'ici nulle part où aller.

Un agent à qui il manque un fait ne pouvait pas le demander. Une prospection sans boîte mail configurée, un déploiement sans fournisseur: chacun mourait à l'intérieur d'un outil, laissait une ligne dans le journal des actions et n'était plus jamais vu. L'entreprise continuait comme si de rien n'était, ce qui est la même défaillance qu'inventer une réponse, une couche plus bas. Et une session qui se gèle elle-même n'avait aucun moyen de le dire: un déclenchement du coupe-circuit ou un modèle injoignable écrivait une ligne, et l'entreprise pouvait rester morte une journée.

`corparius/inbox.py` ajoute donc deux genres à côté de l'approbation. Une **question** bloque le travail qui l'a soulevée, exactement comme une approbation — même résultat `pending`, même tâche mise de côté — et le débloque à la réponse. Un **avis** ne bloque rien et existe pour être vu.

L'identité est un hachage de ce qui est demandé, pas un identifiant neuf à chaque tentative, donc rejouer un tick retrouve la question déjà posée au lieu de la poser deux fois. Une réponse est appariée sur l'intitulé et non sur l'identifiant, qui inclut l'agent: « depuis quelle boîte mail ? » répondu pour la prospection l'est aussi pour le support, sinon l'exploitant se ferait poser la même question une fois par rôle. Une résolution est unique et le premier arrivé gagne: le travail en attente est déjà reparti sur la première réponse, et réécrire l'enregistrement laisserait le magasin en désaccord avec ce qui s'est produit.

Les surfaces sont les mêmes que pour les approbations: console, `corparius inbox` et `corparius inbox --answer-to <id> --answer "..."`, et les outils MCP `inbox` et `answer`.

### Attendre sans s'arrêter

Une approbation en attente ne suspend plus le tour de l'agent. Auparavant une question non répondue sur un paiement empêchait le même agent de faire les autres choses de son playbook, et la tâche derrière repartait en file pour être reprise au tour suivant et redéposer la même demande: l'entreprise dépensait son budget à reposer une question et ne faisait rien d'autre.

Désormais un garde-fou qui se déclenche arrête le tour, un humain sollicité non. La tâche concernée est mise de côté au statut `waiting` avec l'identifiant de l'approbation qui la débloquerait, statut que `claim_next_task` ignore, donc l'agent passe directement à la suivante. À chaque tick, `release_waiting_tasks` relit les réponses arrivées entre-temps et remet en file ce qui a été approuvé, ferme ce qui a été refusé. La lecture est faite par sondage et non par notification, parce qu'une approbation peut être tranchée depuis la console, la CLI ou un hôte MCP, et qu'une exécution peut être redémarrée entre la question et la réponse.

Le travail bloqué est compté à part du travail en cours (`blocked` dans les indicateurs de flux). Le compter dans l'en-cours flatterait le tableau; le facturer sur la limite de tirage laisserait quatre approbations sans réponse empêcher l'entreprise de commencer quoi que ce soit d'autre, ce qui est l'inverse du but.

Enfin, un outil déjà en attente pour cette entreprise n'est pas redemandé: la vérification a lieu avant la rédaction, donc aucun appel de modèle n'est dépensé à produire une seconde demande identique. Cela n'élargit pas la porte, puisque l'association d'une approbation à une exécution continue de comparer les paramètres exactement.

Bonne pratique d'intégration: ne pas déléguer au modèle l'extraction des métadonnées de la demande (objet, expéditeur, corps). Un nœud de récupération déterministe (requête directe ou lecture de message) hydrate la demande transmise à l'humain, ce qui écarte toute mauvaise interprétation.

Côté dépôt de code, le même principe existe chez GitHub Agentic Workflows. L'agent tourne en lecture seule par défaut, et toute écriture (Pull Request, commentaire, validation d'une issue) transite par un sous-système de sorties sécurisées qui applique des filtres déterministes avant soumission.

## Instructions données à l'agent

L'agent est informé de ces barrières dans son invite système. En cas de rejet, il doit informer l'exploitant, analyser les motifs si des commentaires ont été saisis puis proposer une correction ou demander des clarifications, sans relancer l'outil ni ouvrir d'autres tâches en parallèle.

## Secrets au repos

Par défaut, les clés API et jetons enregistrés depuis la console sont stockés en clair dans la base SQLite (`data/corparius.sqlite`), et le doctor le signale. Sur les systèmes POSIX, corparius pose des permissions propriétaire-seul (dossier `0700`, base `0600`) ; sous Windows, `%LOCALAPPDATA%` est déjà propre au compte. Traitez ce fichier comme un mot de passe.

Pour chiffrer ces secrets au repos, définissez `CORP_SECRET_KEY` (une phrase secrète). Les réglages marqués secrets sont alors chiffrés dans la base et dans les sauvegardes, via le paquet `cryptography` (`pip install -r requirements-secrets.txt`). Le chiffrement est **désactivé par défaut** pour que le mode mock hors-ligne n'exige aucune dépendance. La clé est dérivée de la phrase secrète par scrypt ; les valeurs chiffrées portent un préfixe `enc:v1:`, et les valeurs en clair déjà présentes restent lisibles jusqu'à leur prochaine écriture.

Propriété importante : `CORP_SECRET_KEY` est une clé de démarrage, écrite dans `.env` (ou l'environnement), **jamais dans la base** — sinon il faudrait la base pour se déchiffrer elle-même. Comme `corparius/backup.py` archive `data/` et `companies/` mais **pas** `.env`, une sauvegarde volée ne contient que des secrets chiffrés, pas la phrase qui les ouvre. En contrepartie : perdez la phrase et les secrets chiffrés sont irrécupérables. Effectif au redémarrage.

## Sources

- https://techcommunity.microsoft.com/blog/linuxandopensourceblog/applying-site-reliability-engineering-to-autonomous-ai-agents/4521357
- https://docs.n8n.io/build/integrate-ai/ai-examples/human-in-the-loop-for-tools
- https://github.blog/ai-and-ml/automate-repository-tasks-with-github-agentic-workflows/
- https://www.anthropic.com/engineering/code-execution-with-mcp
