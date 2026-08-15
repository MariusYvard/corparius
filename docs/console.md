# Console opérateur

La console web (corparius/api/) est servie sur http://127.0.0.1:8600 par la bibliothèque standard.
Elle lit le même store SQLite que le CLI et pilote le même Runtime.

## Une console, et un chemin de repli

**`/` sert la console Svelte** dès qu'elle a été construite, et c'est ce que `start-windows.bat`
donne sans qu'on tape quoi que ce soit : le lanceur la construit avant de servir quand Node est
installé. `/app/` sert le même shell et porte ses **ressources** — `base` vaut `/app/`, donc la
copie servie sur `/` nomme son script en absolu et le trouve là.

Le drapeau du plan a fini son travail. Il devait garder l'ancienne page sur `/` « jusqu'à ce que le
nouveau bundle passe le test d'égalité des jeux de clés i18n » : il passe, les sept onglets sont
refaits, donc `/` est la nouvelle console.

**Le repli n'est pas un réglage, c'est un fait sur la copie de travail.** `corparius/api/static/`
n'existe qu'après `npm run build` : sans lui, `/` sert la page d'origine — une console entière, sans
étape de build — et `/app/` répond 404 en nommant la commande. Construit veut dire nouvelle, non
construit veut dire ancienne, et aucun des deux états n'est une console cassée.

La page d'origine garde un chemin à elle, **`/legacy`**, tant qu'elle est livrée. Un chemin plutôt
qu'une variable d'environnement : un exploitant qui tombe sur un défaut de la nouvelle a besoin d'un
endroit où cliquer, pas d'une variable à poser et d'un redémarrage pour le faire. Voir
`web/README.md`.

**Node n'est jamais nécessaire à l'exécution.** La construction est une étape de développement et de
CI ; le wheel et le binaire gelé servent le résultat sans Node installé.

## Lancement

```bash
python -m corparius.cli ui                # 127.0.0.1:8600
python -m corparius.cli ui --port 9000    # port choisi
CORP_UI_HOST et CORP_UI_PORT font la même chose depuis .env
```

## Onglets

Overview donne le pouls de la company. « En attente de vous » mène la ligne et se clique : le portail humain est le sujet du produit, il n'a pas à se chercher. Suivent l'avancement des tâches, la dépense par agent, les métriques de flux lean (débit, encours, goulot, défauts, attente), le site de vente et les paiements. Operations regroupe la file d'approbations HITL (décision inline avec note), le backlog kanban (arbitrage et édition de titre ou de priorité en place), la sauvegarde et le journal des actions. Documents porte les fichiers de l'entreprise: une zone de glisser-déposer, puis la liste de ce qui est au dossier avec, par ligne, la provenance (déposé par vous ou écrit par l'entreprise), l'état vis-à-vis du budget d'invite, le texte extrait derrière un dépli et un bouton pour le retirer. Voir `docs/documents.md`. Providers expose les bascules d'exécution (mock, cloud, Claude Code), les tiers de routage, la saisie des clés par provider et le préflight qui prouve par un vrai appel ce que le compte peut réellement appeler — y compris s'il sait lire une image, testé en lui en envoyant une. CEO est une conversation avec l'agent CEO, alimentée par l'état réel de la company. Réglages contient l'éditeur de société et toute la configuration.

## Rien à éditer à la main

La console écrit tout ce que corparius lit. L'éditeur de société couvre chaque champ de `company.yaml` (offre, prix, lien de paiement, ICP, canaux, agents, budgets, outils sous approbation) ; enregistrer réécrit le fichier depuis ces champs, donc les commentaires ajoutés à la main ne survivent pas. La suppression exige de taper le slug et déplace la config dans `companies/.trash/` : rien n'est détruit. Un fichier cassé s'ouvre quand même, avec ses problèmes nommés, plutôt que de renvoyer une erreur qui laisserait l'opérateur sans moyen de le réparer.

L'onglet Réglages couvre le reste, groupe par groupe, piloté par le registre `corparius/config/settings_spec.py` : ajouter un réglage est une ligne, pas une modification du HTML. Chaque champ affiche la couche qui lui répond et se met en lecture seule quand l'environnement du processus le fixe (voir la table de précédence du README) — un réglage n'est jamais ignoré en silence.

**Sans navigateur, l'assistant aussi : `corparius new --name "Acme" --product "…"`.**
Il n'y avait aucun moyen de créer une entreprise depuis un terminal — `init` initialise l'état
d'une entreprise qui existe déjà, donc l'opérateur écrivait `companies/<slug>/company.yaml` à la
main, en devinant la forme et les champs requis, sans que `company.validate` tourne à la
création. Or c'est toute la promesse de l'assistant : deux champs suffisent, le reste vient du
*même* validateur que l'éditeur, « donc une entreprise créée ici et une entreprise modifiée
ensuite ne peuvent jamais être en désaccord sur ce qu'est une entreprise ». `--list-templates`
montre les gabarits ; un champ explicite gagne toujours sur l'exemple du gabarit.

**Sans navigateur : `corparius set CLE=valeur`.** La page et la commande passent par le même
service (`corparius/app/settings.py`), donc elles refusent les mêmes valeurs avec les mêmes
messages, et chaque clé part dans la couche qui peut la porter — le store pour un réglage
ordinaire, `.env` pour une clé d'amorçage, avec le redémarrage annoncé. C'était la première des
onze choses que la console savait faire et que la ligne de commande ne savait pas, parce que la
logique vivait dans le gestionnaire HTTP : `_persist(state, …)` prenait un objet de console, et
ce paramètre était toute la barrière.

## Compte mail

Un compte, dans les deux sens. Choisissez le fournisseur, donnez l'adresse et un mot de passe d'application : les serveurs et ports SMTP et IMAP sont déduits et repliés sous « Réglages déduits ». Le bouton « Tester ce compte » envoie un vrai message et lit vraiment la boîte, puis rapporte les deux moitiés séparément — elles échouent pour des raisons différentes. Les diagnostics nomment le remède, pas le protocole.

**Les étapes, avec leur état.** Le préréglage remplit quatre noms d'hôte, ce qui est la moitié facile. La moitié difficile se passe ailleurs : créer un mot de passe d'application derrière la validation en deux étapes, lancer Proton Bridge, valider un domaine d'envoi. Choisir un fournisseur affiche désormais ses étapes numérotées, dans l'ordre, avec le lien direct vers la bonne page.

L'état de chaque étape est **déduit des réglages**, pas coché à la main : une étape qui demande une adresse et un mot de passe passe au vert quand les deux sont enregistrés. Une étape que corparius ne peut pas vérifier — installer un logiciel, relever un mot de passe sur le tableau de bord de quelqu'un d'autre — le dit et reste grise, parce qu'une case qui ne pourra jamais devenir verte se lit comme un échec.

**Et là où ça se plaint, il y a un bouton.** `scan_replies` et `triage_inbox` renvoyaient chacun leur ligne dans le journal d'actions à chaque tour : vrai, correct, répété indéfiniment, et ne pointant vers rien. C'est maintenant une notice unique dans l'inbox — une seule, parce que son identifiant est déterministe — avec un bouton qui ouvre directement le groupe Courrier de cet onglet.

La lecture est en lecture seule : corparius ouvre la boîte en `readonly`, n'a jamais marqué un message comme lu, ne déplace rien et ne supprime rien. Elle sert à deux choses : le triage du support, et surtout savoir quels prospects ont répondu (`scan_replies`, agent outreach), ce qui ferme la boucle de la prospection.

## Icônes

Le logo corparius (organigramme pixel-art, un carré CEO au-dessus de trois agents) et les pictogrammes des rôles et des onglets sont des créations du propriétaire du projet (sources dans docs/icons/). Le logo sert de favicon et de marque du header ; le README utilise les bannières docs/banner.svg et banner-dark.svg (thème GitHub), qui embarquent le logo. Ils sont embarqués dans la page en data URI (PNG, fond rendu transparent, mise à l'échelle au plus proche voisin) sur une pastille ivoire lisible dans les deux thèmes.

## Première utilisation et diagnostics

Sans company existante, la console affiche un formulaire de création (nom et offre suffisent ; agents et budget ont des valeurs par défaut). L'option "+ Nouvelle société" du sélecteur rouvre ce formulaire ensuite. L'onglet Réglages embarque le diagnostic (équivalent de `python -m corparius.cli doctor`) : chaque vérification indique son niveau et l'action corrective.

## Site et paiements

La carte "Site de vente" de la vue d'ensemble montre un aperçu réduit du site généré (data/sites/<slug>/index.html, servi sur /site/<slug>/), avec génération et régénération en un clic ; le déploiement reste une action HITL. La carte "Paiements" lit les encaissements Stripe avec STRIPE_API_KEY (clé de lecture restreinte) et affiche des données d'exemple étiquetées sinon.

## API

### Le contrat, et ce qui n'en fait pas partie

`GET /api/v1/meta` est la **première** route versionnée, et c'est celle qu'un second client
interroge en premier — les quatre ressources étroites ci-dessous sont les autres. Elle est publique, comme `/api/session` et pour la même raison une étape
plus tôt : un client doit pouvoir apprendre à quoi il parle avant de pouvoir s'y authentifier.
Elle ne nomme aucun secret, aucune entreprise et aucune *valeur* de réglage.

```json
{"ok": true, "api_version": 1, "app_version": "0.4.0", "schema_version": 21,
 "settings_count": 80,
 "capabilities": {"models": true, "mail": false, "payments": false, "skills": true,
                  "memory": true, "secrets_at_rest": false, "plugins": false,
                  "durable_jobs": false}}
```

Trois versions qui ne sont pas interchangeables : `api_version` est le contrat (un petit
entier, qu'on compare et que personne ne parse), `app_version` est la build, `schema_version`
est le `PRAGMA user_version` **que la base porte** — une mise à jour migre sur place, donc ce
qu'un client a besoin de savoir est ce que la base *est*, pas ce que cette build attend.

`capabilities` est résolu depuis la configuration, jamais déclaré : `mail` est vrai quand un
compte est configuré, pas quand la fonctionnalité existe dans le code. C'est ce qui fait qu'un
client cache un bouton au lieu de découvrir un 404. Et jamais par une sonde réseau — cette
route est faite pour être sondée, et la règle contre l'ouverture d'une socket depuis un point
sondé a été écrite après que `/api/providers` en ouvrait une à chaque rafraîchissement. Donc
`payments` demande si une clé Stripe est posée, pas si Stripe répond ; savoir si une chose
configurée *marche* est la question de `corparius doctor`, et elle se pose quand on la pose.
`durable_jobs` répond `false` plutôt que de manquer : un client à qui on dit *non* n'a pas à
le deviner depuis une clé absente.

### Les ressources étroites

`/api/overview` fait **48 530 octets** sur la vraie entreprise et la page le sonde toutes les cinq
secondes : 34 Mo par heure et par client. Mesuré clé par clé, trois clés font 94 % — `tasks`
21 115, `memory` 17 706, `recent_actions` 6 765 — donc quatre ressources :

```text
GET /api/v1/summary?company=    2 859 o   l'horloge, le flux, ce qui attend une personne
GET /api/v1/tasks?company=     21 156 o   le kanban
GET /api/v1/memory?company=    17 754 o   46 faits, qui ne changent presque jamais
GET /api/v1/activity?company=   6 797 o   les 25 dernières actions
```

`summary` est **17,0× plus petit** que ce que la page sonde, et il garde `approvals` et `inbox` —
613 octets à deux, et les deux choses qu'un exploitant ne doit pas avoir à redemander. Le plan les
nommait comme ressources séparées ; la mesure a dit non.

**Chaque GET v1 porte un `ETag`.** Renvoyez-le en `If-None-Match` et une ressource inchangée
répond `304` sans corps : `/api/v1/memory` passe de 17 754 octets à 0. Ce que ça économise est la
bande passante, pas le travail — la charge est construite puis hachée, donc la requête a bien eu
lieu. `Cache-Control` vaut `no-cache` sur ces routes (garde et redemande) et reste `no-store`
ailleurs : `no-store` interdirait de garder la copie, et il n'y aurait rien à revalider.

### Le travail durable

Un tour est une ligne dans `jobs` (schéma 19), donc il survit au redémarrage de la console — et un
tour que la console tenait quand elle est morte se relit `interrupted` plutôt que de disparaître
sans trace.

```text
POST /api/v1/runs?      {company, ticks, loop}   démarre ; honore Idempotency-Key
POST /api/v1/runs/stop  {company}                demande l'arrêt, depuis n'importe où
GET  /api/v1/jobs?company=                       les 20 derniers, le plus récent d'abord
```

**`Idempotency-Key` est honoré, pas documenté comme une intention.** Deux requêtes portant la même
clé donnent **un** travail : la seconde répond `created: false` avec le même `job`. Un téléphone en
4G qui n'a jamais vu la première réponse ne peut donc pas lancer un second tour en redemandant.

**L'arrêt est durable.** `cancel_requested` est une colonne, donc le client qui arrête un tour n'a
pas besoin d'être le processus qui le fait tourner. La console garde en plus un `Event` en mémoire,
parce qu'un tick est assez long pour qu'un bouton ait l'air cassé.

**Un travail interrompu n'est jamais repris.** Au démarrage, un travail encore `running` qu'aucun
processus vivant ne possède passe à `interrupted`, et la vue d'ensemble le dit en mots. Reprendre en
silence revendiquerait des ticks qui n'ont pas eu lieu.

`corparius run` enregistre aussi son travail, donc `corparius status` ailleurs voit le tour de la
console et deux terminaux ne peuvent pas lancer la même entreprise en même temps.

### Les refus

Une route v1 refuse dans une enveloppe :

```json
{"ok": false, "error": {"code": "unknown_company",
                        "message": "no company here is called 'nope'",
                        "detail": {"slug": "nope"}}}
```

Sept codes, et c'est un ensemble fermé parce qu'un client fait un `switch` dessus :
`unknown_company`, `not_found`, `invalid`, `unauthenticated`, `forbidden`, `too_large`,
`internal`. Le code est pour le client, le message pour la personne, `detail` porte les
particularités au lieu qu'elles soient soudées dans la phrase. Les contrôles qui précèdent tout
gestionnaire — Host, taille, origine, jeton — parlent le même vocabulaire : un client qui pourrait
distinguer le refus d'un gestionnaire mais pas un 401 ne pourrait presque rien distinguer.

Les 54 routes non préfixées ci-dessous sont la **forme interne de la console** : elles ont
changé chaque fois que la page changeait, ce qui allait très bien tant que la page était le
seul client. C'est un ensemble *déclaré* — `tests/test_api_version.py` en épingle le compte,
donc une route ajoutée hors de `v1` est une ligne délibérée dans ce fichier. **Elles gardent la
phrase plate** (`{"ok": false, "error": "unknown company 'nope'"}`) : la page lit `data.error`
comme une chaîne à quatorze endroits, et un objet s'y afficherait « [object Object] » précisément
sur les échecs qu'on a le plus besoin de lire.

Deux noms ont leur lecture en v1 et leur écriture encore en historique, `tasks` et `memory` : on
sonde `GET /api/v1/tasks` et on poste une décision à `POST /api/tasks`. Les lectures ont bougé les
premières parce que c'est là qu'était le coût. C'est déclaré dans le test, pas subi.

GET `/api/companies`, `/api/overview?company=`, `/api/company?company=`, `/api/settings`, `/api/session`, `/api/providers`, `/api/doctor`, `/api/site?company=`, `/api/documents?company=`, `/api/document/text?company=&path=`, `/api/payments`, `/api/chat?company=`, `/site/<slug>/`.

POST `/api/companies` {name, product, agents, session_tokens}, `/api/company` {company, config}, `/api/company/delete` {company, confirm, purge_store}, `/api/settings` {values, unset}, `/api/providers` {values}, `/api/site` {company, headline}, `/api/deploy` {company}, `/api/backup`, `/api/run` {company, ticks, loop}, `/api/run/stop` {company}, `/api/approvals` {id, decision, note, remember}, `/api/rules` {company, tool}, `/api/memory` {id, action}, `/api/inbox` {id, answer}, `/api/tasks` {id, decision | title, priority, target, tool}, `/api/chat` {company, message}, `/api/documents` {company, name, data}, `/api/documents/delete` {company, path}, `/api/test/mail` {to}, `/api/test/payments`.

`/api/document/text` sert le texte **entier** d'un document, sans le plafond `documents.MAX_CHARS`. Ce plafond existe pour qu'une présentation de trente pages n'avale pas un tour d'agent ; il n'a rien à faire entre l'exploitant et un fichier qui est à lui. La carte réutilisait le texte tronqué de l'agent, donc relire son propre brief de 12 000 caractères en montrait 4 000 — honnête, la pastille le disait, et quand même la mauvaise réponse. La surface de lecture et le budget d'invite sont deux questions différentes. Le bouton n'apparaît que si quelque chose a été coupé.

Deux détails de `/api/documents`. Le plafond de corps est **par route**: celle-ci porte un fichier en base64 et vaut donc `documents.MAX_UPLOAD` plus le tiers que l'encodage coûte, là où toutes les autres gardent le 1 Mio global — élargir ce plafond pour tout le monde aurait élargi du même geste tous les autres points d'API. Et le GET n'est jamais sur le sondage de 5 secondes, parce qu'il ouvre et extrait chaque fichier qu'il liste: la page le recharge à l'arrivée, au changement d'entreprise, à la fin d'un run et sur le bouton.

Toutes les réponses portent un champ `ok`, qui qualifie la requête et non son verdict : un test SMTP qui échoue renvoie `200 {ok: true, result: {ok: false, detail: ...}}`, et un déploiement qui ne publie rien renvoie `200 {ok: true, published: false}`. La distinction compte : un échec métier n'est pas une erreur d'API, et il ne doit pas non plus être maquillé en succès.

## Modèle de sécurité

Le serveur écoute sur 127.0.0.1 par défaut. Les secrets envoyés depuis la page sont en écriture seule : stockés, jamais renvoyés, l'API n'expose qu'un booléen `configured`. Seules les clés du registre sont modifiables ; toute autre variable est refusée. Si `CORP_UI_TOKEN` est défini, chaque appel mutateur doit porter l'en-tête `X-Corp-Token` — la page l'envoie et propose de le saisir sur un 401. Le doctor **échoue** si la console est exposée hors localhost sans token : elle peut dépenser de l'argent et publier.

### Un identifiant par appareil

`CORP_UI_TOKEN` reste l'identifiant d'amorçage : un secret partagé, sans nom, sans portée, et
qu'on ne peut pas retirer à un téléphone sans le changer pour le portable. `corparius pair` donne
l'autre forme.

```bash
corparius pair --name "Marius iPhone" --act   # affiché une seule fois
corparius clients                             # ce qui est appairé, et vu quand
corparius revoke --id <id>                    # refusé dès la requête suivante
```

L'appareil envoie `Authorization: Bearer <token>` ; `X-Corp-Token` reste un alias pour une version.
Le secret n'est **jamais** stocké — seul un SHA-256 sur un sel par client, et il n'y a aucun moyen
de le redemander. Pourquoi SHA-256 et pas scrypt : [ADR 0009](adr/0009-sha256-pour-un-jeton-d-appareil.md),
mesuré à 87 ms et 16 MiB par requête pour protéger 256 bits qui n'ont pas besoin d'être protégés.

**Deux portées, pas dix.** `read` regarde, `act` agit aussi. Un appareil `read` qui tente une
écriture reçoit **403 et pas 401** : son identifiant est bon et la réponse est quand même non — un
client à qui on répond 401 se ré-appairerait, ce qui ne changerait rien.

### Le palier CSRF qui s'est resserré

Le contrôle d'origine a trois paliers, et le troisième disait « ni `Sec-Fetch-Site` ni `Origin` ⇒
autorisé ». C'était un compromis local raisonnable — c'est ce qui fait marcher curl, le smoke de la
CI, la suite de tests et le serveur MCP sans configuration. Mais **une application native n'envoie
ni l'un ni l'autre non plus**, donc dès qu'un second client existe pour de vrai, ce palier cesse de
vouloir dire « pas un navigateur, donc local » et devient la porte par laquelle passe une écriture
distante.

Il exige maintenant **le loopback ou un appareil appairé**. Le loopback est vérifié sur l'adresse du
pair, que l'appelant ne peut pas fabriquer.

`CORP_UI_ALLOWED_ORIGINS` autorise une origine croisée — un serveur de développement front est une
autre origine, ce qui est tout l'arrangement de l'étape 9 — avec `do_OPTIONS` pour le préflight.
**Jamais `*`, jamais `Origin` renvoyé en écho** : refléter, c'est la même permission épelée pour
avoir l'air prudent. Comme `CORP_UI_ALLOWED_HOSTS`, c'est une clé d'amorçage et pas un réglage :
un contrôle de sécurité ne doit pas être modifiable par la surface qu'il protège.

### TLS : non, et le doctor le vérifie

`http.server` avec un certificat auto-signé est une catastrophe d'expérience sur iOS et apprendrait
aux exploitants à cliquer à travers les avertissements de certificat. La réponse honnête est de
rester en loopback et d'atteindre la console par un tunnel — WireGuard, Tailscale, SSH, ou un proxy
inverse qui termine TLS.

Ce qui n'est honnête que si quelque chose vérifie. Le doctor **échoue** quand un appareil est
appairé et que la console écoute hors loopback sans TLS : un jeton d'appareil est un identifiant
porteur, donc il est dans chaque requête sur le fil, et un avertissement sur un identifiant qui
fuit est un avertissement qu'on n'écoute pas deux fois. `CORP_UI_BEHIND_TLS=true` est l'exploitant
qui affirme qu'un proxy termine devant — une affirmation, pas une détection, et c'est dit tel quel :
vu de l'intérieur du processus, une requête venue d'un proxy local et une requête venue d'un
portable au fond d'un café sont identiques.

Les secrets sont stockés en clair dans `data/corparius.sqlite` par défaut (comme ils l'étaient dans `.env`) ; le panneau et le doctor le disent. `corparius secrets on` les chiffre au repos, y compris ceux déjà enregistrés, avec la phrase de passe `CORP_SECRET_KEY` — une clé d'amorçage, donc elle vit dans `.env` ou l'environnement du processus, jamais dans la base qu'elle protège. Dans les deux cas aucune archive de `backup` ne sort un secret en clair : chiffré il voyage comme cryptogramme, non chiffré il est blanchi et `REDACTED.txt` nomme ce qu'il faudra ressaisir. Sur POSIX la base est passée en 0600 ; sur Windows c'est sans effet.

Un run lancé depuis la page tourne dans un thread du même processus et passe par le firewall habituel (budget, loop guard, circuit breaker, gate HITL). Une boucle lancée depuis la console vit dans le processus console : la fermer l'arrête, contrairement au profil docker `loop`. Le bouton Stop pose un drapeau que le runtime consulte à chaque tick — le thread n'est jamais tué, et seules les heures réellement jouées sont comptées.
