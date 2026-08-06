# OpenWorker

OpenWorker est un agent de bureau libre publié par Andrew Ng sous licence MIT. Il ne vend pas une entreprise autonome mais un collègue : l'utilisateur décrit un résultat, l'agent découpe la tâche, travaille dans les applications du poste et rend un livrable fini. Contrairement à NanoCorp et Polsia, il est auto-hébergé et fonctionne avec les clés de l'utilisateur, ce qui en fait le seul comparable direct de corparius sur la souveraineté.

## Architecture

Trois couches : une coquille de bureau Tauri avec une interface React, un serveur d'agent Python bâti sur aisuite, et une couche d'intégration de plus de vingt-cinq connecteurs (GitHub, Slack, Jira, Notion, HubSpot, Outlook, Gmail) doublée d'un client MCP. Un module Rust séparé assure la reconnaissance vocale.

Le paquet Python `coworker/` est découpé en sous-systèmes : `agents`, `automation`, `connectors`, `mcp`, `memory`, `personas`, `providers`, `server`, `skills`, `tools`, `tui`, `web`, avec au premier niveau `engine.py`, `permissions.py`, `inbox.py`, `audit.py`, `sessions.py` et `risk`.

Le moteur est une boucle ReAct classique : `TurnEngine` enchaîne des allers-retours modèle/outils jusqu'à ce que le modèle cesse de demander des outils, qu'un garde-fou se déclenche ou que l'utilisateur interrompe. Le modèle choisit ses outils. C'est la différence structurante avec corparius, dont le flux de contrôle reste dans le code.

## Ce que corparius en tire

Quatre sous-systèmes d'OpenWorker sont plus mûrs que leurs équivalents corparius et comblent des manques déjà inscrits dans `docs/roadmap-90j.md`. Chacun est repris pour sa structure de données et sa sémantique, jamais pour l'agence qu'il accorde au modèle.

### Les permissions par classe de risque

`permissions.py` remplace le drapeau binaire par un moteur de décision. Un mode d'exploitation (`discuss`, `plan`, `interactive`, `auto`, `custom`) croise une classe de risque déduite de l'appel (`EXEC`, `WRITE_LOCAL`, `EXTERNAL`), une liste d'autorisations préalables et des règles permanentes portées par la session ou par la tâche. Le résultat est un objet `Decision` qui transporte non seulement l'autorisation mais le motif et la règle qui l'a produite, ce qui alimente la piste d'audit.

Deux détails valent d'être repris tels quels. Un ordre de résolution explicite, où une interdiction déclarée l'emporte toujours sur une règle permanente. Et le refus d'appliquer une autorisation de commande quand la commande contient des métacaractères de shell qui la transformeraient en plusieurs commandes.

Corparius s'en tient aujourd'hui à `tool.hitl or tool.name in hitl_tools`, alors que la porte humaine est la promesse centrale du produit. La reprise annote les vingt-huit outils d'une classe de risque, conserve `hitl_tools` comme forçage explicite, et journalise enfin le motif d'une exécution autorisée.

### Les compétences en prose

`skills/base.py` définit une compétence comme un dossier contenant un `SKILL.md` à en-tête YAML : un nom, une description, une liste d'outils concernés, et un corps d'instructions. Le catalogue seul, noms et descriptions, est injecté au départ ; le corps n'est chargé que lorsqu'il devient pertinent. C'est de la divulgation progressive, et c'est une réponse directe au coût en jetons d'un contexte qui grossit.

Corparius dispose de plugins, mais ce sont du code : sept coutures d'extension, une liste blanche vérifiée par empreinte, une porte d'entrée qui suppose du Python. Aucun véhicule n'existe pour du savoir métier écrit en prose, alors qu'une micro-entreprise en produit dès le premier jour.

L'adaptation porte sur le déclencheur. OpenWorker charge le corps d'une compétence par un appel d'outil du modèle, parce qu'il a une boucle qui le permet. Corparius n'en a pas et n'en veut pas : c'est l'exécuteur qui sélectionne les compétences dont l'en-tête `allowed-tools` cite l'outil en cours. Même économie de jetons, sélection par le code.

### La mémoire persistante

`memory/` sépare une abstraction, un magasin SQLite et des outils exposés à l'agent. La mémoire y est adressable et survit aux sessions.

Corparius se limite aux trois derniers résumés de fin de journée, relus à chaque frontière de jour. Le garde-fou est correct — une boucle qui n'aurait pas relu ce qu'elle écrit planifierait chaque matin comme si elle venait de naître — mais l'horizon de trois jours efface tout ce qu'une entreprise apprend sur son marché.

La reprise ajoute une table de mémoire et un rappel par pertinence. Elle n'introduit aucune dépendance vectorielle : `corparius/safety.py` contient déjà `hash_embed`, un plongement déterministe sans dépendance écrit pour la détection de boucles, et sa similarité cosinus suffit à classer quelques dizaines de faits. Le service pgvector présent dans le profil `extras` du `docker-compose.yml` reste inutilisé.

### La boîte de réception typée

`inbox.py` généralise l'approbation. Un élément porte un genre — approbation, **question**, notification, plan — un état qui va de `pending` à `resolved` une seule fois, et une visibilité qui distingue une session surveillée d'une exécution sans témoin. L'identité est la paire session et identifiant d'appel d'outil, si bien qu'un agent redémarré retrouve l'élément existant au lieu de reposer sa question. À la reprise, `reconcile_on_resume` remonte les éléments en attente et récapitule ceux qui ont été tranchés.

Corparius a les approbations et leur identifiant md5 déterministe, mais rien d'autre. Un agent qui ignore le prix cible ou l'adresse d'un interlocuteur n'a aucun moyen de demander : il invente. Et un gel de coupe-circuit n'est visible que si l'opérateur pense à lire le journal des actions.

La reprise ajoute les genres question et notification à côté de la table d'approbations, qui reste inchangée. Le mécanisme de rupture de tour est déjà là : une question en attente renvoie le même `pending` qu'une approbation.

## Ce que corparius ne reprend pas

**La boucle ReAct et le choix d'outils par le modèle.** `docs/architecture.md` écarte la topologie à routeur dynamique après le démontage de Polsia, dont le taux de succès mesuré sur tâches complexes est de 21,3 %. Corparius garde la spécialisation par rôle sans l'autonomie de routage : le modèle rédige, le code décide.

**Les sous-agents.** `coworker/tools/subagent.py` permet à un agent d'en engendrer d'autres. La même page d'architecture cite le gain mesuré par Anthropic sur une topologie agent principal et sous-agents, et range malgré tout le parallélisme dans les analyses lourdes hors périmètre initial. Un sous-agent qui dépense un budget non plafonné contredit le pare-feu que corparius met en tête.

**Les vingt-cinq connecteurs et leurs poignées de main OAuth.** OpenWorker route ces échanges par une infrastructure hébergée. Corparius s'en tient à des outils remplaçables un par un et à deux dépendances d'exécution.

**Tauri, React et aisuite.** La console corparius est un serveur `http.server` de la bibliothèque standard et une page unique sans étape de construction. aisuite serait une troisième dépendance pour ce que `corparius/llm.py` fait déjà à la main sur quatorze fournisseurs, dont deux qu'aisuite ne couvre pas : l'interface en ligne de commande de Claude Code et Ollama en repli systématique.

**Le fichier `config.toml`.** Le résolveur à quatre couches de `corparius/config/cfg.py` et le registre de `corparius/config/settings_spec.py` répondent déjà au besoin, en montrant en plus quelle couche répond pour chaque champ.

## Sources

- https://github.com/andrewyng/openworker
- https://github.com/andrewyng/openworker/blob/main/coworker/permissions.py
- https://github.com/andrewyng/openworker/blob/main/coworker/inbox.py
- https://github.com/andrewyng/openworker/blob/main/coworker/skills/base.py
