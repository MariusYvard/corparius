# Backlog et gouvernance des tâches

L'entreprise tient une file de tâches par société. La règle est simple: le CEO décide, les autres exécutent.

## Rôles

Le CEO crée des tâches approuvées et arbitre les propositions. Les agents opérationnels exécutent, à chaque tour, la tâche approuvée la plus prioritaire visant leur rôle, puis la marquent terminée. Certains agents comme la stratégie et le support peuvent proposer une tâche, mais la validation, la modification ou le refus reviennent au CEO.

## Statuts

Une tâche passe par proposed, approved, in_progress, done ou rejected. Une proposition reste proposed jusqu'à la revue du CEO. Le CEO valide (approved) ou refuse (rejected), et peut modifier le titre ou la priorité. Seules les tâches approved sont exécutables.

## Revue

À son tour, le CEO lit les propositions et en valide un nombre plafonné par CORP_CEO_APPROVE_CAP, le reste étant refusé. Ce plafond garde le CEO maître du volume entrant.

## Consultation

La commande `python -m app.cli tasks --company example` liste les tâches avec leur statut, leur priorité, l'agent cible et l'auteur.
