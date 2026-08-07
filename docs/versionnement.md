# Versionnement des companies

Une company, un dépôt privé. Le dossier `companies/<slug>/` contient les seules choses
qui appartiennent vraiment à l'opérateur : la configuration, les skills, les notes de
travail, souvent les noms et les adresses des personnes que la société démarche. Le
perdre, c'est perdre la société.

Ce module (`corparius/providers/companyrepo.py`) fait de chaque dossier de company un dépôt git
indépendant, avec un distant privé chez le fournisseur de l'opérateur.

## Pourquoi séparément du dépôt du framework

Le dépôt de corparius est public. Un dossier de company ne doit jamais y arriver, et
`.gitignore` porte `companies/*` puis `!companies/example/` pour que ce soit vrai même
par accident. Git ne descend jamais dans un dossier ignoré : un dépôt imbriqué dans
`companies/` est donc totalement invisible du parent. Pas de sous-module, pas de
`.gitmodules`, aucune URL de dépôt privé qui fuite dans un fichier public.

C'est la raison pour laquelle les sous-modules ont été écartés : le pointeur et l'URL
auraient atterri dans un fichier suivi du dépôt public.

## Utilisation

```
python -m corparius.cli repo --company vigil --status   # ne change rien
python -m corparius.cli repo --company vigil            # crée le distant privé et pousse
python -m corparius.cli repo --company vigil --sync     # commite et pousse maintenant
```

Le provisionnement est idempotent. Relancé, il retrouve le dépôt existant plutôt que
d'en créer un second ou de basculer sur un autre hébergeur.

## Les fournisseurs

Même forme que `deploy.py` : une classe abstraite, un registre, un ordre que
l'opérateur réordonne, et un fournisseur local qui marche toujours sans rien
d'extérieur.

| Nom | Actif quand | Résultat |
|---|---|---|
| `github` | `CORP_GITHUB_TOKEN` ou `GITHUB_TOKEN` posé, ou le CLI `gh` présent | dépôt privé sur le compte de l'opérateur |
| `gitlab` | `GITLAB_TOKEN` posé | projet privé, `CORP_GITLAB_URL` pour une instance à soi |
| `ssh` | `CORP_REPO_SSH_TARGET` posé et `ssh` disponible | dépôt bare sur une machine à soi |
| `local` | toujours | dépôt bare sous `repos/` du home inscriptible |

`CORP_REPO_PROVIDERS` vaut `github,gitlab,ssh,local` par défaut. **L'ordre diffère de
celui de `deploy.py` exprès.** Le déploiement essaie `local` en premier parce que
publier dans une racine web locale est le défaut prudent. Ici, un opérateur qui demande
un dépôt de company veut presque toujours un dépôt hébergé, et le bare local est le
repli qui garde la fonction utilisable hors ligne. `local` en premier ferait que rien
d'hébergé ne serait jamais atteint.

Le repli local vit sur le même disque que la company. C'est un repli, pas une
sauvegarde. Pour une vraie sauvegarde, voir `cli backup`.

## Toujours privé

`GitHubProvider` envoie `private: true` à la création **et** vérifie la réponse : un
dépôt qui revient public fait échouer le fournisseur au lieu d'être utilisé. Une
politique d'organisation ou un changement d'API ne doit pas suffire à publier la
correspondance d'une société.

Le distant est l'URL https. Le push passe donc par le gestionnaire d'identifiants que
git a déjà, et aucun jeton n'est écrit dans une URL de remote, où `git remote -v`
l'afficherait.

## Le commit automatique

`CORP_REPO_AUTOCOMMIT=true` fait commiter et pousser le dossier de la company **à la fin
d'un run**, s'il a changé. Une fois par run, pas une fois par tick : un agent modifie
`company.yaml` ou `skills/` rarement, et un commit par tick enterrerait les vraies
modifications sous des dizaines de commits vides.

La fonction ne lève jamais. Un distant injoignable ne doit pas coûter un run qui a déjà
eu lieu, et le commit reste local de toute façon : rien n'est perdu.

Le réglage est à `false` par défaut. Pousser l'activité d'un opérateur vers un serveur
n'est pas quelque chose qu'un framework se met à faire de lui-même.

## Ce qui n'est jamais commité

Le `.gitignore` posé à l'initialisation exclut `data/` et `state.json` : de l'état
d'exécution, régénéré par corparius, binaire, et qui changerait à chaque tick.

Ne mettez pas non plus le store du framework dans un dépôt de company.
`data/corparius.sqlite` contient les clés API en clair tant que `CORP_SECRET_KEY` n'est
pas posée, et `cli backup` les embarque dans son zip.

## Où vit le dossier

`companies/` est sous `paths.user_home()`, donc sous `CORP_HOME` quand cette variable
est posée. Poser `CORP_HOME` hors du checkout sort `companies/`, `data/`, `backups/` et
`.env` du dépôt public d'un coup, et le code redevient du code.
