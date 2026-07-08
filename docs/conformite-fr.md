# Conformité (France et Union européenne)

Héberger les opérations en local ne dispense pas l'entreprise de ses obligations. Ce document couvre les points qui engagent l'exploitant. Il donne une information générale, pas un conseil juridique ou fiscal.

## Facturation électronique et PDP

Les factures émises par l'API de Stripe ne répondent pas aux exigences fiscales françaises de facturation électronique. Le calendrier de la réforme prévoit une généralisation aux transactions B2B nationales, avec passage obligatoire par une Plateforme de Dématérialisation Partenaire (PDP) agréée ou par le portail public, l'obligation atteignant toutes les entreprises à l'horizon 2027. Le calendrier a été révisé plusieurs fois, il faut vérifier les dates en vigueur. Les limites de Stripe Invoicing sont l'absence de format mixte Factur-X (un PDF visuel associé à un schéma de données XML) et l'absence de transmission automatique des flux à l'administration (e-reporting).

Deux modèles d'intégration connectent Stripe à une PDP agréée. Le modèle Indy écoute chaque paiement validé, génère la facture au format Factur-X avec les mentions légales du profil fiscal (dont l'exonération de TVA du micro-entrepreneur), envoie au client et transmet à l'administration. Le modèle Tiime, adapté aux prestations individualisées, génère la facture Factur-X et y adosse un lien de paiement Stripe, l'écriture comptable étant lettrée au règlement. Utiliser Indy et Tiime sur le même compte de production est déconseillé, sous peine de doublons de facturation.

## Archivage

Les pièces comptables et les factures se conservent de façon sécurisée et inaltérable pendant au moins 10 ans à compter de la clôture de l'exercice. L'automatisation doit répliquer les factures vers un stockage immuable, par exemple un compartiment S3 avec verrouillage d'objet ou un espace organisé par période.

## Forme juridique

Le choix de la structure détermine la fiscalité et les obligations administratives.

| Forme | Fiscalité et régime social | Coûts et contraintes |
| --- | --- | --- |
| Micro-entreprise | imposition à l'IR, cotisations au prorata du chiffre d'affaires, franchise de TVA possible | formalités minimales, comptabilité simplifiée, seuils de chiffre d'affaires (dans les barèmes récents, 77 700 € pour les services et 188 700 € pour le commerce) |
| SASU | IS par défaut avec option pour l'IR, président assimilé salarié au régime général | constitution d'environ 200 € via plateforme, annonce légale 138 €, immatriculation 37,45 €, déclaration des bénéficiaires effectifs 21,41 € |
| EURL | IR par défaut avec option pour l'IS, gérant au régime des indépendants | statuts plus rigides (1 500 € à 2 000 € via cabinet), publication environ 121 €, commissaire aux apports si apport en nature supérieur à 30 000 € |

## Règlement européen et responsabilité

L'exploitation relève de l'AI Act européen. Si l'agent évalue la solvabilité ou qualifie des candidats au recrutement, l'activité est classée système d'IA à haut risque, ce qui impose une documentation technique des jeux de données, la traçabilité des décisions et une supervision humaine de haut niveau. Sur le plan civil, l'agent n'a pas de personnalité juridique, il engage donc pleinement la responsabilité de son exploitant pour tout préjudice causé à des tiers. Une gouvernance de l'identité des agents (Non-Human Identity) devient un prérequis d'audit, pour établir quel agent a déclenché quelle action sur les infrastructures.

## Sources

- https://comparepdp.com/articles/stripe-facturation-electronique
- https://stripe.com/fr/resources/more/sasu-france
- https://stripe.com/fr/resources/more/eurl-france
- https://artificialintelligenceact.eu/
- https://www.okta.com/fr-fr/identity-101/what-is-ai-agent-identity/
