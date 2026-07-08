# Intégrations réelles

Chaque outil métier porte un effet mock et un backend réel. Le mock sert par défaut. Dès qu'une intégration est configurée par ses variables d'environnement, l'outil appelle le backend réel, et retombe sur le mock seulement en l'absence de configuration ou en cas d'erreur. Le système reste donc utilisable hors ligne.

## Modèle de langage

Le passage en réel se fait avec CORP_LLM_MOCK=false. Les tiers très simple, normal et lourd pointent alors vers Ollama en local ou vers un modèle cloud selon le préfixe local: ou cloud: décrit dans architecture.md. Aucune autre modification n'est requise.

## Finance (Stripe)

En présence de STRIPE_API_KEY, l'outil reconcile_stripe lit le solde disponible via l'API Stripe et renvoie un résultat marqué "(live)". Utiliser une clé restreinte en lecture seule. Sans clé, l'outil conserve sa valeur mock.

## Prospection (SMTP)

En présence de CORP_SMTP_HOST et CORP_OUTREACH_TEST_TO, l'outil send_outreach envoie l'accroche rédigée par courriel via SMTP vers une adresse de test ou de notification, sans dépendre d'un SaaS. L'authentification par CORP_SMTP_USER et CORP_SMTP_PASSWORD est optionnelle selon le relais. Ce mode prouve le câblage d'envoi. L'envoi vers de vraies cibles suppose un outil find_targets raccordé à une source réelle.

## Ajouter une intégration

Le motif tient en une fonction dans app/integrations.py qui renvoie une chaîne de résultat si la configuration existe, sinon None. L'effet de l'outil s'écrit alors "résultat réel sinon repli mock". Ce motif s'applique tel quel à Lemlist, HubSpot, Pipedrive, Meta Ads ou à la création d'une Pull Request GitHub. Les actions sensibles restent soumises à la validation humaine, quel que soit le backend.

## Sources

- https://docs.stripe.com/api/balance
- https://docs.python.org/3/library/smtplib.html
