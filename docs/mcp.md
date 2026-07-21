# Serveur MCP

corparius s'expose comme serveur MCP, ce qui permet à un hôte compatible (Claude Cowork, Claude Code, ou un runtime d'agents parlant MCP) de piloter l'entreprise sans passer par la ligne de commande. Le noyau reste indépendant, le serveur n'est qu'une façade fine.

## Lancer

Installer la dépendance optionnelle puis démarrer le serveur en transport stdio.

    pip install -r requirements-mcp.txt
    python -m corparius.mcp_server

## Outils exposés

run pour lancer la boucle, status pour l'état, tasks pour lire le backlog, task pour arbitrer une tâche (le CEO valide, modifie ou refuse), approvals et approve pour la validation humaine des actions sensibles, site et deploy pour la page de vente. Les garde-fous, la mémoire et le stockage local restent en place derrière chaque appel.

## Connexion depuis un hôte

Déclarer le serveur dans la configuration MCP de l'hôte, avec une commande et son dossier de travail.

    {
      "mcpServers": {
        "corparius": {
          "command": "python",
          "args": ["-m", "corparius.mcp_server"],
          "cwd": "C:/Users/mariu/Claude/Projects/Corparius"
        }
      }
    }

## Portée

La logique vit dans des fonctions simples, testées sans la dépendance mcp. Aucune donnée ne sort tant que les fournisseurs tiers ne sont pas configurés, la façade MCP ne change pas ce contrat.
