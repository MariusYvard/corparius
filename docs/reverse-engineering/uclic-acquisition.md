# Uclic: acquisition B2B autonome

Uclic est une agence de growth marketing et d'IA. Deux dispositifs documentés servent de référence à l'agent de prospection de corparius: la captation de signaux d'intention (Avanoo) et l'inversion de persona (CodinGame).

## Avanoo: 22 signaux d'intention

Avanoo opère sur le marché de la gouvernance des dépenses logicielles (SAM, FinOps, shadow IT). Le besoin client y est intermittent, il devient fort lors d'événements précis (recrutement d'un DSI, fusion-acquisition, incident de sécurité, démarche de certification) puis retombe en quelques semaines. Le dispositif capte 22 signaux d'intention répartis en 5 clusters, les score en trois tiers de priorité (T1 chaud, T2 qualifié, T3 maturation), enrichit les décideurs via Clay et Apollo puis active des séquences Lemlist synchronisées avec un CRM Pipedrive ou HubSpot. La mission a duré 6 mois.

| Cluster | Exemples de signaux | Activation |
| --- | --- | --- |
| RH stratégiques | recrutement d'un DSI, d'un CISO, d'un DPO, d'un administrateur Salesforce | séquence citant l'arrivée du cadre et l'audit des outils |
| Organisationnels | fusion-acquisition, levée de fonds, ouverture de bureaux | message sur la rationalisation des licences pré-scale |
| Conformité et sécurité | certification SOC2 ou ISO 27001, migration SSO, incident publié | argumentaire conformité continue et risque tiers |
| Comportementaux | engagement LinkedIn, participation à un salon (FIC, RSA) | invitation à un échange, envoi d'un livre blanc |
| Achat actif | appel d'offres SAM ou ITSM publié, changement de stack | prise de contact citant l'appel d'offres |

Le score compose la nature du signal (un appel d'offres pèse plus qu'un engagement LinkedIn), sa fraîcheur (moins de 30 jours est fort, plus de 90 jours est faible) et la combinaison des signaux (un appel d'offres avec l'arrivée d'un CISO donne un T1). Le raisonnement de conversion est direct: un changement de direction technique ouvre une fenêtre d'audit d'environ 90 jours, l'hyper-croissance produit du shadow IT et des doublons de licences.

## CodinGame: inversion de persona

CodinGame est une plateforme de recrutement technique de plus de 2 millions de développeurs. La cible naturelle (RH et Talent Acquisition) est saturée de sollicitations, ce qui dégrade les taux de réponse. Le dispositif inverse l'angle. Des scrapers Python lisent Indeed en temps réel pour repérer les entreprises qui publient des offres de développeurs, preuve d'un besoin actif. L'orchestration sous n8n enrichit les profils techniques (CTO, VP Engineering, Head of Engineering, Tech Lead) et déclenche les séquences. La prospection vise ces profils, plus réceptifs à un outil conçu par des pairs, la recommandation interne remontant ensuite vers la décision. La mission a duré 8 mois.

## Ce que corparius reprend

L'agent de prospection sépare trois étapes: captation du signal, score de priorité et rédaction contextualisée. Dans le MVP elles sont simulées par des outils mock (find_targets, send_outreach). Le remplacement par des intégrations réelles (scrapers, Clay, Lemlist, CRM) se fait sans toucher à la boucle d'orchestration ni aux garde-fous.

## Sources

- https://uclic.fr/cas-clients/avanoo-22-signaux-intention-sam-finops
- https://uclic.fr/cas-clients/industrialiser-acquisition-b2b
- https://uclic.fr/expertise/agents-ia-custom
