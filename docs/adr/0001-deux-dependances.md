# 0001 — Deux dépendances d'exécution, et pas une de plus

## Contexte

Corparius est auto-hébergé : il tourne sur la machine de l'exploitant, qui l'installe
lui-même et doit pouvoir l'auditer. Chaque dépendance d'exécution est une chose de plus à
faire confiance, à mettre à jour, et qui peut refuser de s'installer.

## Décision

`requests` et PyYAML. Tout le reste est la bibliothèque standard.

Deux extras optionnels existent — `cryptography` pour le chiffrement au repos, `mcp` pour le
serveur MCP — et le produit fonctionne entièrement sans eux, en le disant quand ils manquent.

## Ce que ça permet, concrètement

Le serveur de la console est `http.server` de la stdlib, et il fait déjà l'authentification
par jeton, le contrôle de l'en-tête `Host` contre le rebinding DNS, la protection
cross-site, et un plafond de corps par route. La persistance est `sqlite3` avec des
migrations `PRAGMA user_version`. Le chiffrement des jetons d'appareil utilisera
`hashlib.scrypt` et `hmac.compare_digest`, déjà dans la stdlib.

Ce que ça exclut, et il faut le dire : FastAPI, Pydantic, SQLAlchemy, Alembic. Chacun
résoudrait un problème que le produit n'a pas.

## Coût

Plus de code écrit à la main, donc plus de code à tester — ce que la suite fait. Et une
tentation permanente à chaque nouvelle fonctionnalité, ce pour quoi cette décision est
écrite ici.

## Où c'est appliqué

`pyproject.toml:24-33`, et le commentaire à la ligne 24 dit la règle.
