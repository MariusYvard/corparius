# knowledge-work-plugins

`anthropics/knowledge-work-plugins` est la bibliothèque officielle de plugins d'Anthropic pour le travail de bureau, publiée sous licence Apache-2.0 avec un `LICENSE.txt` par compétence. Dix-sept plugins, cent quarante et une compétences, organisés par métier plutôt que par technologie : l'ingénieur, l'analyste, le chef de produit, le commercial, le marketeur, le support, l'opérateur, la finance, le juriste, les RH, le designer, le chercheur, le dirigeant de petite entreprise.

C'est le comparable le plus direct de `corparius/skills.py` — même nom de fichier, même en-tête YAML, même idée : de la connaissance métier en prose plutôt qu'en code.

## Architecture

Un plugin est un dossier : `.claude-plugin/plugin.json` pour le manifeste, `.mcp.json` pour les connecteurs, `commands/` pour les commandes explicites, `skills/<nom>/SKILL.md` pour la connaissance. Les grosses compétences poussent le détail dans `references/*.md` et `scripts/*.py` à côté du `SKILL.md`. Le dépôt le résume ainsi : *« every component is file-based — markdown and JSON, no code, no infrastructure, no build steps »*.

L'en-tête réel, relevé sur `customer-support/skills/draft-response/SKILL.md` :

```yaml
name: draft-response
description: Draft a professional customer-facing response tailored to the situation…
argument-hint: "<situation description>"
```

Trois clés, et **pas** de `allowed-tools`. C'est cohérent chez eux : la `description` est écrite pour que le modèle réclame lui-même la compétence quand il la juge pertinente. La sélection est du routage par le modèle.

## Pourquoi rien ne se dépose ici

Trois mesures, prises sur les fichiers et non sur la présentation qui en est faite.

**Aucun `allowed-tools`.** Dans corparius, `Skill.unscoped` est vrai dès que la clé manque, et une compétence non cadrée entre dans **chaque** invite de **chaque** agent. Les cent quarante et une déposées telles quelles seraient un impôt permanent sur le budget de jetons — exactement la panne silencieuse que le chargeur a été durci à exposer trois jours plus tôt, et dont le motif écrit alors était : « c'est à ça que ressemble une compétence écrite pour un autre hôte quand on la dépose ici ».

**La taille.** Médiane ≈ 12 Ko, maximum 26 Ko (`sales/create-an-asset`), contre `CORP_SKILL_MAX_CHARS = 4000` pour le bloc **entier**. Les compétences livrées avec corparius pèsent environ 1 Ko. Un import brut serait tronqué à un cinquième.

**Ce sont des commandes slash pour un humain présent.** `marketing/campaign-plan` : *« Gather the following from the user. If not provided, ask before proceeding. »* Les agents de corparius tournent sans surveillance sur une cadence, et `docs/architecture.md` écarte le routage par le modèle.

Sur les cent quarante et une, une quarantaine visent un métier que les vingt-neuf outils d'ici exercent déjà. Le reste — pipelines de bio-recherche, SDK Zoom, rédaction de contrats, RH, signature de PDF — vise des métiers que ce roster n'a pas.

## Ce que corparius en tire

**La prose, pas les fichiers.** `corparius skills import` copie un corps verbatim, remplit l'en-tête manquant, et annonce l'arithmétique avant d'écrire : « 14182 caractères, plafond 4000, 71,8 % sera coupé ». Deux refus portent la valeur : un nom inconnu de la table de correspondance ne reçoit aucun outil — une portée inventée pointe de la prose vers le mauvais agent en silence — et un import n'écrase jamais une compétence, parce que ce qui rend un import utilisable est l'élagage fait après.

**Six compétences de départ.** Adaptées, créditées, ramenées à ~1 Ko, cadrées sur les outils qui n'avaient aucune prose : `support-triage`, `social-cadence`, `books-hygiene`, `competitor-watch`, `design-handoff`, `ship-gate`.

**Un pack de compétences n'a pas besoin de code.** C'est la remarque qui valait d'être prise. `PluginManifest` exigeait un `entrypoint` module:fonction, donc la seule façon de distribuer de la prose était d'écrire du Python qui tourne pour n'exécuter rien. Un manifeste `kinds: ["skills"]` peut désormais l'omettre. La liste blanche vérifiée continue de s'appliquer : de la prose n'exécute rien et entre quand même dans l'invite système avec l'autorité du prompt de rôle.

## Ce qui a été écarté

**La sélection par `description`.** C'est leur mécanisme central et c'est du routage par le modèle. Corparius décide en code, ce qui rend le catalogue inutile dans l'invite et fait qu'un tour paie les compétences qui s'y appliquent et rien d'autre.

**`argument-hint`.** Il n'y a pas d'argument : personne ne tape de commande, un agent exécute un playbook fixe à sa cadence.

**Les connecteurs MCP par plugin.** Corparius a déjà `docs/mcp.md` et un registre d'intégrations ; un second chemin de configuration par pack de prose serait deux endroits où débrancher la même chose.

**`references/` et `scripts/`.** La divulgation progressive par fichier suppose que quelque chose sait réclamer le fichier suivant. Ici, une compétence trop grosse pour le plafond doit être coupée par son auteur, pas répartie sur des fichiers que rien ne viendra chercher.

**Les treize plugins hors périmètre.** Juridique, RH, bio-recherche, PDF : leur donner un outil ici serait inventer un métier plutôt qu'en nommer un. Un test l'épingle, pour que la table de correspondance ne devienne pas une liste de souhaits.
