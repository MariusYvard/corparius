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
