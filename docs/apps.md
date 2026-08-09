# Applications de l'entreprise

corparius branche jusqu'à quatorze fournisseurs LLM, une chaîne de repli et trois paliers, et jusqu'ici dix agents seulement pouvaient s'en servir. Une entreprise a d'autres besoins — une FAQ sur son site, un formulaire qui comprend ce qu'écrit un visiteur, un petit outil interne — et la seule façon de les servir était de recopier une clé API ailleurs. **Recopiée dans une page web, elle est lisible par quiconque ouvre l'inspecteur.**

Une **app** est un fichier YAML à côté des skills de l'entreprise. Elle passe par le même routeur que les agents, donc elle hérite des paliers, de la chaîne de repli et de la comptabilité des coûts sans rien de nouveau.

```
companies/<slug>/apps/<nom>.yaml
```

## Écrire une app

```yaml
name: faq
description: Répond à une question sur l'offre, ou dit qu'il ne sait pas.
tier: trivial              # trivial | normal | hard

system: |
  Tu réponds aux questions des visiteurs sur l'offre, dans leur langue, en
  quatre phrases au plus. N'invente jamais un prix, une date ni une garantie.

max_tokens: 300            # par appel
daily_tokens: 20000        # plafond dur par jour
rate_per_minute: 6         # par IP appelante
origins: ["https://votre-site.example"]
```

`system` n'a pas de valeur par défaut : c'est toute la définition, et lui en donner une reviendrait à inventer la voix d'une entreprise. Une app sans `system` est ignorée avec un avertissement.

**Les plafonds ne sont pas décoratifs.** Un point d'accès qui appelle un modèle pour qui le demande est un moyen de dépenser l'abonnement de quelqu'un d'autre. Une valeur absurde (`0`, `-5`, `"beaucoup"`) retombe sur le défaut plutôt que de se lire comme « pas de limite » — c'est la direction qui coûte de l'argent.

`tier` est une décision de coût : `trivial` pour une réponse courte sur une question étroite, `hard` seulement si la différence vaut une fenêtre d'abonnement.

## L'essayer hors ligne

```bash
corparius apps list --company example
corparius apps show faq --company example
corparius apps run faq --company example --input "C'est combien ?"
```

`run` fonctionne en **mode mock**, donc une app s'écrit et se mesure sans clé, sans réseau et sans rien exposer. La sortie annonce ce qu'elle a dépensé et où en est le plafond du jour.

## Le point d'accès

```bash
corparius apps key faq --company example     # une clé, à mettre dans .env
# puis, dans .env : CORP_APPS_ENABLED=true
corparius apps serve                          # 127.0.0.1:8610 par défaut
```

```bash
curl -X POST http://127.0.0.1:8610/v1/apps/example/faq \
  -H "X-Corp-App-Key: ..." -d '{"input":"C est combien ?"}'
# {"ok": true, "text": "..."}
```

La réponse porte `ok` et `text`, et rien d'autre. Quel fournisseur a servi, quel modèle et à quel coût sont l'affaire de l'exploitant et restent dans la console, où la dépense apparaît sous `app:<nom>` dans la ventilation par agent.

### Un serveur séparé, et pourquoi

Ce n'est **pas** la console. La console est le plan de contrôle de l'exploitant — réglages, clés, approbations, toute l'entreprise — et elle écoute sur `127.0.0.1` derrière un jeton. Le point d'accès existe pour être appelé par autre chose. Les mettre dans un seul processus reviendrait à faire d'un contrôle qui cède l'exposition des deux. Un test demande `/api/settings` au port des apps et exige un 404.

### La clé n'est pas un secret

Une clé qu'une page web envoie est lisible par quiconque ouvre l'inspecteur. Elle sert à **identifier** une app pour lui attribuer une dépense et pouvoir la révoquer — pas à l'autoriser. Une variable par app, donc une clé abusée se révoque sans toucher aux autres.

Ce qui protège réellement, ce sont les quatre gardes, dans cet ordre :

1. **Débit**, par (app, appelant), en mémoire. En premier parce que c'est le seul garde qui ne coûte rien et le seul qui protège les autres d'être exécutés. Une requête refusée consomme quand même son quota : sinon, deviner des clés serait gratuit.
2. **Origine**, quand l'app en liste. Une liste vide n'autorise **aucun** navigateur, pas tous : un défaut « n'importe quelle page peut appeler » est la façon dont un point d'accès finit intégré à un site dont son propriétaire n'a jamais entendu parler.
3. **Clé**, comparée par `hmac.compare_digest`.
4. **Plafond du jour**, lu sur `token_usage`. En dernier parce que c'est une lecture SQLite : le mettre avant la limite de débit laisserait une inondation faire un aller-retour en base par requête.

Le CORS n'est appliqué que par les navigateurs. `curl` l'ignore entièrement. Ce qui tient contre un non-navigateur, c'est la limite de débit et le plafond du jour, qui s'appliquent à tout le monde.

### Le publier

`CORP_APPS_HOST` vaut `127.0.0.1` : le point d'accès n'est joignable que depuis cette machine. **Publiez-le par un tunnel ou un reverse proxy, pas en ouvrant l'adresse d'écoute** — un proxy vous donne TLS, un vrai journal d'accès et un endroit où couper, et ouvrir le bind ne vous donne rien de tout ça.

```bash
# Cloudflare Tunnel : pas de port ouvert, TLS fourni, révocable côté Cloudflare
cloudflared tunnel --url http://127.0.0.1:8610

# ou, derrière un nginx que vous tenez déjà
# location /v1/apps/ { proxy_pass http://127.0.0.1:8610; }
```

Le doctor signale une app définie sans clé — elle a l'air prête et chacun de ses appels est refusé — et une app sans origine, que nul navigateur ne peut appeler.

## La même app, figée dans le site

Une app tourne à la requête **ou** à la construction. Dans `company.yaml` :

```yaml
site:
  faq_app: faq
  faq:
    - Combien ça coûte ?
    - Est-ce que ça marche pour une reconversion ?
```

`corparius site` exécute l'app une fois par question et écrit les réponses dans le HTML. **La page reste un seul fichier statique** : pas de JavaScript, aucun point d'accès à joindre, rien à laisser allumé. C'est la propriété que `sitegen/` défend depuis le début, et un widget de conversation l'aurait échangée contre une fonctionnalité que personne n'a demandée.

Un modèle injoignable omet la section et construit la page quand même. Ne pas publier parce qu'un fournisseur gratuit a eu un hoquet serait un mauvais échange pour une FAQ.

## Exporter l'app avec le site

Pour un site qui répond tout seul, sans machine allumée :

```bash
corparius apps export netlify --app faq --company example
```

Écrit `netlify/functions/faq.mjs` à côté du site construit, et nomme la variable d'environnement à poser chez l'hébergeur.

**À partir de là, corparius ne voit plus la dépense.** La clé vit chez l'hébergeur, donc le plafond du jour, la limite de débit et la ligne de l'app dans la ventilation des coûts ne s'appliquent plus à ce que cette fonction dépense. C'est le prix d'un site qui répond sans que rien de chez vous ne tourne, et l'avertissement est répété en tête du fichier généré — là où vous le lisez au moment de le choisir.

L'export refuse ce qui ne pourrait échouer que plus tard : un palier `local:` (pas d'Ollama dans une fonction), `claudecode:` (pas de CLI ni de connexion), `cloud:` (ce serait recopier la clé Anthropic), et une app sans `origins` (la fonction refuserait tous les navigateurs pour lesquels elle existe).

## Ce que ça ne fait pas

- **Aucun agent n'appelle une app.** Le roster a ses outils ; une app sert le monde extérieur. Mélanger les deux donnerait au modèle un moyen de contourner le pare-feu de permissions.
- **Aucune app ne lit le magasin.** Elle reçoit son invite système, ce que le visiteur a écrit et les faits de `company.yaml`. Le journal, les prospects et les approbations restent hors de portée.
- **Rien n'est activé par défaut.** `CORP_APPS_ENABLED` est à `false` comme les plugins, et pour la même raison : c'est une surface qu'on ouvre délibérément.
