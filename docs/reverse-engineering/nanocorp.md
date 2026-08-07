# NanoCorp

NanoCorp est une plateforme de création et d'exploitation d'entreprises autonomes. La société est fondée en 2023 par Pierre-Louis Biojout, compte un salarié, est basée à San Francisco et financée par Y Combinator.

## Modèle

À partir d'une formulation en langage naturel, la plateforme déploie une micro-entreprise pilotée par un agent exécutif. L'agent poursuit un signal unique (le chiffre d'affaires) et cherche à éviter la faillite sans intervention humaine. L'infrastructure produite associe une page de destination, une base de données, un système de paiement Stripe et des campagnes d'acquisition. L'approche est la création ex nihilo de structures nouvelles, par opposition à l'autonomisation d'entreprises existantes que vise Pancake.

## Chiffres publics

Les indicateurs communiqués varient dans le temps et proviennent du fondateur ou du tableau de bord public. Un message du fondateur sur LinkedIn annonce 193 000 $ d'ARR atteints en trois jours. Le tableau public "live" recense les entreprises créées, les sites déployés et un cumul de chiffre d'affaires réel généré par les agents, de l'ordre de quelques centaines de dollars sur les premières semaines (par exemple 264,27 $ pour 29 transactions à une date donnée). Des entreprises individuelles affichent des revenus faibles mais réels, tel un service d'audit de profils LinkedIn à 1 540 $.

Cohérence des données: le document de travail interne mentionne un ARR de 9 millions de dollars à la mi-2026 et, dans le même tableau, un chiffre d'affaires cumulé de plateforme de 9 854 $. Ces deux valeurs sont incompatibles. Les données publiques vérifiables se situent dans l'ordre de grandeur des milliers de dollars de chiffre d'affaires cumulé, pas des millions d'ARR. Le chiffre de 9 millions n'est pas corroboré et n'est pas repris ici.

## Tarification

Le palier d'entrée (Founder) est gratuit avec trois crédits d'exécution initiaux. Les paliers payants montent vers 30 $ par mois pour un volume de crédits élargi. La plateforme fournit l'hébergement et une adresse de messagerie sur son domaine.

## Ce que corparius reprend

corparius conserve deux principes: le signal de récompense unique (chiffre d'affaires) et la boucle d'agents planifiés. Il les exécute en local, sur la machine de l'exploitant, avec un pare-feu budgétaire et une validation humaine sur les actions sensibles. Le déploiement d'infrastructure tierce (domaines, paiements) reste hors du périmètre autonome par défaut.

## Rétro-ingénierie des journaux d'exécution

Tout ce qui précède vient de sources publiques. Cette section vient d'autre chose :
les journaux d'exécution d'une vraie entreprise NanoCorp appartenant au
propriétaire de corparius — `Vigil`, session du 26/05/2026, de 14:08 à 16:31.
**Le journal fourni est tronqué à 16:31** : ce qui suit est hors de portée, et rien
ici n'est déduit de ce que je n'ai pas lu.

NanoCorp et corparius répondent à la même question et arrivent à deux architectures
presque opposées. NanoCorp donne à un *worker* un dépôt, un shell, un navigateur et
des procédures nommées, puis le laisse expédier. Corparius donne à dix *rôles* un
catalogue d'outils déclarés, un budget de jetons et un backlog, puis les fait
tourner en boucle. Les deux ont des défauts réels ; ce qui suit sépare ce qui se
transfère de ce qui ne se transfère pas.

### Ce que le journal produit, compté

Sur ~2h20 : une application Next.js 16 échafaudée et déployée sur Vercel, un
produit Stripe créé et branché sur deux CTA, une page `/tech`, une UI de check-in
de 90 s avec minuteur, un endpoint `POST /api/check-in` adossé à Cerebras, un
microservice Python FastAPI d'extraction prosodique (décodage Opus en mémoire,
`librosa` + `parselmouth`), une migration PostgreSQL avec contraintes strictes et
20 lignes de seed, un module React Native autour d'openSMILE 3.0 compilé et validé
à `feature_count=88`, et quatre documents techniques. **13 tâches créées, 11
exécutées dans la fenêtre lue.**

Le compte qui compte pour corparius : **une tâche sur onze s'est terminée
« bloquée »** — le post Reddit — et c'est celle qui apprend le plus.

### 1. Le worker travaille sur le dépôt, pas sur un artefact dérivé

Chaque tâche lit de vrais fichiers, les édite, lance `npm run build`, commite,
pousse, vérifie la production, rapporte le SHA. Quand le build casse, il lit
l'erreur et corrige : *« le `logger` FastAPI n'existe pas tel quel »*, *« un
`std::vector` a été interprété comme déclaration de fonction »*.

Corparius dérivait la page d'un fichier de configuration. **Et c'est là qu'était le
vrai trou, mesuré sur l'installation du propriétaire :** `companies/vigil/site/`
contenait six pages HTML écrites à la main, une feuille de style, une fonction
serverless, `robots.txt` et `sitemap.xml`, versionnées dans le dépôt privé de
l'entreprise — et corparius ne voyait rien. `build_sales_site` régénérait une page
unique à partir de quatre champs de `company.yaml`, à chaque tour de l'agent
design, et annonçait « Sales site built » ; `deploy_site` publiait *celle-là*.
L'exploitant demandait pourquoi son site restait mauvais : **le produit n'avait
jamais touché son site.**

**Transféré.** `paths.owned_site(slug)` : si l'entreprise a son propre dossier
publiable, c'est ça le site. Le générateur refuse de l'écraser et dit ce qu'il
contient ; `deploy_site` et la console publient et prévisualisent le même dossier.
Un `netlify.toml` avec une clé `publish` est honoré — une entreprise qui en a écrit
un a déjà dit quel dossier est le site, et publier la racine y enverrait sa
configuration et ses sources serverless.

**Pas transféré :** échafauder un framework, installer des dépendances, lancer un
build. Corparius tient sur deux dépendances d'exécution et n'a pas de bac à sable ;
un agent qui lance `npm install` sur la machine de l'exploitant est un autre
produit. La frontière retenue : *corparius publie ce que l'entreprise possède, il
ne le compile pas.*

### 2. La vérification est bornée, unique, et dit ce qu'elle a mesuré

La compétence `vercel-deploy-verify` impose une forme exacte : pousser, attendre
une durée fixe, faire **un** contrôle contre la production, dire si c'est frais ou
encore en cache, **et s'arrêter dans les deux cas**. Le worker la narre : *« je suis
dans la fenêtre d'attente réglementaire de 90 secondes »*, *« je m'y limite à une
seule séquence `agent-browser open` »*, *« j'arrête même si le CDN sert encore
l'ancienne version »*.

Ce que ça vaut est dans le journal : sur la tâche Cerebras, le push a réussi, la
route était déployée, et **la production répondait `La variable
NANO_USER_CEREBRASAPIKEY est absente`**. Sans le contrôle, cette tâche finissait en
succès.

Corparius annonçait `Site published: netlify -> <url>` sur la parole du fournisseur
et n'allait jamais chercher l'adresse. Un hôte qui accepte un envoi et sert autre
chose — cache ancien, 404, page d'erreur de build — était indistinguable d'une
publication réussie.

**Transféré**, dans `corparius/providers/sitecheck.py` : attente bornée
(`CORP_DEPLOY_VERIFY_WAIT`, plafonnée à 180 s), une requête, un verdict parmi
`fresh` / `stale` / `unreachable` / `unverified`, et une phrase qui dit d'où il
vient. Le marqueur est le `<title>` et non un hachage des octets : une page générée
porte un horodatage de build, donc un hachage diffère à chaque build et chaque
contrôle lirait « périmé ». Aucune reprise, jamais de boucle.

Deux règles de la maison contraignent ce module. *Prouver plutôt que demander qu'on
croie* : le verdict vient d'une vraie réponse. *Jamais de sonde réseau depuis un
point interrogé en boucle* : c'est appelé après un déploiement, par l'outil qui a
déployé — jamais par le doctor ni par le sondage de la console.

### 3. `DOCS.md` : un journal que les agents écrivent et relisent

**Chaque** worker ouvre par « je lis `DOCS.md` » et ferme par « je mets à jour
`DOCS.md` avec les constats d'exploration ». La raison est dite explicitement :
*« pour éviter de réexplorer ce service au prochain tour »*, *« pour que le prochain
agent n'ait pas à ré-explorer le dépôt »*.

Ce n'est pas de la documentation : c'est un cache d'exploration partagé entre des
agents qui ne partagent pas de contexte — exactement le problème de corparius quand
dix rôles redérivent la même chose à chaque tick.

**Déjà présent, en partie.** `documents.write()` fait atterrir ce qu'un agent écrit
dans le même dossier que les fichiers déposés par l'exploitant, et
`documents.context()` le réinjecte. La différence est de discipline, pas de
mécanisme : les agents de corparius y écrivent des *livrables* (un brief de design,
une note de prix) et jamais des *constats*.

### 4. Un blocage est un résultat, avec preuve et artefact utilisable

La tâche Reddit est le meilleur passage du journal. Le worker essaie trois canaux
dans l'ordre, constate que Reddit refuse sans compte authentifié et que la page
« upcoming » de Product Hunt n'est pas un flux de soumission, cherche des
identifiants dans le dépôt, n'en trouve pas — puis **écrit les blocages exacts dans
`DOCS.md`, y laisse un brouillon de post en français prêt à publier, commite et
pousse**, en disant pourquoi : *« pour que la prochaine tâche se concentre
étroitement sur l'accès au compte plutôt que sur une redécouverte »*.

À comparer au journal corparius du même exploitant, deux mois plus tard :
`find_targets: No lead found. Sources configured: none.` — **la même ligne, plus de
quarante fois**, sans trace disant que c'était déjà établi, et sans brouillon
utilisable nulle part. C'est le « il tourne en rond » rapporté par l'exploitant,
dans sa forme la plus pure.

**À transférer.** Le refus est déjà propre (`skip_when` évite même de payer la
rédaction), mais il n'est pas *enregistré*. Forme visée : la première fois qu'un
outil bute sur un mur qu'un humain seul peut abattre, il écrit le constat, le
remède et l'artefact déjà rédigé dans les documents de l'entreprise — une fois — et
les tours suivants lisent ce document au lieu de redécouvrir.

### 5. Des procédures nommées, avec conditions d'arrêt déclarées

Le journal cite les compétences par leur nom : `worker-stop-conditions`,
`task-result-summary`, `nanocorp-cli`, `agent-browser`, `vercel-deploy-verify`,
`browser-troubleshooting`, `nextjs-bootstrap`. Ce ne sont pas des notes en prose,
ce sont des procédures avec budgets de reprise, et le worker les respecte
visiblement : *« l'unique tentative d'installation autorisée »*, *« je borne les
reprises »*.

Il y a aussi une notion que corparius n'a pas : une **précondition** à satisfaire
avant d'éditer. `AGENTS.md` exige d'avoir lu la doc Next 16 locale ; le worker
constate que `node_modules/next/dist/docs` n'existe pas et **installe les
dépendances pour satisfaire la précondition** au lieu d'écrire du code contre une
API supposée. Le `skip_when` de corparius est le cousin le plus proche, mais il
*saute* au lieu de *remédier*. Le disjoncteur de corparius, lui, est global et non
par procédure.

### Ce qui ne se transfère pas, et pourquoi

- **Le worker unique à long horizon.** NanoCorp fait tenir une tâche entière dans une session avec shell, navigateur et dépôt. Corparius exécute des tours courts avec des rôles séparés et un budget de jetons — c'est ce qui le rend auto-hébergeable sur une machine sans GPU, et c'est aussi ce qui l'empêche de faire ce que fait ce worker.
- **`agent-browser`.** Un navigateur piloté ajoute Chromium comme dépendance ; le journal montre qu'il échoue trois fois sur `Chrome not found` et coûte chaque fois une installation.
- **Créer des tâches depuis un document produit par un autre agent.** NanoCorp le fait très bien : la synthèse paralinguistique de 15:45 engendre six tâches techniques précises à 16:02. `_create_tasks` met en file des triplets écrits en dur. C'est un écart réel, et le prochain candidat sérieux — pas quelque chose à bricoler en fin de lot.
- **Crédit et provisionnement** (`[CRDT]`, `Database provisioned`, `Custom domain configured`) sont d'une plateforme hébergée. Corparius est auto-hébergé : ces lignes n'ont pas de destinataire ici.

### Ce que ce journal dit aussi sur Vigil

Le journal est du 26/05/2026. La migration hors NanoCorp
(`companies/vigil/_migration/`) est du 28/07/2026 et avait déjà repris l'essentiel :
le site multi-pages, le produit Stripe sur le compte marchand de l'exploitant, la
synthèse voix-vers-baseline, les compétences. Ce qui manquait n'était pas le
contenu — **c'était que corparius sache que ce contenu existe.**

## Sources

- https://www.nanocorp.so/
- https://www.nanocorp.so/live
- https://www.ycombinator.com/companies/nanocorp
- https://news.ycombinator.com/item?id=48062033
- Les journaux d'exécution de l'entreprise `Vigil`, 26/05/2026 14:08–16:31, fournis par le propriétaire. Tronqués à 16:31.
