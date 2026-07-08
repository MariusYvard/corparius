# Polsia

Polsia est une plateforme d'exploitation d'entreprises autonomes. Le produit repose sur neuf agents cognitifs qui planifient, construisent, commercialisent et opèrent une activité de bout en bout. La société a levé 30 millions de dollars sur une valorisation de 250 millions, avec un fondateur solo.

## Architecture des neuf agents

Chaque agent tourne sur un planning décalé, ce qui évite un pic de consommation simultané.

| Agent | Fréquence | Tâches |
| --- | --- | --- |
| Orchestrateur (CEO) | deux fois par jour | plan du matin, arbitrage des priorités, synthèse du soir |
| Médias sociaux | toutes les 2 h | rédaction et publication de contenus (X, LinkedIn) |
| Prospection | toutes les 3 h | ciblage sur données enrichies, envoi de courriels froids |
| Support client | toutes les 3 h | analyse de la boîte de réception, propositions de réponses |
| Publicité | toutes les 6 h | suivi des budgets, variantes de messages, ajustement des enchères |
| Finance | toutes les 6 h | synchronisation Stripe, dépenses d'infrastructure, bilan |
| Stratégie | quotidien | analyse des KPI, prix, feuille de route |
| Concurrence | quotidien | veille web, mise à jour des profils concurrents |
| Générateur de code | à la demande | fonctionnalités, correctifs, requêtes de fusion |

## Analyse des défaillances

À la mi-2026, la fiche Trustpilot de Polsia est notée 1,8 sur 5 pour 35 avis, dont 80 % à une étoile. Les plaintes récurrentes portent sur des tâches marquées "terminées" qui ne sont pas déployées, des crédits consommés sur des actions en échec avec remboursement limité, des courriels de prospection envoyés avec un mauvais nom ou un mauvais prix, des délais de support de plusieurs semaines et des comptes maintenus en pause après paiement.

Une revue indépendante (preuve.ai) rapporte un taux de succès d'exécution de 21,3 % sur les tâches complexes, avec un exemple de 41 tâches déclarées terminées sur 47 initiées dont 24 comportaient des erreurs de destinataires ou des incohérences tarifaires. La délégation sans contrôle d'actions sensibles (affectation de noms de domaine sur des serveurs tiers, envoi non régulé de messages) produit des blocages techniques et un risque réputationnel pour l'exploitant.

## Ce que corparius en tire

Le cas Polsia motive trois choix de conception, plus un quatrième de gouvernance. Les garde-fous priment sur l'autonomie brute: budget de jetons, détection de boucles et coupe-circuit de vélocité. La validation humaine est obligatoire sur l'argent et la mise en production. Le flux de contrôle est déterministe, le modèle ne décide pas du routage. Enfin chaque action est journalisée avec l'agent qui l'a déclenchée, pour l'audit.

## Sources

- https://polsia.com/
- https://www.trustpilot.com/review/polsia.com
- https://preuve.ai/blog/polsia-review
