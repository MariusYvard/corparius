# Backlog et gouvernance des tâches

L'entreprise tient une file de tâches par société. La règle est simple: le CEO décide, les autres exécutent.

## Rôles

Le CEO crée des tâches approuvées et arbitre les propositions. Les agents opérationnels exécutent, à chaque tour, la tâche approuvée la plus prioritaire visant leur rôle, puis la clôturent. La stratégie et le support peuvent proposer une tâche, mais la validation, la modification ou le refus reviennent au CEO.

## Statuts

Une tâche passe par proposed, approved, in_progress, done ou rejected. Une proposition reste proposed jusqu'à la revue du CEO. Seules les tâches approved sont exécutables.

## Revue et modification

À son tour, le CEO lit les propositions et en valide un nombre plafonné par CORP_CEO_APPROVE_CAP, le reste étant refusé. Valider ne se limite pas à accepter: le CEO modifie la proposition pour la rendre actionnable, il relève sa priorité et lui associe un outil exécutable selon la cible. Une modification manuelle reste possible avec la commande `task --id N`, qui change le titre, la cible, l'outil ou la priorité, et peut approuver ou refuser.

## Exécution réelle

Chaque tâche porte un outil. Quand un agent prend une tâche approuvée, il n'en simule pas la clôture, il exécute l'outil associé à travers le pare-feu de sécurité et la validation humaine, puis clôt la tâche avec le résultat produit. Une tâche sans outil est close symboliquement. Le CEO relie les rôles aux outils: la prospection à l'envoi de courriels, le social à la rédaction de posts, le support à la réponse client, le design à la génération du site.

## Consultation

La commande `python -m app.cli tasks --company example` liste les tâches avec leur statut, leur priorité, la cible, l'outil et l'auteur.
