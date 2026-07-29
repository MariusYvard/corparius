# Génération de site de vente

corparius génère une page de vente autonome à partir de la config d'entreprise. Le résultat est un fichier HTML unique, responsive, sans dépendance ni étape de build, avec un bouton d'appel à l'action relié à un lien de paiement Stripe.

## Philosophie

Là où NullToHero est une boîte à outils large de conception et d'audit, ce module va droit au but. Une commande, une page prête à vendre. Le gabarit est unique et orienté conversion (accroche, problème, bénéfices, prix, appel à l'action), pas un constructeur multi-pages.

## Utilisation

En ligne de commande, `python -m corparius.cli site --company example` écrit la page dans data/sites/<slug>/index.html et affiche le chemin. L'option --headline force l'accroche. Le bouton pointe vers offer.payment_link de la config, sinon vers CORP_STRIPE_PAYMENT_LINK, sinon vers l'ancre de la section prix.

Dans la boucle autonome, l'agent design rédige une accroche puis régénère la page à chaque cycle via l'outil build_sales_site. La page reste un artefact de données, hors du dépôt.

## Contenu

La page tire son texte de la config: nom, accroche (one_liner ou offer.product), douleurs de l'ICP, prix et facturation. Rien n'est inventé, un champ absent prend une valeur neutre. Les valeurs sont échappées avant insertion dans le HTML.

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
