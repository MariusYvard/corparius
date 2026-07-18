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

## Indicateurs de sécurité

L'ingénierie de fiabilité des agents suit des indicateurs de conformité, par exemple la part des actions financières et des écritures système qui ont respecté la pré-approbation et l'audit. Dans corparius, le journal des approbations et le journal des actions fournissent cette trace. Chaque action porte l'agent qui l'a déclenchée, chaque outil sensible laisse une demande d'approbation datée.

## Validation humaine

Certaines actions ne s'exécutent jamais sans accord. Tout outil listé dans CORP_HITL_TOOLS (par défaut send_financial_transaction et publish_production_code) met le flux en pause et dépose une demande d'approbation avec le nom de l'outil et ses paramètres. L'exploitant approuve ou rejette depuis la CLI, ou via un canal externe comme n8n, Slack, Telegram ou courriel. Un rejet est rendu à l'agent comme une erreur d'outil récupérable, avec le message "Tool execution denied: Approval rejected by administrator."

Bonne pratique d'intégration: ne pas déléguer au modèle l'extraction des métadonnées de la demande (objet, expéditeur, corps). Un nœud de récupération déterministe (requête directe ou lecture de message) hydrate la demande transmise à l'humain, ce qui écarte toute mauvaise interprétation.

Côté dépôt de code, le même principe existe chez GitHub Agentic Workflows. L'agent tourne en lecture seule par défaut, et toute écriture (Pull Request, commentaire, validation d'une issue) transite par un sous-système de sorties sécurisées qui applique des filtres déterministes avant soumission.

## Instructions données à l'agent

L'agent est informé de ces barrières dans son invite système. En cas de rejet, il doit informer l'exploitant, analyser les motifs si des commentaires ont été saisis puis proposer une correction ou demander des clarifications, sans relancer l'outil ni ouvrir d'autres tâches en parallèle.

## Secrets au repos

Par défaut, les clés API et jetons enregistrés depuis la console sont stockés en clair dans la base SQLite (`data/corparius.sqlite`), et le doctor le signale. Sur les systèmes POSIX, corparius pose des permissions propriétaire-seul (dossier `0700`, base `0600`) ; sous Windows, `%LOCALAPPDATA%` est déjà propre au compte. Traitez ce fichier comme un mot de passe.

Pour chiffrer ces secrets au repos, définissez `CORP_SECRET_KEY` (une phrase secrète). Les réglages marqués secrets sont alors chiffrés dans la base et dans les sauvegardes, via le paquet `cryptography` (`pip install -r requirements-secrets.txt`). Le chiffrement est **désactivé par défaut** pour que le mode mock hors-ligne n'exige aucune dépendance. La clé est dérivée de la phrase secrète par scrypt ; les valeurs chiffrées portent un préfixe `enc:v1:`, et les valeurs en clair déjà présentes restent lisibles jusqu'à leur prochaine écriture.

Propriété importante : `CORP_SECRET_KEY` est une clé de démarrage, écrite dans `.env` (ou l'environnement), **jamais dans la base** — sinon il faudrait la base pour se déchiffrer elle-même. Comme `app/backup.py` archive `data/` et `companies/` mais **pas** `.env`, une sauvegarde volée ne contient que des secrets chiffrés, pas la phrase qui les ouvre. En contrepartie : perdez la phrase et les secrets chiffrés sont irrécupérables. Effectif au redémarrage.

## Sources

- https://techcommunity.microsoft.com/blog/linuxandopensourceblog/applying-site-reliability-engineering-to-autonomous-ai-agents/4521357
- https://docs.n8n.io/build/integrate-ai/ai-examples/human-in-the-loop-for-tools
- https://github.blog/ai-and-ml/automate-repository-tasks-with-github-agentic-workflows/
- https://www.anthropic.com/engineering/code-execution-with-mcp
