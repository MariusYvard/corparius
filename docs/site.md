# Génération de site de vente

corparius génère une page de vente autonome à partir de la config d'entreprise. Le résultat est un fichier HTML unique, responsive, sans dépendance ni étape de build, avec un bouton d'appel à l'action relié à un lien de paiement Stripe.

## Philosophie

Là où NullToHero est une boîte à outils large de conception et d'audit, ce module va droit au but. Une commande, une page prête à vendre. Le gabarit est unique et orienté conversion (accroche, problème, bénéfices, prix, appel à l'action), pas un constructeur multi-pages.

## Utilisation

En ligne de commande, `python -m corparius.cli site --company example` écrit la page dans data/sites/<slug>/index.html et affiche le chemin. L'option --headline force l'accroche. Le bouton pointe vers offer.payment_link de la config, sinon vers CORP_STRIPE_PAYMENT_LINK, sinon vers l'ancre de la section prix.

Dans la boucle autonome, l'agent design rédige une accroche puis régénère la page à chaque cycle via l'outil build_sales_site. La page reste un artefact de données, hors du dépôt. **Une tâche du backlog visant le site passe par `write_site_content`, pas par `build_sales_site`** : régénérer la page à partir d'un texte que personne n'a changé produit la même page et annonce une réussite. C'est l'outil qui écrit le texte dans company.yaml qui change quelque chose.

## Contenu

La page tire son texte de la config : nom, accroche (one_liner ou offer.product), douleurs de l'ICP, prix et facturation. Les valeurs sont échappées avant insertion dans le HTML.

**Rien n'est inventé, et une section vide disparaît.** Un champ absent ne prend plus une valeur neutre : la section n'est pas rendue. La version précédente imprimait « Cancel anytime » et « Instant onboarding » dans l'encadré de prix de *chaque* page produite — des conditions de vente que personne n'avait acceptées, sur le site commercial de quelqu'un d'autre. Ce qui figure dans « Ce que vous obtenez » vient de `offer.includes`, ou la section n'existe pas.

```yaml
offer:
  product: Check-in anonyme du moral
  price_eur: 9
  billing: stripe
  includes:                       # facultatif ; rien n'est ajouté d'office
    - Anonyme par conception
    - Export CSV
```

## Le contrat de contenu

Une page a été publiée avec ceci en H1, à 4 rem :

> « Check-in, anonyme, en 90 secondes. » Alternatively, a more punchy version: « Mental Check-in en 90s »

C'est le modèle en train de délibérer, affiché sur un site en ligne. `sitegen.clean_headline` refuse désormais le méta-commentaire (`Alternatively`, `Here is a headline:`, `Option 1 / Option 2`, les guillemets encadrants, deux variantes séparées par deux points) et, quand le bon titre est là entre guillemets, il le récupère. À défaut, il retombe sur la proposition de valeur écrite par un humain dans la config.

## La langue

`company.yaml` a un champ `language`. Il est déduit de ce que l'exploitant a écrit à la création, puis inscrit dans le fichier pour qu'il puisse le voir et le corriger :

```yaml
language: fr
```

Il fixe l'attribut `lang` de la page, les titres de sections, le libellé du bouton et la mention de facturation. Sept langues sont traduites (`en`, `fr`, `es`, `de`, `it`, `pt`, `nl`) ; une autre garde le mobilier en anglais autour d'un contenu qui reste dans la langue de l'entreprise — un mélange honnête plutôt qu'un titre traduit par personne. Le champ part aussi dans l'invite de chaque agent, ce qui règle les réponses support en anglais chez une entreprise française.

## L'apparence

Trois réglages, chacun facultatif :

```yaml
site:
  theme: light        # light | dark
  font: serif         # serif | sans
  accent: "#c2410c"   # #rrggbb
```

La page change de fond trois fois — héros teinté, corps neutre, bloc de prix inversé — et porte une **signature** : une bande de barres dont les hauteurs viennent d'une empreinte du nom de l'entreprise. Différente pour chaque entreprise, identique d'une construction à l'autre, environ 4 ko de SVG en ligne. Aucun fichier, aucune requête.

### Le contraste, calculé

Le bandeau de prix du thème sombre est parti avec un texte à **1,16:1** contre son propre fond — quasi-noir sur quasi-noir, illisible. Une ligne supposait que la couleur de fond de la page fait un bon texte sur le bandeau inversé : vrai en thème clair (18:1), faux en thème sombre. Rien ici ne savait ce qu'était un contraste, donc rien ne l'a vu.

`sitegen.palette_for()` dérive maintenant chaque couleur de texte de ce sur quoi elle se pose, et `tests/test_sitegen_contrast.py` parcourt les deux thèmes contre six accents. Seuils WCAG 2.1 AA : 4,5 pour le texte courant, 3,0 pour le grand texte et les commandes.

Deux règles en découlent :

- **Aucune couleur n'arrive par `color-mix`.** Une valeur qui se résout dans le navigateur est une valeur qu'aucun test ne peut mesurer.
- **`#fff` n'est jamais un libellé de bouton en dur.** Il échoue sur tout accent clair — 1,74:1 sur le vert utilisé en exemple. Le libellé est celui du blanc ou du quasi-noir qui gagne contre l'accent choisi.

### Le référencement

La page portait quatre balises `meta`. Elle porte maintenant :

- `<link rel="canonical">`, Open Graph complet et carte Twitter ;
- des **données structurées** JSON-LD : `Product` avec son `Offer` (prix, devise, disponibilité, lien de paiement), et `FAQPage` quand la FAQ existe — la FAQ n'est demandée qu'une fois et sert aux deux ;
- `robots.txt` et `sitemap.xml`, écrits à côté de `index.html` ;
- `<header>`, `<main>`, `<footer>` comme vrais repères, un seul H1.

Le `<title>` mène par la promesse et non par le nom de l'entreprise — un lecteur qui parcourt dix résultats ne sait pas encore ce qu'est « Vigil ». Il tient sous ~60 caractères, la description sous ~155.

**Rien n'est inventé là non plus.** Les données structurées sont l'endroit où un générateur est le plus tenté : une note fabriquée est invisible à l'écran et remonte quand même dans le résultat de recherche. Jamais de `aggregateRating`, `reviewCount` ni `Review`. Pas de prix signifie pas d'`Offer`, et non `"price": "0"` qui annoncerait un produit gratuit.

Tout ce qui est absolu — canonical, `og:url`, le sitemap — a besoin de `site.url` :

```yaml
site:
  url: https://vigil.fr
```

Sans lui, ces éléments sont **omis, jamais devinés** : un canonical vers la mauvaise adresse dit à un robot d'indexer quelqu'un d'autre. `corparius doctor` le signale une fois plutôt que de vous laisser le découvrir.

Les réponses de modèle qui entrent dans le bloc JSON-LD ont chaque `<`, `>` et `&` échappés en `<` : du JSON valide, identique une fois décodé, et rien dans le bloc qu'un analyseur puisse lire comme du balisage. Échapper seulement `</script>` est le conseil habituel, mais c'est raisonner sur des états d'analyse HTML, et c'est là que vivent les XSS.

Ces règles sont écrites dans [`DESIGN.md`](../DESIGN.md) et dans la compétence livrée `packaging/skill-pack-starter/skills/landing-craft/`, que l'agent design lit avant de rédiger. Elles existent parce que le générateur a échoué deux fois : d'abord un gabarit centré avec sa grille de cartes, puis, une fois le gabarit retiré, une page plate — « on dirait une page blanche avec du texte ». Retirer un gabarit n'est que la moitié du travail.

## Une FAQ écrite à la construction

Le bloc `site:` de `company.yaml` fait rédiger une FAQ par une app de l'entreprise, une fois, au moment de la construction :

```yaml
site:
  faq_app: faq          # une app de companies/<slug>/apps/
  faq:
    - Combien ça coûte ?
    - Est-ce que ça marche pour une reconversion ?
```

Les réponses sont écrites dans le HTML. **La page reste un seul fichier statique** : pas de JavaScript, aucun point d'accès à joindre, rien à laisser allumé. C'est la propriété que ce générateur défend depuis le début, et un widget de conversation l'aurait échangée contre une fonctionnalité que personne n'a demandée.

Un modèle injoignable omet la section et construit la page quand même : ne pas publier parce qu'un fournisseur gratuit a eu un hoquet serait un mauvais échange pour une FAQ. Les réponses sont échappées comme le reste — c'est de la sortie de modèle sur une page publique.

Voir [`docs/apps.md`](apps.md) pour écrire l'app, et pour l'autre mode : le même fichier servi à la requête.

## Déploiement

La génération produit le fichier. La mise en ligne (Netlify, un compartiment S3, un hébergeur statique) est l'étape suivante et reste sous validation humaine, comme toute action de publication.

`corparius apps export netlify --app <nom>` écrit en plus une fonction à côté du site, pour une page qui répond sans machine allumée — au prix, dit explicitement, de la visibilité de corparius sur cette dépense.
