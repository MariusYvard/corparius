# Déploiement

Le site généré se publie via des fournisseurs interchangeables, essayés dans un ordre configurable, avec repli automatique. Le principe est de ne jamais dépendre d'un outil unique. Le fournisseur local est toujours disponible et ne requiert rien d'externe.

## Fournisseurs

Quatre cibles sont fournies. Le fournisseur local copie le site vers une racine web auto-hébergée (nginx, Caddy) ou un dossier de données. Netlify passe par son CLI et un jeton. Le fournisseur S3 vise tout point de terminaison compatible S3 (AWS, MinIO auto-hébergé, Cloudflare R2) grâce à CORP_S3_ENDPOINT. Le fournisseur SSH synchronise par rsync vers un serveur, VPS ou machine du homelab.

## Ordre et repli

CORP_DEPLOY_PROVIDERS fixe l'ordre, par défaut "local,netlify,s3,ssh". Un fournisseur non configuré est ignoré, le suivant est tenté. Pour publier d'abord sur un hôte externe tout en gardant une copie locale de secours, placez cet hôte avant local, par exemple "netlify,local". Le local restant en fin de chaîne, une panne de l'hôte externe n'empêche pas la publication.

## Validation humaine

La publication est une action sensible. L'outil deploy_site est soumis à la validation humaine, au même titre que l'envoi d'argent ou la mise en production de code. En ligne de commande, `python -m app.cli deploy --company example` publie directement, l'opérateur étant l'humain qui lance la commande.

## Variables

Les clés figurent dans .env.example: CORP_DEPLOY_PROVIDERS, CORP_DEPLOY_LOCAL_DIR, NETLIFY_AUTH_TOKEN, NETLIFY_SITE_ID, le groupe CORP_S3_*, et CORP_DEPLOY_SSH_TARGET.


## Clé en main et durabilité

Deux chemins de démarrage. `python start.py` prépare l'environnement virtuel, les dépendances, le fichier .env, la company d'exemple, puis sert la console et ouvre le navigateur. `docker compose up -d` sert la console sur 127.0.0.1:8600 à côté d'un Ollama local ; le profil `loop` ajoute la boucle de company en arrière-plan (`docker compose --profile loop up -d`) et le profil `extras` ajoute Postgres (pgvector) et n8n. Les ports sont liés à 127.0.0.1 : placez un reverse proxy devant pour exposer la console, avec CORP_UI_TOKEN.

`python -m app.cli doctor` vérifie l'installation (Python, store, Ollama et ses modèles, clés, réseau) et dit quoi corriger ; le même diagnostic est disponible dans l'onglet Réglages de la console. `python -m app.cli backup` archive le store SQLite et les configurations de companies dans backups/ (horodaté) ; planifiez-le en cron ou tâche planifiée.

Mise à jour : `git pull`, puis `pip install -r requirements.txt` dans le venv (ou `docker compose build --pull` en Docker), puis redémarrez la console. Le schéma SQLite se crée à la demande ; sauvegardez avant toute montée de version.

Service systemd (hors Docker) :

```ini
[Unit]
Description=corparius operator console
After=network-online.target

[Service]
WorkingDirectory=/opt/corparius
ExecStart=/opt/corparius/.venv/bin/python -m app.cli ui
Restart=on-failure
User=corparius

[Install]
WantedBy=multi-user.target
```
