# 0009 — SHA-256 pour un jeton d'appareil, scrypt pour une passphrase

## Contexte

Schéma 20 ajoute une table `clients` : un identifiant nommé par appareil, avec une portée et une
révocation, au lieu d'un `CORP_UI_TOKEN` partagé sans nom qu'on ne peut pas retirer à un téléphone
sans le changer pour le portable.

Le plan disait de stocker le jeton en `hashlib.scrypt`, « la primitive que `secretbox` utilise
déjà ». La cohérence est un bon argument par défaut, et ici elle répond à la mauvaise question.

## Ce qui a été mesuré

Sur la machine de développement, avant de choisir :

```text
scrypt n=2**14 r=8 p=1    87,1 ms    ~16 MiB par appel
scrypt n=2**12            21,3 ms
sha256                     0,0014 ms
```

Soit un facteur **62 000**. Et cette vérification tourne à **chaque requête authentifiée** d'une
API sondée.

L'entrée est `secrets.token_urlsafe(32)` : **256 bits**, générés par `kernel/tokens.py` et
**jamais acceptés d'un appelant**. C'est cette dernière clause qui rend le raisonnement solide :
il n'y a pas de mot de passe choisi par un humain quelque part dans le chemin.

## Décision

`SHA-256` sur un sel par client, comparé par `hmac.compare_digest`.

Une KDF mémoire-dure existe pour rendre chères les **devinettes à faible entropie**. Il n'y a rien
à deviner ici : face à un attaquant qui tient le fichier du store, SHA-256 de 256 bits aléatoires
et scrypt de 256 bits aléatoires sont tous deux une recherche en 2^256. scrypt n'achète rien.

Ce qu'il coûterait est réel : un appelant **non authentifié** envoyant un identifiant bidon
forcerait 87 ms et 16 MiB d'allocation par tentative. C'est un levier de déni de service offert,
dans un serveur dont tout le modèle de menace est qu'il est joignable.

`secretbox` garde scrypt et doit le garder : là l'entrée est la passphrase d'un exploitant, qui est
exactement le cas à faible entropie pour lequel une KDF existe. Même primitive, question
différente.

Le sel est par client et stocké à côté du haché. Il ne défend pas l'entropie — il n'y a rien à
précalculer contre 256 bits aléatoires — il est là pour que deux appareils qui partageraient un
secret ne partagent pas une ligne, et pour que la colonne ne serve pas d'oracle d'égalité entre
installations.

L'identifiant voyage en clair dans l'identifiant présenté (`corp_<id>.<secret>`) pour qu'une
vérification coûte **un** index et **un** hachage, au lieu d'un hachage par appareil appairé.
Le préfixe est là pour qu'une chaîne fuitée soit identifiable — par un scanner de secrets, ou par
un exploitant qui la trouve dans un fichier de configuration qu'il est sur le point de committer.

## Ce que ça coûte

Le raisonnement dépend entièrement de `SECRET_BYTES = 32` et du fait que le secret n'est jamais
fourni par l'appelant. Les deux sont dans `kernel/tokens.py`, la constante est nommée plutôt
qu'écrite dans l'appel, et le docstring dit que la baisser invaliderait ce choix. Si un jour
`pair_client` acceptait un jeton donné par l'exploitant, il faudrait scrypt — et il faudrait
revenir ici.

Aucune limitation de débit sur les tentatives. Elle n'achèterait rien contre 256 bits, et elle
serait elle-même un état par adresse à tenir ; ce qui la rendrait nécessaire, c'est un secret
devinable, ce que la décision ci-dessus exclut par construction.

`tests/test_device_auth.py` tient les propriétés : le secret n'est ni stocké ni listé, un appareil
révoqué est refusé à sa requête suivante, un identifiant malformé est un échec d'authentification
et pas une exception. Les trois ont été prouvées non vides en réintroduisant le défaut.
