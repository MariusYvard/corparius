# Conformité (France et Union européenne)

Héberger les opérations en local ne dispense pas l'entreprise de ses obligations. Ce document couvre les points qui engagent l'exploitant. Il donne une information générale, pas un conseil juridique ou fiscal.

## Facturation électronique et PDP

Les factures émises par l'API de Stripe ne répondent pas aux exigences fiscales françaises de facturation électronique. Le calendrier de la réforme prévoit une généralisation aux transactions B2B nationales, avec passage obligatoire par une Plateforme de Dématérialisation Partenaire (PDP) agréée ou par le portail public, l'obligation atteignant toutes les entreprises à l'horizon 2027. Le calendrier a été révisé plusieurs fois, il faut vérifier les dates en vigueur. Les limites de Stripe Invoicing sont l'absence de format mixte Factur-X (un PDF visuel associé à un schéma de données XML) et l'absence de transmission automatique des flux à l'administration (e-reporting).

Deux modèles d'intégration connectent Stripe à une PDP agréée. Le modèle Indy écoute chaque paiement validé, génère la facture au format Factur-X avec les mentions légales du profil fiscal (dont l'exonération de TVA du micro-entrepreneur), envoie au client et transmet à l'administration. Le modèle Tiime, adapté aux prestations individualisées, génère la facture Factur-X et y adosse un lien de paiement Stripe, l'écriture comptable étant lettrée au règlement. Utiliser Indy et Tiime sur le même compte de production est déconseillé, sous peine de doublons de facturation.

### Le compte bancaire n'est pas une plateforme agréée

Corparius sait encaisser de deux façons : un lien de paiement Stripe, qu'un inconnu clique, et un compte professionnel Qonto, vers lequel un client vire contre facture. C'est le second cas qui correspond à la plus grande partie de la vente entre entreprises, et c'est aussi celui où la question de la facturation électronique se pose.

Corparius n'affirme pas qu'une banque donnée est une PDP agréée, et ne le déduit pas de la présence d'identifiants dans les réglages. Le module Qonto lit l'organisation pour prouver que les identifiants fonctionnent, rien de plus : il ne crée aucune facture, ne transmet rien à l'administration et ne déplace pas d'argent. La liste des plateformes immatriculées est publiée par l'administration fiscale et c'est là qu'il faut vérifier, pas ici. Un prestataire qui annonce « conforme 2026 » sur sa page commerciale n'est pas une preuve d'immatriculation.

Ce que corparius fournit pour cette obligation, c'est la matière : le bloc `legal:` d'une entreprise porte les identifiants qu'une facture doit citer (raison sociale, forme, capital, siège, RCS ou SIREN, TVA intracommunautaire), et ils sont saisis une fois dans la console. La transmission au format Factur-X et l'e-reporting restent à faire par une plateforme agréée.

## Mentions légales du site

Un site qui présente une activité commerciale doit identifier son éditeur, et le manquement est sanctionné pénalement (article 6 III de la LCEN). Les informations attendues :

| Champ | Qui le doit | Remarque |
| --- | --- | --- |
| Raison sociale ou nom et prénom | tout éditeur | une personne physique qui exerce en son nom propre donne son nom |
| Forme juridique | les sociétés | SAS, SASU, SARL, EURL |
| Capital social | les sociétés | pas de capital pour une micro-entreprise |
| Adresse du siège | tout éditeur | une adresse postale réelle, pas une boîte électronique seule |
| Contact | tout éditeur | un moyen de joindre l'éditeur, adresse électronique ou téléphone |
| RCS ou SIREN | les immatriculés | une micro-entreprise donne son SIREN |
| TVA intracommunautaire | les assujettis | absente sous franchise |
| Directeur de la publication | tout éditeur | souvent le représentant légal |
| Hébergeur : nom, adresse, téléphone | tout éditeur | c'est celui qui héberge, pas celui qui a construit le site |

Deux choix de corparius sur ce point. Les champs se saisissent dans la console (onglet Entreprise, bloc « Mentions légales »), pas dans un fichier édité à la main. Et **la page n'affiche que ce qui a été rempli** : une rubrique qui dirait `RCS :` suivi d'un blanc est pire qu'une ligne absente, parce qu'elle affirme que l'entreprise a cherché et n'a rien trouvé. Un bloc entièrement vide ne produit aucune section, donc rien ne rassure à tort.

Si le site est hébergé ailleurs que par corparius (case « site externe »), ces obligations restent celles de l'exploitant sur son propre site, et corparius ne génère alors aucune page où les inscrire.

Deux obligations voisines que ce tableau ne couvre pas : le traitement des données personnelles relève du RGPD et se déclare dans `site.privacy`, et une vente à des particuliers ajoute les conditions générales et le droit de rétractation, qui ne sont pas des mentions d'identification.

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
- https://www.legifrance.gouv.fr/loda/id/JORFTEXT000000801164 (LCEN, article 6)
- https://entreprendre.service-public.fr/vosdroits/F31228 (mentions obligatoires d'un site)
- https://www.impots.gouv.fr/facturation-electronique (l'immatriculation des plateformes)
- https://stripe.com/fr/resources/more/sasu-france
- https://stripe.com/fr/resources/more/eurl-france
- https://artificialintelligenceact.eu/
- https://www.okta.com/fr-fr/identity-101/what-is-ai-agent-identity/
