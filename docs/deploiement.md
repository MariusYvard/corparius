# Déploiement

Le site généré se publie via des fournisseurs interchangeables, essayés dans un ordre configurable, avec repli automatique. Le principe est de ne jamais dépendre d'un outil unique. Le fournisseur local est toujours disponible et ne requiert rien d'externe.

## Fournisseurs

Quatre cibles sont fournies. Le fournisseur local copie le site vers une racine web auto-hébergée (nginx, Caddy) ou un dossier de données. Netlify passe par son CLI et un jeton. Le fournisseur S3 vise tout point de terminaison compatible S3 (AWS, MinIO auto-hébergé, Cloudflare R2) grâce à CORP_S3_ENDPOINT. Le fournisseur SSH synchronise par rsync vers un serveur, VPS ou machine du homelab.

## Ordre et repli

CORP_DEPLOY_PROVIDERS fixe l'ordre, par défaut "local,netlify,s3,ssh". Un fournisseur non configuré est ignoré, le suivant est tenté. Pour publier d'abord sur un hôte externe tout en gardant une copie locale de secours, placez cet hôte avant local, par exemple "netlify,local". Le local restant en fin de chaîne, une panne de l'hôte externe n'empêche pas la publication.

## Validation humaine

La publication est une action sensible. L'outil deploy_site est soumis à la validation humaine, au même titre que l'envoi d'argent ou la mise en production de code. En ligne de commande, `python -m corparius.cli deploy --company example` publie directement, l'opérateur étant l'humain qui lance la commande.

## Variables

Les clés figurent dans .env.example: CORP_DEPLOY_PROVIDERS, CORP_DEPLOY_LOCAL_DIR, NETLIFY_AUTH_TOKEN, NETLIFY_SITE_ID, le groupe CORP_S3_*, et CORP_DEPLOY_SSH_TARGET.


## Clé en main et durabilité

Deux chemins de démarrage. `python start.py` prépare l'environnement virtuel, les dépendances, le fichier .env, la company d'exemple, puis sert la console et ouvre le navigateur. `docker compose up -d` sert la console sur 127.0.0.1:8600 à côté d'un Ollama local ; le profil `loop` ajoute la boucle de company en arrière-plan (`docker compose --profile loop up -d`) et le profil `extras` ajoute Postgres (pgvector) et n8n. Les ports sont liés à 127.0.0.1 : placez un reverse proxy devant pour exposer la console, avec CORP_UI_TOKEN.

Sans dépôt cloné, l'image publiée démarre en une commande, en mode mock hors-ligne, liée à localhost : `docker run -d -p 127.0.0.1:8600:8600 -v corparius_data:/app/data ghcr.io/mariusyvard/corparius`. Les tags suivent la version (`:vX.Y.Z` et `:latest`) ; l'image est multi-arch (amd64 et arm64) et accompagnée d'une attestation de provenance SLSA. Mise à jour : `docker pull ghcr.io/mariusyvard/corparius` puis recréez le conteneur ; le volume `corparius_data` conserve le store et les réglages.

`python -m corparius.cli doctor` vérifie l'installation (Python, store, Ollama et ses modèles, clés, réseau) et dit quoi corriger ; le même diagnostic est disponible dans l'onglet Réglages de la console. `python -m corparius.cli backup` archive le store SQLite et les configurations de companies dans backups/ (horodaté) ; planifiez-le en cron ou tâche planifiée.

Mise à jour : `git pull`, puis `pip install -r requirements.txt` dans le venv (ou `docker compose build --pull` en Docker), puis redémarrez la console. Le schéma SQLite se crée à la demande ; sauvegardez avant toute montée de version.

Service systemd (hors Docker) :

```ini
[Unit]
Description=corparius operator console
After=network-online.target

[Service]
WorkingDirectory=/opt/corparius
ExecStart=/opt/corparius/.venv/bin/python -m corparius.cli ui
Restart=on-failure
User=corparius

[Install]
WantedBy=multi-user.target
```


## Premier jour en mode réel

Le chemin le plus court vers un run réel est 100 % local : `CORP_LLM_MOCK=false` et `CORP_CLOUD_ENABLED=false` dans .env, un modèle présent dans Ollama (le doctor liste ceux qui manquent) et `CORP_LOCAL_MODEL` pointé dessus si vous ne voulez pas télécharger le modèle de repli par défaut. Le premier appel après démarrage charge le modèle en mémoire et peut être lent : le routeur réessaie une fois automatiquement. Si le backend reste injoignable, le run s'arrête proprement et laisse une action système `llm_unreachable` visible dans la console, avec le renvoi vers le doctor.

Les générations locales sur CPU prennent de quelques secondes à plusieurs dizaines de secondes chacune : un tick complet peut durer plusieurs minutes. Lancez depuis la console (le run tourne en arrière-plan) ou en CLI dans un terminal dédié. Pour passer sur un provider gratuit distant ensuite : collez une clé dans l'onglet Providers, activez le cloud, pointez un tier dessus (`CORP_NORMAL_MODEL=groq:llama-3.3-70b-versatile`).
