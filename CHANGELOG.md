# Changelog

Versions are the git tags, and the sections under each are the changes that
shipped in it. Everything below 0.1.0 said "Unreleased" when 0.1.0 shipped —
there had never been a release to mark them against, and marking them after
the fact is more honest than leaving a released changelog claiming nothing
was released.

## Non publié

- **Added : les fichiers pour crawlers d'un site possédé suivent l'adresse réelle.**
  `sitegen` traçait cette ligne depuis toujours pour une page générée — une balise
  absolue est **omise plutôt que pointée vers une supposition**, parce qu'un lien
  canonique vers la mauvaise adresse est pire pour un site que pas de canonique du
  tout. Un site que l'entreprise possède n'en bénéficiait pas : il livrait des
  fichiers écrits à la main nommant un hôte, et aucune étape ne les faisait
  s'accorder avec l'endroit où le site est publié. Maintenant qu'une publication
  enregistre l'adresse qu'elle renvoie, l'étape de déploiement reconstruit
  `robots.txt` et `sitemap.xml` depuis cette adresse et les pages qui existent
  réellement, pointe les balises canoniques dessus, **en insère une là où il n'y en a
  pas**, et renvoie le tout.
  Trois défauts de ma part attrapés en l'exécutant, pas en le relisant : ma première
  version **régénérait `robots.txt` en entier**, ce qui aurait supprimé une vraie
  décision — l'exploitant y autorise GPTBot, ClaudeBot, PerplexityBot et
  Google-Extended, avec un commentaire expliquant pourquoi ; seule la ligne
  `Sitemap:` change désormais. Elle listait aussi `merci.html`, que ce même fichier
  interdit et qui est `noindex` — un sitemap qui contredit le robots.txt à côté de
  lui est un défaut qu'un crawler rapporte. Et elle ne faisait que *réécrire* les
  balises existantes, alors que j'avais supprimé celles de Vigil : les pages
  seraient revenues sans canonique du tout.
- **Vigil : la revue de site appliquée, seize constats.** L'exploitant a posé la
  règle — on ne vend pas ce que la companie n'a pas encore — et `review_site` avait
  déjà nommé les changements en citant le texte. Le bloc d'état réel remonte au-dessus
  de la section qui vend, « Essayer maintenant » devient « Essayer la démo texte », la
  mention « produit par un modèle de langage » passe **avant** le bouton, le vocabulaire
  d'étude clinique disparaît, la page tech cesse de se contredire au présent, son titre
  anglais passe en français, et la promesse de contact nominatif est signée. Rien n'est
  inventé : la biographie est celle de l'exploitant, verbatim de ses propres relances et
  déjà plus bas sur la même page — je l'ai vérifiée avant de la mettre en avant.
  `vigil-hq.fr`, domaine qu'il ne possède pas, est retiré des six balises absolues, du
  sitemap et du JSON-LD. **Le site est publiable : `deploy_site` ne refuse plus.**

- **Added : le CEO transforme en travail ce que ses agents ont écrit.** C'est le
  mécanisme NanoCorp que le document de rétro-ingénierie signalait et que je n'avais
  que constaté : leur synthèse paralinguistique de 15:45 engendre six tâches
  techniques précises à 16:02. `_create_tasks` met en file des triplets écrits en
  dur lus dans le journal d'actions, et un document qu'un agent a écrit n'en fait
  pas partie. Le cas concret était posé dans l'installation du propriétaire :
  `review_site` avait écrit **16 changements nommés** dans
  `documents/written/site-review.md`, en citant le texte à corriger, et rien ne le
  lisait — encore la donnée qui arrive et qu'on jette, cette fois une page entière.
  `plan_from_documents` la lit et propose au plus quatre tâches, chacune validée
  contre le vrai roster (rôle activé, outil de **son** playbook), dédupliquée contre
  le tableau, refusée et nommée quand le roster ne peut pas l'honorer, et soumise à
  la limite de travail en cours comme n'importe quelle autre.
  **Prouvé sur les vrais documents de Vigil** via l'Opus pin : quatre tâches
  spécifiques sorties, deux mises en file, deux refusées parce que design était à sa
  limite — dit, pas silencieux.
  Un défaut de ma part attrapé en le mesurant : `end-of-day.md` est réécrit à chaque
  tour du CEO, donc par date il est **toujours** le document le plus récent. Ma
  première version planifiait depuis le résumé du CEO lui-même — un miroir — pendant
  qu'une revue de site nommant seize changements restait quatrième et n'entrait
  jamais dans la fenêtre.

- **Fixed : le doctor réclamait des modèles locaux à des installations qui n'en
  utilisent aucun.** `needs_local` valait `... or True` — la condition était morte,
  donc chaque installation se faisait dire de télécharger les modèles locaux.
  **Mesuré sur celle du propriétaire** : les trois paliers sont distants et chaque
  étape de la chaîne de repli est distante, donc Ollama n'est atteint que si *tous*
  les fournisseurs distants tombent en même temps. Lui demander 4,7 Go pour ça est
  une corvée déguisée en avertissement — et un avertissement inactionnable est un
  avertissement qu'on apprend à faire défiler. Le contrôle est donc gradué : un
  palier pointé sur un modèle absent est un avertissement (ces tours ne peuvent pas
  tourner) ; le local en dernier recours est un **fait**, dit comme tel, avec le prix
  de son absence — plus de filet si tout tombe, et les embeddings sur le hachage
  intégré, plus grossier pour le garde-fou anti-répétition et pour reconnaître un
  souvenir déjà détenu. Les `ollama pull` sont proposés, pas exigés.
- **Added : l'adresse qu'une publication renvoie est écrite dans `site.url`.**
  C'est le seul fait SEO que le générateur ne peut pas déduire — lien canonique,
  `og:url`, `sitemap.xml` et `robots.txt` en dépendent — et l'exploitant ne peut pas
  le connaître avant la première publication, puisque c'est Netlify qui l'attribue.
  Le fournisseur le renvoyait déjà (`netlify:<url>`) et personne ne le relisait :
  encore la donnée qui arrive et qu'on jette. **Mesuré, jamais devinée** : écrite
  uniquement depuis ce qu'un fournisseur a réellement répondu, et uniquement dans un
  champ vide — un domaine que l'exploitant a choisi n'est jamais écrasé, parce qu'il
  a décidé.

- **Added : `write_note`, l'outil qui écrit le document qu'une tâche demande.**
  Cinq outils écrivaient déjà des documents — `draft_design_brief`,
  `update_pricing`, `scan_competitors`, `write_eod_summary`, `review_site` — chacun
  sous un nom fixe. Aucun n'écrivait *le* document qu'une tâche particulière
  réclame, donc « rédiger une note de cadrage pour le contrat de licence
  institutionnelle » n'avait nulle part où aller : strategy n'avait aucun outil
  capable de produire un document, la tâche restait retenue, et quand le CEO l'a
  placée quand même elle est tombée sur `write_site_content` — qui aurait écrit du
  texte de site pour un contrat de licence. `ROLE_TOOL["strategy"]` pointe
  désormais sur `write_note`, donc une tâche de strategy est exécutable à
  l'approbation. **Prouvé sur la vraie tâche #80 de Vigil** : 3 232 caractères
  écrits par l'Opus pin, gardés dans les documents de l'entreprise.
  Il est `by_task_only` : sur un playbook il écrirait une note sur rien, à chaque
  tour. Et l'invite lui demande d'étiqueter chaque chiffre Mesuré / Donné / Estimé,
  parce que sa sortie entière est de la prose qui peut en contenir.
- **Fixed : `ask_operator` parlait d'une tâche que le modèle ne pouvait pas voir.**
  Son invite dit depuis toujours « ce que **cette tâche** ne peut pas faire sans » —
  et rien n'avait jamais posé la tâche sur le contexte. Déclaré et inatteignable,
  dans une invite au lieu du code. `ctx.task` existe maintenant, posé pour la durée
  de l'appel et **effacé en sortant sur tous les chemins** : le contexte est partagé
  sur tout le tour, donc une tâche oubliée là serait lue par chaque outil suivant.
  Un test a posé l'invariant et a trouvé le chemin qui ne l'honorait pas — celui où
  rien ne peut exécuter la tâche.

- **Added : le CEO réattribue lui-même une tâche que rien ne peut exécuter.**
  C'est le sixième mécanisme des journaux NanoCorp, celui que
  `docs/reverse-engineering/nanocorp.md` désignait comme « le prochain candidat
  sérieux » : leur CEO crée et attribue le travail à partir de ce qu'un autre agent
  a produit. Corparius retenait la tâche et mettait un avis avec deux listes devant
  l'exploitant, qui l'a dit tel quel : **« je ne le vois pas proposer de lui-même
  l'agent et l'outil, c'est trop compliqué »**. Il a raison sur les deux points —
  offrir des choix n'est pas proposer, et ce n'était de toute façon pas sa décision.
  Une tâche retenue est une tâche que le CEO a mal attribuée, et le CEO est le rôle
  qui possède le backlog. Il lit donc les tâches retenues contre le vrai roster —
  chaque rôle activé et les outils de **son** playbook — et les réattribue.
  L'exploitant n'est sollicité que si le CEO n'arrive pas à en placer une, ce qui
  est mieux qu'un outil qui tournerait sans rien changer.
  Une attribution que le roster ne peut pas honorer est **refusée et nommée**, pas
  ignorée : c'est exactement l'erreur qui a produit la tâche retenue. Une tâche
  parquée sur une approbation de l'exploitant n'est jamais touchée — le préfixe de
  la note les distingue. **Prouvé sur les deux vraies tâches retenues de Vigil** :
  `Re-owned 2: #80 -> design/write_site_content, #70 -> design/write_site_content`.
- **Fixed : l'éditeur proposait « aucun outil » alors que le rôle en avait un.**
  Un seul helper décide maintenant du défaut, partagé par l'éditeur et l'avis :
  le registre `ROLE_TOOL` d'abord, puis la première étape du playbook du rôle. Sur
  le cas réel de l'exploitant, `strategy` propose `kaizen` au lieu de rien.
  « Aucun outil » reste offert mais n'est jamais présélectionné quand le rôle en a
  un : on ouvre l'éditeur parce qu'une tâche n'avait pas d'outil, et y répondre
  « aucun » est un haussement d'épaules.

- **Added : un plafond de jetons par rôle, demandé pour l'agent qui fait le site.**
  `budgets.role_tokens` donne à un rôle sa propre bourse — **en plus** du budget
  de session partagé, pas prélevée dessus. La raison est arithmétique : design
  tourne une fois par 24 ticks et son tour est le plus cher de l'entreprise (il lit
  et relit quatre vraies pages), support tourne toutes les 3 ticks. Mesuré sur une
  vraie semaine : 830 069 jetons dépensés contre un `session_tokens` de 120 000, et
  les tours de support arrivent d'abord — un seul pot commun veut dire que le rôle
  fréquent le dépense et que le rôle rare trouve la caisse fermée. Un rôle réservé
  est arrêté par **son** plafond, avec son nom dans le message ; les autres gardent
  exactement ce qu'ils avaient ; et le total reste ce qui arrête un emballement.
  Une entreprise qui ne demande rien ne change pas d'un iota.
  **Ma première version soustrayait**, et une réserve de 400 000 contre une session
  de 120 000 laissait la part commune à zéro — tous les autres rôles affamés d'un
  coup, l'inverse exact de ce que « donner plus à un rôle » peut vouloir dire.
  Trouvé en l'exécutant, pas en le relisant.
- **Fixed : dans le backlog, on ne pouvait changer ni l'agent ni l'outil d'une
  tâche.** `/api/tasks` accepte `target` et `tool` depuis toujours, et l'éditeur ne
  les a jamais offerts — donc une tâche sur le mauvais rôle, ou sans outil, ne
  pouvait pas être corrigée depuis le tableau où elle s'affiche. L'exploitant l'a
  dit tel quel. Les listes sont les mêmes que celles de l'avis : les agents
  réellement activés, et le playbook de l'agent choisi ; changer d'agent recharge
  ses outils. Les champs ne sont envoyés que s'ils ont été affichés, pour qu'une
  console sans agent activé ne puisse pas vider la cible en enregistrant. Vérifié
  en exécutant l'éditeur livré sur les deux cas réels : une tâche sans outil et une
  tâche outillée.

- **Fixed : l'aperçu du site servait `index.html` et rien d'autre.** Ce qui allait
  très bien tant que le site *était* une page générée. Pour une entreprise qui
  livre le sien — les quatre pages de Vigil, une feuille de style, un script, un
  dossier blog — chaque `/assets/style.css`, `/tech.html` et `/blog/` revenait en
  404, donc l'aperçu affichait la vraie copie de l'exploitant en Times New Roman
  avec des liens bleus soulignés. Il en a envoyé une capture et a logiquement lu ça
  comme un site cassé ; **ce n'était pas une limite de jetons, c'était ma route
  d'aperçu incomplète**. Elle sert maintenant le dossier, avec deux garde-fous
  posés avant qu'aucun chemin ne soit construit : le slug doit être une entreprise
  connue, et le fichier résolu doit rester dans le dossier du site — vérifié sur le
  chemin **résolu**, pas sur le texte de l'URL. Seules les extensions déclarées dans
  `SITE_TYPES` sortent : un dossier d'entreprise contient sa configuration et ses
  sources à côté du site, et un aperçu n'est pas un serveur de fichiers. Mesuré sur
  le vrai site : les huit ressources servies, les quatre tentatives de traversée
  refusées.

- **Fixed : « Ouvrir le backlog » ne faisait rien, et se règle maintenant sur
  place.** Le remède pointait vers l'onglet Opérations — **l'onglet même où l'avis
  est affiché** — donc appuyer dessus était un non-événement par construction.
  L'exploitant l'a signalé deux fois, et a demandé mieux : que la console propose
  elle-même l'agent et l'outil au lieu de le renvoyer les chercher. C'est
  maintenant le cas. L'avis porte l'identifiant de sa tâche (`options`), et rend
  deux listes : les agents réellement activés de l'entreprise, et les outils du
  **playbook** de l'agent choisi — parce qu'un outil absent d'un playbook est un
  outil que ce rôle ne lance jamais. Changer d'agent recharge ses outils, sinon
  « Assigner » donnerait à la tâche un outil que l'agent choisi n'exécute pas —
  la tâche sans outil, déguisée. Défaut proposé : celui du registre `ROLE_TOOL` ;
  **la décision reste à l'exploitant**, deviner la réponse d'après le libellé de
  la tâche serait une supposition déguisée en recommandation. L'identifiant est
  aussi passé dans le titre, parce que `notify` est idempotent sur le titre : deux
  tâches retenues se fondaient en un seul avis, et en régler une laissait l'autre
  invisible. Les dix fonctions du navigateur sont vérifiées **en les exécutant**
  sur le HTML livré, pas en les relisant — la version précédente avait été
  vérifiée en la relisant, et la relecture disait qu'elle marchait.

- **Fixed : un modèle pin était perdu par tout outil à schéma.** `spec.model`
  porte le modèle épinglé d'un rôle. La branche « brouillon brut » d'`agents.py`
  l'a toujours transmis ; la branche structurée ne l'a **jamais** transmis, et
  `structured.ask` n'avait même pas de paramètre `model`. Donc un pin était honoré
  pour de la prose et silencieusement ignoré pour tous les outils à schéma —
  c'est-à-dire la plupart de ceux qu'on a une raison d'épingler. **Mesuré sur un
  vrai tour** : design épinglé sur `claudecode:opus`, le journal affichait
  `[design] pinned to claudecode:opus`, et `review_site` était répondu par
  `cerebras:gpt-oss-120b` qui ne sait pas produire de JSON — l'outil répondait
  « no model returned usable structure » et ne faisait rien. Deux tests tiennent
  les deux bouts du fil.
  **J'avais d'abord mal diagnostiqué**, en accusant le délai de repos du routeur,
  et mon correctif a ramené la tempête de 429 que ce délai existait pour empêcher :
  vingt-et-quelques `Too Many Requests` contre un seul modèle en quatre minutes,
  vus dans un vrai run. La distinction juste n'est pas « cible demandée contre
  repli » mais **« modèle nommé contre palier par défaut »**.
- **Fixed : un modèle nommé n'est plus écarté par un délai de repos.** Le routeur
  déplaçait derrière tous les autres toute cible « au repos » — y compris la cible
  *demandée*. **Mesuré sur un vrai tour** : le rôle design était pin sur
  `claudecode:opus`, le journal disait `[design] pinned to claudecode:opus`, et la
  réponse venait de `cerebras:gpt-oss-120b` — qui ne sait pas produire de JSON,
  donc l'outil répondait « no model returned usable structure » et ne faisait
  rien. Le pin avait été rétrogradé parce que claudecode avait refusé une fois
  plus tôt dans le même run et se trouvait dans sa fenêtre de repos de 45
  secondes. Un délai de repos est une indication, un modèle pin est une
  instruction — et une instruction que le routeur réordonne en silence, c'est
  encore la forme « déclaré mais pas honoré ». La cible demandée garde donc sa
  place en tête ; seules les étapes de repli sont réordonnées, ce qui préserve
  entièrement la raison d'être du mécanisme. Coût d'essayer une cible au repos :
  un appel qui échoue, que la chaîne gère déjà. Coût de ne pas l'essayer : le
  choix explicite de l'exploitant ne tourne jamais.

- **Added : `review_site`, parce que le rôle design n'avait plus rien à faire.**
  Conséquence directe du correctif précédent, et pas un vieux bug :
  `write_site_content` écrit du texte dans `company.yaml`, que le générateur rend
  — et une entreprise qui publie du HTML écrit à la main n'en reçoit rien. Une
  fois que `deploy_site` s'est mis à publier le vrai dossier, l'agent design n'avait
  plus **aucun** outil capable de changer quoi que ce soit. Exactement le motif
  « atteignable et jamais atteint », arrivé comme conséquence d'une correction.
  Donc exactement l'un des deux tourne, et chacun dit pourquoi quand c'est le tour
  de l'autre. `review_site` **ne réécrit pas le HTML** : éditer des pages écrites à
  la main depuis une invite, sans build et sans test, transforme un site qui marche
  en site cassé — corparius publie ce qu'une entreprise possède, il ne le compile
  pas. Il lit les vraies pages et écrit une liste d'actions qui nomme les fichiers
  et cite le texte, ce que fait le worker NanoCorp quand il ne peut pas agir.
  **Prouvé sur le vrai site de Vigil**, via l'Opus pin : `source: claudecode:opus`,
  une tentative, **19 changements concrets** écrits dans ses documents — dont le
  plus important, que la page d'accueil vend au présent une tâche vocale que
  `beta.html` reconnaît comme pas encore en service.
  Deux défauts de ma part attrapés en le mesurant : trier les pages par taille
  faisait que seul `tech.html` entrait dans le budget et que `index.html` n'était
  **jamais** relue ; et l'invite pouvait revenir vide, ce qu'un test de contrat
  existant a refusé.

- **Fixed : « aucun lead trouvé », quarante fois, redécouvert chaque fois.** C'est
  la boucle rapportée par l'exploitant, dans sa forme la plus pure : une seule
  session a journalisé `find_targets: No lead found. Sources configured: none.`
  **plus de quarante fois**, pendant que le CEO mettait en file une nouvelle tâche
  outreach à chaque cycle et que `stop_useless_work` répondait « Every role still
  has somewhere for its work to go ». Chaque ligne était vraie, et chaque ligne
  était redécouverte. Le worker NanoCorp fait l'inverse sur un canal bloqué : il
  enregistre le blocage exact et écrit « pour que la prochaine tâche se concentre
  sur l'accès au compte plutôt que sur une redécouverte ». Le mécanisme existait
  déjà ici — `_stop_useless_work` met un rôle en pause par une directive que le
  CEO lit, et `_create_tasks` refuse de mettre en file un rôle en pause. Social
  l'avait, outreach non.
  **Le déclencheur est mesuré, pas déclaré** : trois tours réels qui n'ont trouvé
  personne, pas une configuration vide. Ma première version se déclenchait dès
  qu'aucune source n'était configurée et arrêtait donc outreach au premier tick
  d'une entreprise neuve — un rôle stoppé avant d'avoir eu sa chance, ce qui est
  une autre erreur et une pire. `tests/test_tasks.py` l'a attrapée.

- **Fixed : le site de l'entreprise était invisible pour le produit censé
  l'entretenir.** Rétro-ingénierie des journaux d'exécution NanoCorp
  (`docs/reverse-engineering/nanocorp.md`) : leur worker travaille sur le dépôt —
  il lit de vrais fichiers, les édite, construit, pousse, vérifie la production.
  Corparius dérivait la page d'un fichier de configuration. **Mesuré sur
  l'installation du propriétaire :** `companies/vigil/site/` contenait six pages
  HTML écrites à la main, une feuille de style, une fonction serverless,
  `robots.txt` et `sitemap.xml`, versionnées dans le dépôt privé de l'entreprise
  — et corparius ne voyait rien. `build_sales_site` régénérait une page unique à
  partir de quatre champs de `company.yaml` à chaque tour de l'agent design et
  annonçait « Sales site built » ; `deploy_site` publiait *celle-là*. L'exploitant
  demandait pourquoi son site restait mauvais : le produit n'avait jamais touché
  son site. `paths.owned_site()` le trouve maintenant, en honorant la clé
  `publish` d'un `netlify.toml` ; le générateur refuse de l'écraser et dit ce
  qu'il contient ; la console prévisualise et publie le même dossier.
- **Added : un déploiement est vérifié, une fois.** `corparius/sitecheck.py`,
  copié de la compétence `vercel-deploy-verify` de NanoCorp : attente bornée
  (`CORP_DEPLOY_VERIFY_WAIT`, plafond 180 s), **une** requête, un verdict parmi
  `fresh` / `stale` / `unreachable` / `unverified`, et une phrase qui dit d'où il
  vient. Jamais de reprise. Ce que ça vaut est dans leur journal : un push réussi,
  une route déployée, et la production répondant « la variable est absente » —
  sans le contrôle, cette tâche finissait en succès. Corparius annonçait `Site
  published` sur la parole du fournisseur et n'allait jamais chercher l'adresse.
  Le marqueur est le `<title>`, pas un hachage des octets : une page générée porte
  un horodatage de build, donc chaque contrôle lirait « périmé ».
- **Added : un site ne part pas en ligne avec des marqueurs à remplacer.**
  **Mesuré :** publier Vigil aurait mis `REMPLACER@TON-DOMAINE.fr` sur la ligne
  de contact de la page d'accueil, deux fois. `deploy_site` refuse et nomme les
  fichiers ; le doctor le dit avant qu'on essaie. Deuxième famille : un
  `robots.txt` ou un `sitemap.xml` qui pointe un crawler vers un hôte autre que
  `site.url` — c'est le raisonnement que `sitegen` applique déjà au lien
  canonique. La première version de ce détecteur signalait
  `www.sitemaps.org`, l'espace de noms XML présent dans tout sitemap ; il ne lit
  plus que les `<loc>` et la directive `Sitemap:`. Trouvé en l'exécutant sur un
  vrai site, pas en le relisant.

- **Fixed : `local` était le premier fournisseur de publication par défaut, et il
  est toujours disponible.** Donc il gagnait toujours, et netlify, s3 et ssh ne
  tournaient jamais. Un exploitant qui posait `NETLIFY_AUTH_TOKEN` et
  `NETLIFY_SITE_ID` obtenait une copie locale et une ligne de journal annonçant
  une publication ; **mesuré sur une vraie installation, un site est resté non
  publié pendant des jours pendant que chaque déploiement se déclarait réussi.**
  Le défaut est maintenant `netlify,s3,ssh,local` — la règle du routeur LLM,
  appliquée à la publication : local termine la chaîne, il ne la commence pas. Un
  fournisseur non configuré est ignoré, donc une installation sans aucune clé
  retombe sur `local` exactement comme avant. Le signe que le défaut était faux
  était dans les tests : chacun de ceux qui voulaient une vraie publication
  réécrivait l'ordre à la main.
- **Changed : une proposition n'est plus comptée comme une décision de
  l'exploitant.** La console additionnait chaque proposition dans sa pastille
  « à faire » et intitulait la colonne « à arbitrer ». Un agent qui remarquait
  quelque chose de mineur — « la landing affiche 12 inscrits en accès anticipé et
  rien ne l'étaye » — se lisait donc comme l'entreprise s'arrêtant pour demander
  la permission sur une broutille. C'est le CEO qui arbitre les propositions,
  c'est à ça qu'il sert. Elles ne comptent que si personne d'autre ne les
  regardera : un CEO désactivé, ou mis en pause par l'exploitant.
- **Added : `always: true` dans l'en-tête d'une compétence.** Le doctor traite
  l'absence d'`allowed-tools` comme un oubli, et c'en est un la plupart du temps
  — mais pas quand la règle commence par « s'applique à toute sortie de tout
  agent, sans exception ». Sans moyen de le déclarer, le seul moyen de faire
  taire l'avertissement était de restreindre la règle, c'est-à-dire l'inverse de
  ce qu'elle demande ; et un avertissement inactionnable est un avertissement
  qu'on apprend à ignorer. La déclaration ne change rien au comportement, elle
  change qui se fait dire qu'il s'est trompé — et **le prix reste annoncé**,
  parce que déclarer ne rend pas gratuit.
- **Fixed : le CLI Claude recevait le prompt sur la ligne de commande, et
  Windows la coupe à 8191 caractères.** **Mesuré** sur le CLI installé
  (2.1.220) : un prompt de 8000 caractères atteint le modèle, 8100 échoue avec
  `claude CLI exited 1: La ligne de commande est trop longue`. Ce n'est pas un
  cas limite — une entreprise qui a des documents et des skills le dépasse au
  premier tour de l'agent design. Et l'échec arrivait comme une erreur de
  fournisseur ordinaire, donc le routeur faisait ce qu'il fait d'un fournisseur
  en panne : il passait à l'étape suivante, un modèle gratuit incapable de
  produire du JSON. `write_site_content` répondait « no JSON object in the
  reply », le site n'était jamais réécrit, et **l'exploitant avait pin Opus sur
  le design : Opus n'a jamais tourné une seule fois.** Rien dans le journal ne
  racontait ça. Le prompt passe maintenant sur stdin — **mesuré : 25 268
  caractères, rc 0** — et il ne reste que les drapeaux sur la ligne de commande.
  Le prompt système y reste tant qu'il tient ; sinon il est replié dans le
  prompt plutôt que perdu, parce qu'un appel qui perd en silence les règles de
  la maison répond avec assurance dans la mauvaise voix.
- **Fixed : une tâche que rien ne peut exécuter était fermée « done ».** Le
  registre `ROLE_TOOL` rend une tâche approuvée exécutable, et **un seul des
  deux chemins d'approbation l'atteignait** : le `review_proposals` du CEO
  attachait l'outil, le bouton de la console non — et c'est celui que
  l'exploitant utilise. **Mesuré dans une vraie base : 24 tâches d'un même rôle
  sans outil, dont 22 fermées avec la note « done (no tool mapped) »**, sans que
  rien n'ait eu lieu. Comme rien n'avait eu lieu, la condition qui avait produit
  la tâche était toujours là au tour suivant : six propositions
  quasi-identiques sur un seul badge d'une seule page, chacune approuvée,
  chacune fermée, rien de fait. Un tableau vert et un site inchangé.
  Trois choses corrigées : les deux bouts du fil passent par la même fonction
  (`tools.executable_fields`) ; une tâche que rien ne peut exécuter est
  **retenue** avec un avis qui dit où aller, au lieu d'être fermée ; et
  l'agent qui propose **nomme le rôle qui doit faire le travail** — support
  possédait « retirer le badge non vérifié de la landing » alors que son outil
  rédige une réponse au support. `ROLE_TOOL["design"]` pointe désormais sur
  `write_site_content` : `build_sales_site` régénère la page à partir d'un texte
  que personne n'a changé et annonce une réussite, ce qui est le même mensonge
  par un autre chemin.
- **Fixed : un refus du roster annoncé comme un changement.** « Roster changed —
  left off, you stood them down: social », tour après tour, alors que le roster
  était exactement tel que l'exploitant l'avait laissé.
- **Fixed : le doctor ouvrait sept connexions à la base et n'en fermait que
  trois.** Sept vérifications ouvraient chacune la leur ; quatre fuitaient à
  chaque appel — et cette fonction tourne à chaque démarrage du lanceur et est
  servie en HTTP. Rien n'échouait : la fuite est restée invisible jusqu'à ce
  qu'elle fasse expirer le sondage de la console elle-même sur un runner
  Windows, en intégration continue, quelques jours après la publication.
  **Mesuré : une connexion par appel maintenant, ouverte et fermée au même
  endroit.** La console prête la sienne — elle en garde une pour toute sa vie et
  n'a rien à faire d'en ouvrir une seconde sur le même fichier pour répondre à
  un sondage — et une connexion prêtée n'est jamais refermée sous son
  propriétaire. Le `store` est un argument **requis, sans valeur par défaut** :
  il en avait une, et deux tests appelaient alors ces vérifications sans le
  passer et recevaient un « ok, rien à signaler » enjoué à la place de la mesure
  périmée et du schéma venu du futur qu'ils venaient d'écrire. Requis, ce
  silence devient une erreur. Trois tests le tiennent : le compte des
  connexions, le fait qu'une connexion prêtée survive à l'appel, et l'absence de
  valeur par défaut.
- **Added : une règle, appliquée à chaque registre — vérifier les deux bouts du
  fil.** Le défaut a une forme et deux faces, et il a coûté neuf bugs à ce projet.
  *Produit et jamais consommé* : `usage.cost`, les timings d'Ollama,
  `icp.channels`, `architecture.input_modalities`, la vraie longueur d'un document.
  *Atteignable et jamais atteint* : `documents.images()` sans appelant,
  `ask_operator` et `set_roster` sans chemin, `_CEO_SCHEMA["model"]` décrit au
  modèle comme une chaîne. Aucun n'échouait, parce que rien ne regardait les deux
  bouts à la fois. `tests/test_registries.py` l'exige désormais pour `TOOLS`,
  `ROSTER`, `ROLE_TOOL`, le registre de réglages, les fournisseurs, les migrations
  et les correctifs d'inbox — sans jugement, ce qui est tout l'intérêt.
  **Elle a trouvé deux vrais trous au premier passage** : `CORP_LEAD_SEARCH_URL` et
  `CORP_REPO_NAME_PREFIX` étaient lus par le code, absents du registre et de toute
  documentation — et `find_targets` disait à l'exploitant de régler le premier
  « dans Réglages, Prospects », où aucun champ ne l'accueillait. Les deux sont
  réglables maintenant.
  Elle a aussi produit trois fausses alertes, dues à mon détecteur et non au code :
  sa regex n'acceptait que les clés `CORP_` sur une seule ligne, donc
  `CORP_HITL_TOOLS`, `GITLAB_TOKEN` et `NETLIFY_SITE_ID` passaient pour non lus. Un
  détecteur qui crie au loup est un détecteur qu'on finit par ignorer : corrigé,
  pas contourné.
- **Fixed : un champ `dict` était décrit à un modèle comme une chaîne.**
  `render_hint` n'avait aucun rendu pour `dict` et retombait sur `string`, donc le
  CEO recevait `"model": string` là où le code attend `{"design": "..."}`. Demandé
  en console de mettre le design sur `claudecode:opus`, il a répondu « J'approuve
  l'utilisation de Claudecode Opus pour le design » et n'a **rien écrit** — la
  promesse vide, arrivant par le champ censé y mettre fin. `cadence` ne survivait
  que parce que sa prose montrait un exemple par chance. La forme vit désormais
  **sur le champ** (`shape`), que `render_hint` lit : un paragraphe s'oublie, un
  attribut non.
- **Fixed : huit sous-processus décodaient l'UTF-8 avec l'encodage local.**
  `subprocess.run(text=True)` sans `encoding` utilise cp1252 sous Windows, et le CLI
  Claude émet de l'UTF-8 — vérifié sur les octets, `0xC3 0xB9` pour « ù ». Chaque
  accent d'une réponse du palier `hard` revenait donc abîmé et était **stocké**
  ainsi (`Facturez Ã  partir du jour oÃ¹`). Corrigé dans `llm.py`, `claudecli.py`,
  `companyrepo.py` et `deploy.py`.
- **Fixed : « Nothing usable drafted » ne disait pas laquelle des deux choses
  s'était produite.** `structured.ask` renvoie les valeurs par défaut du schéma
  quand aucune réponse ne valide, donc un outil qui ne lit que `.data` ne peut pas
  distinguer « le modèle n'avait rien à ajouter » de « aucun fournisseur n'a
  répondu ». Mesuré sur une vraie exécution : groq et cerebras en 429, le harnais
  retombe, et `write_site_content` annonce n'avoir rien trouvé à écrire. L'exploitant
  y a lu un mauvais générateur de site après 365 026 jetons. Le harnais portait
  `ok`, `fell_back`, `attempts`, `source` et `errors` depuis toujours : quatrième
  appelant à n'en lire qu'un champ.
- **Fixed : `send_outreach` rédigeait sans destinataire.** Sans lead, un appel de
  modèle toutes les trois heures pour écrire à personne — le gaspillage exact que
  `draft_support_reply` avait déjà cessé de payer sur une entreprise sans boîte
  mail, jamais corrigé sur la prospection juste à côté. Et le brouillon obtenu
  était adressé à `[Nom]`, prêt à partir tel quel. `skip_when` sans destinataire,
  et un brouillon contenant un blanc n'est plus envoyé : l'invite l'interdisait
  déjà, mais une invite est une demande.
- **Fixed : `set_roster` annonçait un changement qui n'existait pas.** « Roster
  changed — on: coder » à chaque tour, pour un rôle jamais mis en veille. Ma
  régression du jour même.
- **Fixed : une notice disait de lancer une commande de terminal.** « Run
  `corparius preflight` », dans une console web, en anglais, sur une page qui peut
  être en français — alors que le bouton existe depuis toujours. La note ne porte
  plus que le fait mesuré ; la console dit quoi presser, dans la langue de
  l'exploitant, avec les mots du contrôle qu'elle va presser — et elle le presse.

## 0.3.3 — construit et jamais atteint

Onze entrées, un seul fil. Une capacité annoncée en **sept endroits** que rien
n'implémentait : `documents.images()` n'avait aucun appelant, aucun signal de
capacité vision n'existait, et une image déposée était listée, nommée, puis jetée.
Deux de ces sept phrases avaient été écrites le jour de la 0.3.2.

En la construisant, la même forme est réapparue trois fois de plus. La capacité
elle-même n'était atteignable par aucun réglage. Deux outils étaient dans `TOOLS`
sans qu'aucun chemin ne mène à eux, dont un que le CHANGELOG affirmait pourtant
joignable par le CEO. Et le diagnostic ne voyait pas le levier ajouté la veille.

**Mesuré, pas cru** : sur les trois modèles gratuits que le catalogue annonce
capables de lire une image, **un la lit, un l'annonce et n'y arrive pas, un ne
répond rien**. Le troisième reste `NULL` — jamais demandé n'est pas « ne voit
pas ». C'est la leçon de `cerebras:gpt-oss-120b` avec `structured_outputs`, sur une
deuxième capacité.

Chacun de ces trous est désormais gardé par un test qui échoue si la promesse
repart sans son chemin.

- **Fixed : deux outils que rien ne pouvait appeler, et le garde-fou de la
  classe.** Trouvés en balayant pour le défaut qui avait produit le bug des
  images : `ask_operator` et `set_roster` étaient dans `TOOLS`, sur aucun playbook,
  dans aucune file, nommés par aucun autre module. Le CHANGELOG affirmait pourtant
  que « `ask_operator` is a mappable tool so the CEO can queue "ask about X" » —
  or `ROLE_TOOL` associe un **rôle** à son outil par défaut, `ask_operator`
  n'appartient à aucun rôle, et `create_tasks` ne peut poser que six triplets
  codés en dur. La docstring et le CHANGELOG se trompaient tous les deux.
  L'un des deux l'était par conception : son invite est écrite pour une tâche
  (« ce que *cette tâche* ne peut pas faire sans »), comme `deploy_site`. Ces deux
  outils le **déclarent** maintenant (`by_task_only`), parce que « sur aucun
  playbook » est aussi ce à quoi ressemble un outil oublié, et rien ne pouvait les
  distinguer. L'autre l'était par omission : « la décision la plus CEO qui
  existe », d'après sa propre docstring, et aucun CEO ne pouvait la prendre.
  `tests/test_tool_reach.py` exige désormais que **chaque outil ait un chemin** —
  playbook, file du CEO, outil par défaut d'un rôle, ou tâche déclarée. Vérifié non
  vacant : sans le drapeau, les deux ressortent.
- **Fixed : `set_roster` aurait défait les mises en veille de l'exploitant.**
  Le brancher tel quel sur le playbook du CEO aurait fait effacer, deux fois par
  jour, les pauses posées par l'exploitant lui-même — l'échec exact que les
  directives permanentes avaient été introduites pour finir, arrivant par l'outil
  censé les respecter. Il ne peut plus lever que les mises en veille qu'il a
  écrites, la distinction existait déjà dans la donnée (`note`), et un rôle laissé
  éteint est **dit** au lieu d'être rapporté comme rallumé. Son invite demande
  aussi de ne nommer que ce qui change, et rien du tout si le roster est bon :
  nommer tous les rôles à chaque tour est la façon dont une décision devient du
  bruit.
- **Fixed : le doctor ne voyait pas les modèles épinglés par rôle.** Le pin
  ajouté hier vit dans une directive par entreprise, et toutes les vérifications
  lisent les trois réglages de palier — un pin vers un fournisseur sans clé faisait
  donc retomber **tous les tours de ce rôle** sur local, pendant que le diagnostic
  annonçait que tout allait bien. Le levier avait été ajouté sans le diagnostic qui
  existe précisément pour ça. Il lit les directives et les clés ; il ne sonde rien.
- **Added : la console sert le texte entier d'un document.** `MAX_CHARS` existe
  pour qu'une présentation de trente pages n'avale pas un tour d'agent. Il n'a
  rien à faire entre l'exploitant et un fichier qui est à lui — or la carte
  réutilisait le texte tronqué de l'agent, donc relire son propre brief de 12 000
  caractères en montrait 4 000 et renvoyait ouvrir le fichier à la main. Honnête,
  la pastille le disait, et quand même la mauvaise réponse : la surface de lecture
  et le budget d'invite sont deux questions différentes. Le bouton n'apparaît que
  si quelque chose a été coupé et disparaît une fois servi. Prouvé dans un vrai
  navigateur : 4 000 puis 20 999 caractères, et le fichier court ne le propose pas.
- **Mesuré et laissé tel quel : `documents.context()` ne met rien en cache.** Il
  est rappelé à chaque tour et ré-extrait tout le dossier, ce qui sentait le
  problème. Mesuré sur un dossier réaliste — une présentation de 40 diapos, un
  cahier des charges, un tarif de 2 000 lignes, six notes : **10 ms par appel,
  0,24 s pour une journée simulée de 24 tours.** Un cache par `(chemin, mtime)` ne
  rachèterait rien et ajouterait un état à invalider. Noté pour que ça cesse
  d'être un soupçon.

- **Added : un modèle par rôle, parce que la capacité images n'était atteignable
  par personne.** Trois paliers sont réglables et neuf rôles sur dix prennent le
  leur dans l'un d'eux : donner à l'agent de design un modèle qui lit une image
  demandait de déplacer tout le palier normal. **Mesuré sur une configuration
  réelle : 535 tok/s vers 49** pour le CEO, la prospection, le support *et* le
  design, afin de donner la vue à un seul d'entre eux. La seule autre porte était
  d'éditer `agents.py`, ce qui n'est pas de la configuration. Une capacité livrée
  que les réglages ne savent pas atteindre.
  Un rôle s'épingle désormais dans la conversation avec le CEO, exactement comme
  la cadence et la mise en veille : une directive par entreprise, relue à chaque
  tour, effet au tour suivant. Le spec du roster est **copié et non muté** — y
  écrire épinglerait le modèle pour toutes les entreprises du processus, et la
  console en fait tourner plusieurs.
  **Le préfixe doit être écrit**, et le refus est nommé. `llm._split` rabat exprès
  un préfixe inconnu sur `local` pour que les étiquettes Ollama fonctionnent dans
  les paliers, ce qui rend `opnerouter:typo` indiscernable de `gemma4:e4b` : une
  validation bâtie dessus aurait accepté la faute de frappe et envoyé tous les
  tours de ce rôle vers Ollama — une journée lente, pas une erreur visible. Trouvé
  parce que le test l'a attrapé, pas en relisant le code.
- **Added : `CORP_IMAGE_MAX_PER_CALL`, et zéro veut dire jamais.** La capacité
  ci-dessous fait sortir un fichier de l'exploitant vers un tiers, et il n'avait
  aucun moyen de le refuser. Le texte d'un document est extrait sur sa machine —
  le module s'en vante — mais une image doit en sortir pour être lue, et une
  capture d'écran peut contenir les données d'un client. Le seul refus disponible
  était `CORP_CLOUD_ENABLED=false`, qui coupe aussi tout le texte : rien ne
  permettait de garder le texte dans le cloud en refusant les images, alors que
  l'image est la plus sensible des deux. C'est donc un contrôle de confidentialité,
  pas un bouton de réglage fin — et c'est pour ça que c'est un réglage et non une
  constante, contrairement au plafond d'octets qui reste une décision de forme
  comme `MAX_UPLOAD`. À zéro, les fichiers ne sont ni lus ni encodés, et le journal
  le dit une fois par tour au lieu de laisser croire qu'il n'y avait rien à
  envoyer.
- **Fixed : `sees_images` ne peut plus être posé sur un outil qui n'appelle aucun
  modèle.** Le drapeau n'est lu que sur le chemin de rédaction, donc le mettre sur
  un outil sans `needs_draft` ne fait rien — en silence. `produce_mockup` est le
  piège : c'est le travail visuel évident de l'agent de design et il ne fait aucun
  appel de modèle, il aurait donc eu l'air branché sans l'être jamais. Un drapeau
  mort se lit comme une fonctionnalité par la personne suivante qui le cherche.
- **Fixed : une image déposée est enfin envoyée à un modèle. Pendant deux
  versions, le produit disait qu'elle l'était.** `documents.images()` n'avait
  **aucun appelant**, aucun signal de capacité vision n'existait, et rien dans
  `llm.py`, `agents.py` ni `structured.py` ne pouvait envoyer une image. Elle
  était listée, nommée, puis jetée — pendant que sept endroits affirmaient
  qu'elle était « proposée aux modèles qui acceptent les images » : le module, la
  console dans les deux langues, `docs/documents.md` et le README. Deux de ces
  sept avaient été écrits le jour même de la 0.3.2.
  **Et le motif habituel était là, pour la huitième fois** : la donnée qui
  permettait de tenir la promesse arrivait déjà et était jetée.
  `modelinfo.fetch()` lisait le catalogue et ne gardait que le contexte, le
  raisonnement et le JSON — d'une réponse qui porte aussi
  `architecture.input_modalities`. Mesuré sur le catalogue réel : **180 entrées
  sur 337 déclarent l'image en entrée, et 5 seulement en palier gratuit**, ce qui
  compte pour un projet qui route vers le gratuit.
  Trois conditions gouvernent désormais l'envoi, et il faut les trois : l'outil
  l'a demandée (`Tool(sees_images=True)` — `draft_design_brief` et
  `scan_competitors`, pas le rapprochement Stripe), l'entreprise en a une, et le
  modèle sait la lire — **mesuré d'abord, déclaré ensuite**. `corparius preflight`
  envoie une vraie image de test, un carré bleu sur jaune de 79 octets généré en
  code, et demande les deux couleurs dans l'ordre : une seule serait devinable
  par un modèle qui ne voit rien, et l'invite ne nomme jamais la réponse qu'elle
  attend. Le verdict va dans `model_probes.vision_ok` (**schéma 16**), où `NULL`
  est un troisième état — jamais demandé, ce qui n'est pas « ne voit pas » — et où
  une mesure ultérieure qui n'a pas posé la question n'efface pas un verdict
  acquis.
  **Et la sonde a immédiatement payé.** Mesurée sur une vraie clé, sur les trois
  modèles gratuits que le catalogue annonce capables de lire une image : **un la
  lit, un l'annonce et n'y arrive pas, un ne répond rien** — ce dernier restant
  `NULL`, parce qu'une absence de réponse n'est pas un verdict. Un modèle gratuit
  sur trois mentait sur sa propre fiche, et le troisième état a servi dès la
  première mesure.
  **`content` reste une chaîne.** `_flatten`, le Mock et le `system` d'Anthropic
  la joignent tous : glisser des blocs façon OpenAI dans `messages` aurait cassé
  quatre chemins d'un coup et en silence. Les images voyagent donc dans un
  argument à part, que chaque fournisseur dépense dans son dialecte — `image_url`
  en URI `data:`, le bloc `source` d'Anthropic, le tableau `images` d'Ollama — et
  celui qui ne sait pas le déclare (`accepts_images = False`) plutôt que de la
  laisser tomber. Le mot-clé est **absent** quand il n'y a pas d'image, pas passé
  vide, pour qu'un fournisseur de greffon écrit avant ce changement continue de
  fonctionner. `base64` est dans la bibliothèque standard : toujours deux
  dépendances.
  Borné et dit : deux images par appel, 3 Mio chacune, et ce qui dépasse est nommé
  avec sa taille réelle. Prouvé hors ligne de bout en bout — le brief de design
  reçoit `[saw 1 image(s): competitor-page.png]`, et aucun outil qui ne l'a pas
  demandée n'en reçoit.
  Enfin **le test qui manquait** : aucune surface ne peut dire qu'un modèle voit
  une image tant que le chemin n'existe pas — `documents.images()` doit avoir un
  appelant, le contrat des fournisseurs doit porter les images, un outil doit
  pouvoir en demander. Vérifié non vacant : sur le code d'avant, les quatre
  conditions étaient fausses.
- **Fixed : le README décrivait une version antérieure du produit.** Un audit
  ligne à ligne a trouvé : toute la capacité documents absente — pas de section,
  pas de module dans le plan, pas de `docs/documents.md`, rien dans
  `docs/console.md` — `corparius preflight` jamais nommé alors qu'il est le titre
  d'une version, **13 des 28 commandes CLI** manquantes, « 12 free tiers » imprimé
  trois fois contre un registre qui en tient 14, deux préfixes de cible
  indocumentés (`alibaba:`, `openai:`), le défaut HITL annonçant deux outils là où
  le code en nomme trois, cinq sections absentes du sommaire, `versionnement.md`
  introuvable depuis l'index, et l'affirmation que les clés enregistrées depuis la
  console dorment en clair — écrite après que `corparius secrets on` existe pour
  les chiffrer.
  Rien de tout cela ne pouvait échouer : la dérive de documentation est invisible
  par construction. **Dix tests la rendent visible**, chacun comparant le README au
  code qu'il décrit dans le sens qui pourrit — les docs dans les deux directions,
  les commandes lues sur le parser, les préfixes lus sur le registre, le compte de
  fournisseurs, les défauts HITL, les ancres du sommaire et les sections qu'il
  omet, les onglets de la console, et la paire de captures clair/sombre. Vérifiés
  non vacants : chacun tire sur le README tel qu'il était.
- **Added : `docs/documents.md`, et la capture d'écran en deux thèmes.** La page
  qui manquait au seul sous-système qui n'en avait pas. La capture datait d'avant
  l'onglet ; elle est reprise sur la console réelle après une journée simulée, en
  clair et en sombre depuis une seule session — les deux images ne diffèrent que
  par la couleur, jamais par les chiffres — et GitHub choisit selon le thème du
  lecteur.

## 0.3.2 — voir ce que l'entreprise sait, et ce qu'un agent en lit vraiment

Un dossier de documents qui fonctionne et que rien n'affiche est un dossier dont
personne ne connaît l'état. Mesuré sur neuf fichiers réels : **quatre atteignent
les agents, trois specs parfaitement lisibles sont hors du budget d'invite** et
rien ne les lit — un état que le produit n'avait aucun moyen de dire. La console
a maintenant son onglet, on y dépose au glisser et on en retire.

Et deux leçons dont le prix était déjà payé ailleurs : **33 clés de traduction**
que le test de parité exemptait en silence, dont neuf antérieures à cette
version ; et une suite de tests qui écrivait dans le dépôt qu'elle teste, faute
d'un réglage qui a été faux dans les deux directions successives.

- **Added : on peut retirer un document depuis la console.** Une zone de dépôt
  sans retour est un dossier qui ne fait que grossir, et l'exploitant qui avait
  déposé le tarif du mauvais trimestre devait aller trouver le répertoire à la
  main. Le bouton est sur chaque ligne, y compris celles qu'aucun extracteur ne
  sait lire — un PDF scanné est justement la ligne qu'on veut voir partir, et
  c'est la seule qui n'a pas de dépli où cacher un bouton. Déplacé de côté, pas
  effacé : les fichiers de l'exploitant ne sont pas à nous, c'est la réponse que
  reçoit déjà une entreprise supprimée, et la console dit où le fichier est parti.
  Pas de confirmation à retaper, contrairement à la suppression d'une entreprise :
  cette barrière existe parce qu'une entreprise est le tout, alors qu'un document
  est un fichier qui reste sur le disque après coup. Le chemin arrive dans un
  corps de requête, donc il est résolu et comparé au dossier plutôt que cru sur
  parole pour être venu de notre page une seconde plus tôt.
- **Fixed : un dossier caché dans `documents/` était lu.** Le parcours ne testait
  que `p.name`, c'est-à-dire le nom du fichier — pas les segments au-dessus. Un
  `.git` ou un `.obsidian` posé là voyait donc tout son contenu partir dans les
  invites, et le `.trash` du retrait ci-dessus aurait renvoyé dans l'invite le
  document que l'exploitant venait précisément d'en sortir.
- **Added : un onglet « Documents », et on y dépose ses fichiers au glisser.**
  La carte a son onglet, et au-dessus une zone de dépôt. Un fichier part seul
  dans sa requête, en base64 dans le corps JSON que la console analyse déjà :
  pas de parseur multipart, donc toujours deux dépendances. Un fichier par
  requête et non un lot, parce qu'un lot rendrait un seul verdict pour dix
  fichiers et que la ligne de résultat par fichier serait alors inventée par la
  page. Un refus n'est pas une requête ratée — `ok` qualifie la requête, et
  demander à ranger un .zip est une demande parfaitement formée : la réponse est
  `stored: false`, avec lequel de vos fichiers et pourquoi. Le nom est réduit à
  son dernier segment avant toute chose, barres obliques inverses repliées
  d'abord puisqu'elles sont légales dans un nom POSIX ; un fichier caché est
  refusé plutôt qu'écrit, parce que `load` l'ignorerait ensuite pour toujours.
  Le plafond de corps devient un réglage par route : un PDF de 6 Mo ne passe pas
  sous le 1 Mio global, et relever ce plafond pour tout le monde aurait élargi
  du même geste tous les autres points d'API. La page annonce les formats
  acceptés et la taille limite avant qu'on glisse quoi que ce soit, en les
  tenant du serveur qui les décide.
- **Fixed : le préfixe `doc.` appartenait au docteur.** Réutilisé pour la carte
  des documents, il a fait déclarer `doc.title` et `doc.desc` deux fois : dans un
  littéral JS la dernière gagne en silence, si bien que la carte des documents
  s'intitulait « Diagnostics » et portait la description du docteur. Le test de
  parité compare les deux tables entre elles et n'y voyait rien — le doublon
  était dans les deux langues. Seule l'ouverture de la page dans un navigateur
  l'a trouvé, ce qui n'est pas un test : il y en a un maintenant.
- **Fixed : le bouton d'ajout de fichier était celui du navigateur.** Widget
  natif gris et son « Aucun fichier choisi », au milieu d'une console qui a sa
  propre langue visuelle. L'étiquette porte désormais l'apparence et entre dans
  la même règle CSS que `button`, plutôt que d'en inventer une seconde ; le champ
  garde le comportement, masqué à l'œil et jamais au clavier, avec l'anneau de
  focus reporté sur l'étiquette — `display:none` l'aurait sorti de l'ordre de
  tabulation et rendu l'onglet utilisable à la souris seulement.
- **Fixed : la suite de tests écrivait dans le dépôt.** `CORP_HOME` était
  *supprimé* par la fixture d'hermétisme, ce qui écartait bien les tests d'une
  installation réelle mais les pointait sur le checkout, qui est writable. Deux
  fixtures y lançaient un vrai tour d'orchestrateur sur `example` :
  `companies/example/company.yaml` revenait reformaté, commentaires et bloc
  `site:` disparus, avec ses quatre documents écrits réécrits. Et les tests qui
  appellent les outils avec les slugs `t`, `d` et `m` laissaient `companies/t`,
  `companies/d` et `companies/m` dans l'arbre de travail — gitignorés, donc
  invisibles pour git, donc jamais remarqués. Tant que `companies/` se résolvait
  à l'import, la même écriture partait dans l'installation réelle du
  développeur, où rien ne l'aurait jamais montrée : le réglage était faux dans
  les deux directions.
  Chaque test reçoit désormais un home privé **vide** ; les rares fixtures qui
  ont besoin de l'entreprise livrée la copient elles-mêmes, ce qui est aussi la
  forme honnête — un test qui fait tourner une entreprise devrait dire laquelle.
  Copier `companies/` dans chaque home fermait le même trou et a été mesuré à
  768 ms par test, trois fois la durée de toute la suite. Un garde-fou de session
  compare l'empreinte de **tout** le dossier à la fin du run, pas seulement du
  fichier suivi : ne regarder qu'`example` est précisément ce qui a laissé `d`,
  `m` et `t` s'accumuler. Il nomme le fichier et le remède.
- **Fixed : deux tests sur les compétences livrées se sont mis à sauter.** Ils
  lisaient `companies_dir()` et sautaient quand il était vide, si bien qu'au
  moment où la suite a cessé de pointer là le test s'est tu au lieu d'échouer.
  Une affirmation sur ce qui est livré doit lire ce qui est livré : ils prennent
  la source, plus le home d'exécution, et le saut a disparu.
- **Fixed : `companies/` avait deux sources.** `company.ROOT` était un
  instantané pris à l'import et `paths.companies_dir()` se résout à chaque
  appel ; les deux ne s'accordaient qu'aussi longtemps que `CORP_HOME` était posé
  avant l'import, et la console avait déjà un point d'API qui gardait un slug
  contre l'un en construisant un chemin depuis l'autre. Troisième module à
  apprendre la leçon après `backup.py` et `cli._store()` : l'instantané d'un
  réglage en couches est l'instantané de la mauvaise couche. Une seule source
  désormais, et les tests déplacent le dossier avec le levier qu'un exploitant
  utilise.
- **Fixed : deux documents de même nom étaient une seule chose dans l'invite.**
  Le bloc les nommait par leur nom de fichier, donc un `design-brief.md` déposé
  et un `design-brief.md` écrit par l'agent de design donnaient deux en-têtes
  identiques dans la même invite, sans rien pour les distinguer. C'est le chemin
  relatif qui les nomme maintenant, ce qui apprend au modèle lequel des deux
  l'entreprise a écrit elle-même, gratuitement.
- **Added : la console montre les documents, et dit lesquels un agent lit
  vraiment.** Le dossier par entreprise fonctionnait et rien ne l'affichait :
  le brief que l'agent de design venait d'écrire était sur le disque, était dans
  l'invite du tour suivant, et restait illisible pour la personne qui le paie —
  la même forme que les quatre livrables coupés à 120 caractères, un étage plus
  haut. Une carte dans « Opérations » liste les deux provenances, celle que vous
  déposez et celle que l'entreprise écrit, avec le texte extrait derrière un
  dépli. Le nombre qui compte n'est pas le nombre de fichiers : `context`
  s'arrête au budget d'invite, donc une entreprise peut en avoir douze au
  dossier et n'en donner que deux à ses agents. Mesuré sur neuf documents
  réels : **quatre atteignent les agents, trois specs parfaitement lisibles
  sont hors budget** et rien ne les lit. Elles portent désormais une pastille
  qui le dit, au lieu de figurer dans la même liste que celles qui passent. La
  sélection au budget est devenue une seule boucle partagée par `context` et
  `inventory` : écrite deux fois, elle aurait dérivé, et une console qui se
  porte garante d'un document qu'aucun agent n'a jamais vu coûte plus cher que
  le silence qu'elle remplace. L'état d'un document voyage comme un code et non
  comme une phrase, parce que la console parle deux langues et que la phrase,
  elle, part dans une invite en anglais. La vraie longueur voyage comme un
  nombre : elle n'existait que dans cette phrase, si bien qu'un lecteur du
  payload voyait 4 000 caractères sans pouvoir apprendre que le document en
  faisait trois fois plus. Le point d'API n'est pas sur le sondage de 5 s — il
  ouvre et extrait chaque fichier qu'il liste.
- **Fixed : le test de parité en/fr ne regardait pas les clés qu'il comptait le
  plus.** Sa regex n'acceptait que deux segments, ce qui exemptait en silence
  toutes les clés que la console atteint en fabriquant leur nom — `dft.state.*`,
  `ib.fix.*`, `prov.pf.*`, `risk.write_local`, `col.in_progress`. Trente-trois
  clés, dont neuf antérieures à ce changement, n'avaient jamais été vérifiées
  par le seul test qui prétend garantir qu'une console française ne contient pas
  une phrase anglaise. Aucune ne manquait ; c'est la chance, pas le test.
- **Added : un dossier de documents par entreprise, lu *et* écrit.** Déposez un
  PDF, un .docx, un .pptx, un .xlsx, un CSV, une note ou une capture dans
  `companies/<slug>/documents/` et le texte devient du contexte pour les agents,
  sans nouvelle dépendance. Ce qui ne peut pas être lu honnêtement est nommé
  plutôt qu'inventé : un PDF scanné répond « aucune couche de texte », une image
  est proposée aux modèles qui acceptent les images. Et quatre outils qui
  produisaient un vrai livrable pour n'en garder que 120 caractères de journal
  l'écrivent maintenant dans `written/` — le brief de design mesuré passe de 120
  à 512 caractères et revient dans l'invite au tour suivant.
- **Fixed : une proposition d'agent dit enfin ce qu'elle propose.** Le titre
  était fabriqué à partir du rôle — « Idea from support », indéfiniment. Quatre
  lignes identiques dans une colonne, que ni l'exploitant ni le CEO ne pouvaient
  distinguer. L'agent rédige désormais l'intitulé et la raison ; sans intitulé,
  rien n'est déposé, parce qu'un backlog vide se lit et qu'un backlog de
  gabarits non. La raison va dans une colonne à elle (schéma 15) : `note`
  portait deux métiers et chaque changement d'état l'écrasait, si bien que le
  pourquoi mourait au moment précis où quelqu'un agissait sur la tâche.
- **Fixed : la colonne « Terminées » ne pousse plus la page à l'infini.** Elle
  s'ouvre repliée sur six lignes, les plus récentes d'abord, avec un « voir
  les N autres ». Le rendu coupait à trente sans le dire, donc l'en-tête
  annonçait 36 au-dessus d'une colonne qui en montrait 30.

## 0.3.1 — prouver ce qu'un modèle peut faire, au lieu de le croire

Un catalogue de fournisseur liste des modèles qui existent, pas des modèles que
votre compte peut appeler. Mesuré sur une vraie clé : **10 des 18 entrées
échantillonnées du catalogue NVIDIA répondent 404**, et **deux des quatre
modèles d'une chaîne de repli réelle ne savent pas produire de JSON** — ce
qu'aucune fiche ne dit et que tout outil à schéma paie.

- **Added : `corparius preflight`, et un bouton « Prouver ces modèles ».**
  Un catalogue liste les modèles qui *existent*, pas ceux que *vous* pouvez
  appeler : `/models` renvoie des noms qui répondent 404 pour votre clé — un
  palier payant auquel vous n'êtes pas abonné, une préversion jamais accordée,
  une région où votre compte n'est pas. Router un palier là-dessus configure un
  modèle qui échoue au premier tour réel. Le préflight appelle chaque palier
  configuré pour de vrai, huit jetons, rôle par rôle.

  **La classification est tout le dispositif.** Un 404 (ou un 400 qui nomme le
  modèle) bloque ; un 401/403 bloque en disant que c'est la clé et non le
  modèle ; mais un 429, un 500, un 503 ou un délai dépassé sont signalés comme
  **capacité momentanée**, jamais comme un verdict. Les paliers gratuits sur
  lesquels ce projet est bâti démarrent à froid : les rejeter jetterait des
  modèles qui marchent une minute plus tard, ce qui serait pire que le
  catalogue remplacé. Mesuré sur la configuration réelle du propriétaire — OVH
  a renvoyé `HTTP 500 TTL exceeded` pour un modèle parfaitement utilisable.

  Ce qu'il ne peut pas prouver est nommé plutôt qu'ignoré (`claudecode:` passe
  par le CLI local, `local:` par Ollama). Et rien ne se déclenche seul : une
  sonde coûte une vraie génération, donc le doctor lit le dernier résultat
  enregistré et ne mesure jamais — même séparation que le banc matériel.

  Deux défauts trouvés en l'exécutant : `llm_fallback` est une liste et non une
  chaîne, donc aucun repli n'était analysé ; et un `content: null` (le palier
  gratuit d'openrouter) devenait la chaîne « None » comme si le modèle l'avait
  dite.

- **Added : `--provider` balaie un catalogue entier, et le résultat est
  retenu.** Sur NVIDIA, avec la vraie clé du propriétaire : **10 des 18 entrées
  échantillonnées répondent 404**, sur un catalogue de 102. L'échantillon est
  réparti sur toute la liste et non pris au début — les fournisseurs listent par
  ordre alphabétique, et les vingt premiers ne représentent rien.

  La première version ne retenait rien par fournisseur : un rapport par
  exécution, écrasé à chaque fois, donc les mêmes 404 étaient redécouverts
  indéfiniment. Schéma 10 ajoute `model_probes`, clé (fournisseur, modèle), mis
  à jour plutôt que dupliqué — un modèle froid la semaine dernière qui répond
  aujourd'hui finit avec le verdict d'aujourd'hui. Rien n'est écrit quand rien
  n'a été appelé : traiter une question non posée comme une réponse serait
  exactement l'erreur que cette commande existe pour supprimer.

  Et ça sert : le sélecteur de modèles de la console retire les noms prouvés
  non appelables et étiquette ceux qui ont répondu.

- **Added : « Vérifier tous les modèles » — une passe sur tout, en une fois.**
  Tous les modèles de tous les fournisseurs configurés, un appel réel chacun.
  Sur la machine du propriétaire, cela représente **785 appels sur 10
  fournisseurs** (openrouter 365, huggingface 128, nvidia 102…), et c'est
  exactement pour ça que **le prix s'affiche d'abord** : lire les catalogues
  coûte peu, les appeler non, et ce sont ses clés et ses quotas.

  Le balayage tourne en arrière-plan avec sa progression, comme un
  téléchargement Ollama, parce qu'aucune requête HTTP n'attendrait plusieurs
  minutes. Les fournisseurs sont parcourus l'un après l'autre et non en
  parallèle : ce sont des paliers gratuits limités en débit, et en marteler
  quatre à la fois transforme chaque réponse en 429 et ne prouve rien.

  **Chaque verdict est écrit dès qu'il arrive.** Vérifié en direct : un
  balayage arrêté après 27 appels a conservé les 27. Perdre une heure d'appels
  réels parce qu'un onglet s'est fermé serait un gâchis en soi. Un second
  balayage simultané est refusé.

- **Changed : le routage recommandé ne choisit plus un modèle prouvé mort.**
  C'est ce qui donne son sens à la mesure — sans cela, on appelait 785 modèles
  pour peupler une liste déroulante. Les `default_model` du registre sont des
  chaînes figées qui pourrissent : celle d'openrouter a cessé d'exister pendant
  que sa variante payante restait, et « recommandé » écrivait alors un palier
  qui répond 404. Quand un préflight a prouvé qu'un défaut est bloqué, le
  routage prend **le modèle le plus rapide qui a répondu** sur ce fournisseur.
  Un défaut qui marche n'est jamais remis en cause pour un plus rapide : ils
  sont choisis pour leur capacité, pas leur latence. Et sans préflight, rien ne
  change.

- **Added : un verdict vieillit.** Un modèle bloqué il y a six mois peut être
  ouvert aujourd'hui, et un `capacité momentanée` n'a jamais été un verdict —
  il dit que le fournisseur était occupé, ce qui ne devient pas une
  connaissance en restant dans une table. La console affiche l'âge du plus
  vieux verdict et combien méritent d'être redemandés, et un balayage **repose
  les questions provisoires en premier** (les `capacity`, puis tout ce qui
  dépasse trente jours) — pour qu'un balayage arrêté ait dépensé ses appels sur
  ce qui valait la peine.

- **Changed : le routage décide sur la performance mesurée, pas sur « il a
  répondu ».** Une seule mesure ne valait pas grand-chose : quatre appels
  identiques de huit jetons au même modèle se sont étalés de **465 à 774 ms**.
  Le préflight prend désormais **trois échantillons** sur les seuls modèles
  qu'un palier pourrait vraiment utiliser, demande un objet JSON, et lit le
  débit dans le `usage.completion_time` du fournisseur — le temps mural sur un
  WAN mesure autant le réseau que le modèle.

  Sur la configuration réelle du propriétaire : groq 594 tok/s JSON ok,
  cerebras 38 tok/s **incapable de produire du JSON**, mistral 10,6 tok/s JSON
  ok, openrouter 7,2 tok/s **incapable de produire du JSON**. **Deux des quatre
  modèles de sa chaîne de repli** ne savent donc pas suivre un schéma — ce
  qu'une sonde de disponibilité ne peut pas voir, puisqu'elle demande un mot, et
  qui casse tout outil passant par `structured.ask`.

  L'ordre de décision : bloqué exclu, puis capacité JSON là où elle a été
  mesurée, puis fiabilité, puis débit et latence. Un modèle jamais mesuré n'est
  pas pénalisé — l'absence de preuve n'est pas une preuve. Schéma 11.

- **Added : le routage tient compte de ce qu'un modèle *est*.** Mesurer prouve
  qu'un modèle répond et à quelle vitesse ; ça ne dit rien de sa capacité à
  tenir une stratégie, ce que le palier `hard` a précisément besoin de savoir.
  Nouveau `corparius/modelinfo.py`, trois sources étiquetées selon la règle du
  dépôt : **Mesuré** (ce qu'il a fait ici), **Donné** (le catalogue du
  fournisseur — contexte, date de création, paramètre `reasoning`), **Estimé**
  (le nombre de paramètres lu dans le nom).

  Le catalogue vient de l'endpoint public d'OpenRouter, un fournisseur déjà au
  registre : 365 modèles décrits, sans clé. **Pas d'un classement de benchmarks
  scrapé** — ce sont des produits web, pas des API versionnées, et en dépendre
  ajouterait une source qui pourrit en silence, ce que ce dépôt a déjà payé.
  Qui a un tableau de confiance pointe `CORP_MODEL_SCORES` vers son fichier.

  **Le mesuré prime toujours sur le déclaré.** `gpt-oss-120b` annonce
  `structured_outputs` et a été mesuré incapable de produire un objet JSON ;
  il tombe dernier sur les trois paliers malgré sa fiche.

  Chaque palier veut autre chose : `hard` pèse raisonnement, contexte,
  génération et taille ; `trivial` le débit puis la petite taille ; `normal`
  équilibre les deux. Vérifié sur des modèles réels — `hard` prend le 120B
  raisonneur à 1 M de contexte, `trivial` le 8B à 800 tok/s.

  Deux défauts trouvés en l'exécutant : `_normalise("groq:llama-3.3-70b")`
  renvoyait `"groq"` — le préfixe fournisseur cassait toute correspondance, en
  silence ; et le routage faisait un **appel réseau**, au point qu'un test
  unitaire du CLI appelait openrouter en vrai et que 400 Ko de catalogue
  atterrissaient dans la table `settings` de l'exploitant. Le catalogue a sa
  propre table (schéma 12) et le routage ne sort plus jamais.

- **Added : `corparius preflight --all`.** La passe complète depuis un
  terminal, pour qui est en SSH ou en cron et n'a pas le bouton. Même
  comptabilité, et la même règle : le prix est annoncé avant, et rien ne part
  sans `--yes`.

## 0.3.0 — la page vue par quelqu'un qui la regarde, et l'exploitant guidé

Presque tout ici vient d'une session réelle sur une entreprise réelle : des
captures d'écran, une ventilation de dépense, 250 lignes de journal, et deux
verdicts sans ambiguïté sur le site généré. Les défauts corrigés étaient tous
visibles en dix minutes d'utilisation, et invisibles en relecture de code.

### Ce que l'exploitant doit faire lui-même

- **Added : la configuration du courrier est guidée, fournisseur par
  fournisseur.** Le préréglage remplissait quatre noms d'hôte, ce qui est la
  moitié facile ; la moitié difficile se passe sur le site de quelqu'un d'autre,
  derrière une authentification à deux facteurs, et la console n'en disait rien.
  Chaque fournisseur a désormais ses étapes numérotées avec le lien direct, et
  **l'état de chacune** déduit des réglages plutôt que cochée à la main. Une
  étape que corparius ne peut pas vérifier (installer Proton Bridge, relever un
  mot de passe sur un tableau de bord) le dit, au lieu d'afficher une case qui
  ne pourra jamais devenir verte.
- **Fixed : « No mailbox connected » revenait à chaque tour, pour rien.** Trois
  outils renvoyaient chacun leur phrase dans le journal d'actions : vrai,
  correct, répété indéfiniment, et ne pointant vers rien de cliquable. C'est
  maintenant **une** notice dans l'inbox (`add_inbox` est idempotent sur un id
  déterministe) qui nomme l'endroit où ça se règle, et la console en fait un
  bouton qui ouvre le groupe Courrier des réglages. Schéma 9 : `inbox.fix`.
- **Added : cadrer une compétence depuis la console.** `promesse-clinique`
  pesait **3 815 caractères sur chaque invite de chaque agent** — la console le
  disait déjà, sans rien offrir pour y remédier. Un sélecteur d'outils écrit
  `allowed-tools` dans le SKILL.md : mesuré sur les vraies données, la taxe
  passe de 3 815 à 0. Le corps du fichier est réécrit **à l'octet près**, la
  description n'est pas repliée, l'écriture est atomique, un outil inexistant
  est refusé (une compétence cadrée sur un nom que personne n'a ne s'applique
  jamais, en silence), et la réécriture est relue avant d'atteindre le disque.

### Fournisseurs

- **Added : `openai` et `alibaba`.** OpenAI sur `api.openai.com/v1`
  (`OPENAI_API_KEY`) ; Alibaba Cloud Model Studio — Qwen — sur l'endpoint
  compatible OpenAI, région internationale par défaut et
  `DASHSCOPE_BASE_URL` pour un compte Pékin, les deux régions étant des comptes
  distincts. Les trois points d'accès ont été vérifiés en direct : chacun répond
  401 sans clé, ce qui est un vrai endpoint qui refuse une clé manquante et non
  une URL fausse. Aucun `default_model` n'est épinglé pour OpenAI : un nom de
  modèle écrit en dur est une affirmation avec une date de péremption, et celui
  d'openrouter avait déjà pourri. Ni l'un ni l'autre n'entre dans l'ordre de
  routage automatique — ils facturent dès le premier appel, et y atterrir par
  défaut dépenserait l'argent de l'exploitant sans qu'il l'ait choisi.
- **Added : `tests/test_provider_registry.py`.** Le registre est la source de
  vérité pour les réglages, la console et le routeur ; la table de
  `docs/llm-providers.md` est écrite à la main, donc c'est le même danger que
  les manifestes d'installation. Elle est désormais confrontée au registre :
  fournisseur absent, mauvaise variable de clé, mauvais endpoint, lien de clé
  manquant. Vérifié en retirant une ligne pour voir le test échouer.

### Le site généré, repris deux fois

- **Fixed : le générateur publiait le modèle en train de réfléchir.** Une page
  est partie en ligne avec `« Check-in, anonyme, en 90 secondes. »
  Alternatively, a more punchy version: « Mental Check-in en 90s »` en H1, à
  4 rem. `sitegen.clean_headline` refuse désormais le méta-commentaire et
  récupère le bon titre quand il est là entre guillemets ; à défaut, la page
  retombe sur la proposition de valeur écrite par un humain.
- **Fixed : le générateur inventait des conditions de vente.** « Cancel
  anytime » et « Instant onboarding » étaient imprimés dans l'encadré de prix de
  *chaque* page produite, sans que personne les ait promises. Ce qui figure dans
  la liste vient de `offer.includes`, ou la section n'existe pas. Une section
  sans contenu réel disparaît au lieu d'afficher un gabarit.
- **Added : `language` sur `company.yaml`.** Déduit de ce que l'exploitant a
  écrit, puis inscrit dans le fichier pour qu'il le voie et le corrige. Il fixe
  l'attribut `lang`, les titres de sections, le bouton et la mention de
  facturation — sept langues traduites.
- **Fixed : les agents rédigeaient en anglais chez une entreprise française.**
  `Reply drafted: "Thank you for contacting us…"`, dans le journal d'une
  entreprise dont chaque champ de config est en français : aucune invite n'avait
  jamais nommé de langue, donc le modèle prenait celle de l'invite système.
  `agents._messages` — le point de passage unique de tous les outils qui
  rédigent — porte désormais la langue de l'entreprise. Formulée comme la langue
  de la *sortie*, jamais « écris *reply* en français », ce qui est exactement la
  tournure qui avait fait répondre « Réponse » au chat CEO. Vérifié par un appel
  réel : le modèle répond en français.
- **Changed : la page a une présence.** Le premier correctif retirait le gabarit
  centré et sa grille de cartes sans rien mettre à la place — verdict du
  propriétaire, « on dirait une page blanche avec du texte ». La page engage
  maintenant sa couleur : trois changements de fond, le prix comme nombre le
  plus fort de la page, et une **signature** de barres dérivée d'une empreinte
  du nom de l'entreprise, différente par entreprise et stable d'une
  construction à l'autre. Toujours un seul fichier, sans script, sans police
  distante, sans requête sortante.
- **Fixed : le bandeau de prix du thème sombre était illisible.** Texte à
  **1,16:1** contre son propre fond — quasi-noir sur quasi-noir. Une ligne
  supposait que la couleur de fond de la page fait un bon texte sur le bandeau
  inversé : vrai en clair (18:1), faux en sombre. Trouvé sur une capture
  d'écran, parce que rien ici ne savait ce qu'était un contraste. `palette_for()`
  dérive désormais chaque couleur de ce sur quoi elle se pose, et
  `tests/test_sitegen_contrast.py` parcourt les deux thèmes contre six accents.
  Le libellé du bouton passe du même coup de 1,74:1 à 11,4:1 sur un accent
  clair : `#fff` n'est plus écrit en dur. Aucune couleur n'arrive plus par
  `color-mix` — une valeur qui se résout dans le navigateur est une valeur
  qu'aucun test ne peut mesurer.
- **Added : le site est fait pour être trouvé.** `canonical`, Open Graph, carte
  Twitter, données structurées JSON-LD (`Product` + `Offer`, et `FAQPage` quand
  la FAQ existe — demandée une seule fois et servie aux deux), `robots.txt` et
  `sitemap.xml` écrits à côté de la page, repères `header`/`main`/`footer`. Rien
  d'inventé là non plus : jamais de note ni de nombre d'avis, et pas de prix
  signifie pas d'`Offer` plutôt que `"price": "0"`. Tout ce qui est absolu
  demande `site.url` ; sans lui c'est omis, jamais deviné, et le doctor le dit.
- **Security : les réponses de modèle qui entrent dans le bloc JSON-LD** ont
  chaque `<`, `>` et `&` échappés en `<`. N'échapper que `</script>` est le
  conseil habituel, mais c'est raisonner sur des états d'analyse HTML.
- **Added : `site.theme`, `site.font`, `site.accent`, `site.url`.**
- **Added : la compétence livrée `landing-craft`,** adaptée du greffon
  NullToHero du propriétaire, cadrée sur `build_sales_site` et
  `draft_design_brief` — zéro coût sur les autres invites. Les mêmes règles sont
  dans `DESIGN.md`, tenues par `tests/test_sitegen_contract.py`.
- **Added : un test qui vérifie que le JavaScript de la console se parse.**
  180 000 caractères de script en ligne, édités à la main, que ni ruff, ni mypy,
  ni aucun test Python ne regardait ; une accolade en trop donnait une page
  blanche que seul le navigateur signalait.

## 0.2.0 — une revue adverse, et deux trous qu'elle a trouvés

- **Fixed (HIGH) : le tag de mise à jour sortait du dépôt.** La route de la
  console lisait le tag dans le corps de la requête et l'interpolait dans l'URL
  de téléchargement. `requests` normalise les segments `..` en préparant la
  requête, donc `DOWNLOAD_BASE` n'épinglait rien :
  `../../../../quelquun/dautre/releases/download/v1` résolvait vers son dépôt.
  **L'empreinte n'y pouvait rien** — `SHA256SUMS` venait du même répertoire
  choisi par l'attaquant, donc la vérification était d'accord avec elle-même, et
  le binaire était installé puis exécuté. Reproduit avant d'être corrigé. La
  console demande désormais le tag à la vérification de version, comme le CLI l'a
  toujours fait, et `check_tag` refuse tout ce qui n'est pas un numéro de version.
- **Fixed (MEDIUM) : un saut de ligne dans une valeur écrivait ses propres
  réglages.** Les valeurs partaient verbatim dans `.env`, jointes par des sauts
  de ligne. Une seule écriture acceptée pouvait donc ajouter
  `CORP_UI_ALLOWED_HOSTS=evil.example` — que `SECURITY.md` promet inatteignable
  par l'API et qu'un test vérifie... par son **nom**. Le nom était protégé, pas
  la valeur. Poser un hôte là éteint la défense contre le DNS-rebinding et la
  console cesse d'être locale. Le garde est dans l'écrivain, pas chez l'appelant :
  il y en a trois, dont une restauration qui lit un `.env` sorti d'une archive.
- **L'injection de prompt est désormais éprouvée, pas affirmée.** Douze ticks
  avec un routeur qui répond l'attaque à chaque appel : seuls les outils des
  playbooks s'exécutent, et les trois outils sensibles finissent en « pending
  human approval » avec une approbation dans la file. Le message d'un visiteur
  est encadré et nommé comme non fiable dans l'invite d'une app — mitigation
  posée par-dessus la garantie structurelle, jamais à sa place.
- Ce que ça ne couvre pas est dit dans `docs/securite.md` : une injection
  réussie peut encore faire écrire une mauvaise phrase.

## 0.2.0 — le chiffrement fait enfin ce qu'il annonce, et on peut restaurer

- **Fixed: activer le chiffrement au repos ne chiffrait que la prochaine
  écriture.** Écrire `CORP_SECRET_KEY` laissait toutes les clés déjà stockées en
  clair, donc les sauvegardes continuaient à les vider : un réglage qui avait
  l'air fait et ne l'était pas. `corparius secrets on` écrit la phrase **et**
  rechiffre l'existant ; la console fait la même migration quand on y écrit le
  champ, au lieu de tendre le même piège en plus joli.
- **`corparius secrets off` existe**, parce qu'une porte à sens unique est une
  porte que personne n'ouvre. La phrase générée n'est montrée qu'une fois, avec
  ce qu'elle implique : c'est la seule copie, et aucune sauvegarde ne la porte.
- **Fixed: rien ne savait consommer une sauvegarde.** On en produisait, on les
  avait durcies, on les décrivait — et aucun chemin de code n'en restaurait une.
  « Ça restaure » était une affirmation sur un processus que personne n'avait
  écrit. `corparius restore <zip>` le fait.
- **La seule opération qui détruit volontairement**, donc bâtie autour du refus :
  elle valide l'archive avant de toucher quoi que ce soit, **sauvegarde ce
  qu'elle va remplacer**, et refuse une archive qui n'est pas une sauvegarde
  corparius comme un chemin qui sortirait de sa zone de décompression (zip-slip).
- **Fixed, trouvé au premier essai réel : une restauration pouvait mourir à
  mi-chemin.** Un `rmtree` a échoué sous Windows *après* qu'une entreprise ait
  déjà été remplacée — une demi-restauration sans rien à défaire. Chaque étape
  met de côté par renommage désormais, un appel atomique, et toute erreur défait
  ce qui précède.
- **Le `.env` de l'archive est fusionné, jamais recopié.** Ses valeurs secrètes
  sont vides par construction ; les écraser effacerait la phrase qui ouvre le
  texte chiffré qu'on restaure.
- Vérifié de bout en bout : chiffrement activé, sauvegarde, données détruites,
  restauration — la clé revient, l'archive ne contient nulle part le texte en
  clair, et `REDACTED.txt` annonce « No secret had to be blanked ».

## 0.2.0 — revenir en arrière ne peut plus se faire en silence

- **Fixed: un ancien build rouvrant un store déjà migré ne disait rien.**
  `_migrate` ne marche que vers l'avant, donc `PRAGMA user_version = 99` face à
  un build qui en connaît 6 donnait une boucle vide : ouvert, lancé, et écrit
  sans un mot. Vérifié en le faisant. C'est le conseil de reprise après une
  mise à jour ratée — renommer le `.old` — qui rendait ce trou concret.
- **Il s'ouvre toujours**, délibérément : refuser bloquerait exactement la
  personne qui en a besoin. Mais il le dit, et le doctor **échoue** dessus en
  nommant la sortie : remettre à jour, ou restaurer la sauvegarde prise avant.
  Un vieux build qui écrit là où un schéma plus récent veut dire autre chose,
  c'est la façon dont des données deviennent fausses sans bruit.

## 0.2.0 — une sauvegarde qu'on ose garder quelque part

- **Une sauvegarde n'écrit plus jamais un secret en clair.** Elle en portait
  tous : le store contient les clés enregistrées depuis la console, et le module
  le disait en demandant de « traiter le fichier comme un mot de passe ». Ce qui
  faisait du seul endroit sûr pour une sauvegarde : nulle part. Pas un NAS, pas
  un mail à soi-même, pas un dépôt privé — un dépôt devient public par accident
  plus souvent qu'un portable ne meurt.
- **La règle est plate.** Un réglage déjà chiffré au repos voyage tel quel, en
  texte chiffré. Tout autre secret est vidé, et son **nom** est écrit dans
  `REDACTED.txt` pour dire quoi ressaisir. La redaction se fait sur une *copie* :
  le store vivant n'est jamais modifié, et un test le tient.
- **`CORP_SECRET_KEY` achète enfin quelque chose.** Avec le chiffrement au
  repos, la sauvegarde restaure l'installation entière ; sans lui, tout sauf les
  clés. C'est un meilleur argument que n'importe quel avertissement.
- **`.env` entre dans l'archive**, ce qui n'était pas le cas : un restore
  perdait tous les réglages de démarrage. Valeurs secrètes vidées, commentaires
  et lignes non secrètes conservés verbatim — c'est un fichier édité à la main.
- **Vérifié que la phrase secrète ne voyage jamais avec le coffre qu'elle
  ouvre.** `CORP_SECRET_KEY` vit dans `.env`, et `.env` est maintenant dans
  l'archive : sans redaction, une sauvegarde volée aurait contenu la serrure et
  la clé. Elle est dans l'ensemble vidé, et c'est la première chose qu'un test
  vérifie.
- **Les tests cherchaient dans les octets du zip**, ce qui ne prouve rien : la
  compression peut cacher une chaîne bel et bien présente. Ils décompressent
  chaque membre désormais — c'est ainsi qu'un test « la clé ne fuit pas » passe
  pendant que la clé fuit.
- **`--with-secrets`** garde les clés en clair pour une copie de reprise sur
  disque chiffré, et annonce ce qu'elle est. La console ne propose que l'archive
  sûre : un clic dans un navigateur ne doit pas pouvoir fabriquer un mot de passe.
- **Fixed: un test archivait les vraies entreprises du développeur.** Le dossier
  personnel était capturé à l'import, avant toute redirection par une fixture,
  donc un test de console zippait 139 fichiers réels et y passait 33 secondes.
  Résolu à l'appel — la leçon que `cli._store()` avait déjà apprise : un
  instantané au niveau module d'un réglage en couches est l'instantané de la
  mauvaise couche.
- Le store est désormais copié par l'API de sauvegarde de SQLite plutôt que
  comme un fichier : une base vivante et son `-wal` ne forment pas une paire
  cohérente, et le but de ce module est de produire quelque chose qui restaure.

## 0.2.0 — mettre à jour depuis la console

- **`corparius update`, et un bouton dans la bannière.** Jusqu'ici la console
  savait dire qu'une version existait et rien de plus — et même ça ne marchait
  pas : sans release publiée, l'API GitHub ne renvoyait rien, donc la bannière
  ne pouvait jamais apparaître. Elle télécharge maintenant, vérifie et remplace.
- **Aucune entreprise ne peut être perdue par une mise à jour**, et ce n'est pas
  une affirmation : le binaire et les données vivent dans deux endroits
  différents, les seuls chemins écrits sont le nom du binaire plus un suffixe,
  et un test fait tourner une vraie mise à jour au-dessus d'un dossier plein
  d'entreprises en exigeant que **chaque octet** soit identique après. Une
  sauvegarde est prise avant l'échange malgré tout, et l'opération refuse si le
  fichier à remplacer contenait le dossier de données. Sur seize tests, treize
  sont des refus.
- **Deux renommages, pas une réécriture.** Le nouveau build est écrit à côté de
  l'ancien pendant que celui-ci tourne encore, puis deux `os.replace` sur le
  même système de fichiers. La fenêtre où aucun corparius n'existe à ce chemin
  fait deux appels système de large au lieu d'un téléchargement entier, et si le
  second échoue le premier est défait.
- **L'ancien build est conservé, pas supprimé**, jusqu'à ce que le nouveau
  démarre une fois — c'est le démarrage lui-même qui l'efface, donc sa présence
  est exactement le signal « le nouveau n'a jamais tourné ».
- **Une empreinte qui ne correspond pas est un refus, jamais un avertissement.**
  C'est le seul endroit de corparius qui télécharge du code pour l'exécuter. Le
  module dit aussi ce que la vérification **ne** prouve pas : les sommes vivent
  dans la même release que le binaire, donc c'est de l'intégrité de transport,
  pas de la provenance. L'image Docker reste le chemin signé (SLSA).
- **Les fournisseurs restent connectés.** Clés et paliers vivent sur deux
  couches, `.env` et la table `settings` du store, toutes deux dans le dossier
  de données. Éprouvé avec une clé sur chacune, sur une vraie mise à jour :
  `connected_providers()`, les paliers et les deux clés sont identiques des deux
  côtés. Un test le tient désormais, parce que « ça devrait marcher » n'est pas
  ce qu'on veut découvrir au tick suivant.
- **Vérifié contre la vraie release.** Un binaire construit exprès en 0.0.9 a
  téléchargé la v0.1.0 publiée, vérifié son empreinte, échangé le fichier : le
  binaire obtenu est **octet pour octet** celui de la release, l'entreprise
  `acme` créée avant est intacte (les neuf fichiers stables comparés avant/après
  sont identiques, elle répond toujours dans le store), et le `.new` a disparu.
- **Le premier saut reste manuel** : la v0.1.0 publiée ne contient pas le bouton,
  puisqu'il arrive après elle. Idem pour le ménage du `.old`, que fait le build
  installé. Dit dans `docs/install.md` plutôt que laissé à découvrir.
- Refuse hors du binaire téléchargeable en disant quoi faire à la place
  (`git pull`, `docker pull`), sur une plateforme sans release publiée, et quand
  le dossier n'est pas accessible en écriture. Le bouton n'apparaît que là où le
  serveur dit pouvoir agir : le proposer ailleurs serait une promesse que le
  clic suivant casse.

## 0.1.0 — le binaire est aussi le CLI

- **Fixed: aucune commande n'existait pour qui télécharge le binaire.** Le
  lanceur figé cherchait dans `argv` exactement une chaîne, `--no-browser`, et
  servait la console quoi qu'il y ait d'autre. Donc `corparius doctor` ouvrait
  la console, et `apps serve`, `skills install starter`, `bench`, `claude` —
  toutes les commandes que la documentation dit de lancer — n'existaient pas
  sur le chemin d'installation que le README met en premier. Le pack de
  compétences de départ voyageait même *dans* l'exécutable sans que rien ne
  puisse le demander. Un premier argument qui n'est pas un drapeau part
  maintenant au CLI ; rien, ou seulement des drapeaux, sert la console comme
  avant.
- **Parité mesurée, pas supposée.** Les 23 sous-commandes ont été passées dans
  deux dossiers identiques, une fois par le CLI source et une fois par le
  binaire : **28 invocations, aucune différence** — mêmes sorties, mêmes codes
  de sortie. Plus les chemins que le balayage ne couvre pas : `ui`,
  `apps serve`, `bench` (une vraie mesure via Ollama) et `claude --check`, qui
  prouve la résolution du `.cmd` Windows depuis un binaire figé.
- **Fixed: une sortie que la page de code de la machine ne sait pas encoder
  faisait planter le binaire.** Un build figé écrit stdout dans l'encodage ANSI
  de la machine, et le bootloader initialise Python avant que `PYTHONUTF8` ou
  `PYTHONIOENCODING` puissent y changer quoi que ce soit — les deux sont
  ignorés, vérifié. Sur un Windows occidental tout passe, mais le tiret cadratin
  et les chaînes françaises n'existent pas dans une page cyrillique : un
  `doctor --lang fr` redirigé y mourait sur un `UnicodeEncodeError`. Il dégrade
  en `?` désormais. Une commande de diagnostic qui ne survit pas à une
  redirection n'est pas une commande de diagnostic.
- Le serveur MCP est la seule chose que le binaire ne contient pas — dépendance
  optionnelle, et pas de `pip` dans un exécutable figé. `docs/mcp.md` le dit
  maintenant au lieu de le laisser découvrir.

## 0.1.0 — les LLM de l'entreprise, utilisables par ses applications

- **Une app est un fichier YAML** dans `companies/<slug>/apps/`, à côté des
  skills : un nom, une invite système, un palier et ses plafonds. Elle passe par
  `HybridRouter` comme tout le reste, donc elle hérite des paliers, de la chaîne
  de repli et de la comptabilité des coûts que les agents ont déjà. Jusqu'ici,
  donner une FAQ à son site voulait dire recopier une clé API ailleurs — et dans
  une page web, une clé recopiée est lisible par quiconque ouvre l'inspecteur.
- **La dépense est enregistrée sous `app:<nom>`**, ce que la ventilation par
  agent de la console affiche déjà : aucune ligne de reporting nouvelle.
- **`corparius apps run` fonctionne en mode mock**, donc une app s'écrit et se
  mesure hors ligne avant d'être exposée à quoi que ce soit.
- **Le point d'accès est un second serveur, délibérément pas la console.** La
  console est le plan de contrôle derrière un jeton sur `127.0.0.1` ; un seul
  processus pour les deux ferait d'un contrôle qui cède l'exposition des deux.
  Un test demande `/api/settings` au port des apps et exige un 404.
- **Quatre gardes avant tout appel, du moins cher au plus cher** : débit,
  origine, clé, plafond du jour. Cet ordre n'est pas celui d'une check-list. Le
  plafond est une lecture SQLite : le placer avant la limite de débit laisserait
  une inondation faire un aller-retour en base par requête. Et une requête
  refusée consomme quand même son quota, sinon deviner des clés serait gratuit.
- **Une liste d'origines vide n'autorise aucun navigateur, pas tous.** Un défaut
  « n'importe quelle page peut appeler » est la façon dont un point d'accès
  finit intégré à un site dont son propriétaire n'a jamais entendu parler.
- **La clé n'est pas un secret et la commande le dit.** Ce qu'une page web
  envoie est lisible dans l'inspecteur ; la clé identifie une app pour lui
  attribuer une dépense et pouvoir la révoquer. Ce qui protège est ailleurs.
- **La même app, figée dans le site.** `site.faq_app` dans `company.yaml` :
  l'app tourne une fois à la construction et ses réponses sont écrites dans le
  HTML. **La page reste un seul fichier statique** — pas de JavaScript, aucun
  point d'accès à joindre, rien à laisser allumé — et un test le tient. Un
  modèle injoignable omet la section et construit la page quand même.
- **Fixed: `company.load` jetait silencieusement toute clé qu'il ne nommait
  pas.** Il reconstruit un dict normalisé, donc le bloc `site:` disparaissait
  quoi qu'en dise le YAML. Nommé désormais, avec un avertissement pour un demi-
  bloc — une app sans questions a l'air configurée et ne produit rien.
- **`corparius apps export netlify`** écrit la fonction à côté du site, pour un
  site qui répond sans machine allumée. **À partir de là corparius ne voit plus
  la dépense** : la commande le dit, et l'avertissement est répété en tête du
  fichier généré, là où l'exploitant le lit au moment de le choisir. L'export
  refuse ce qui ne pourrait échouer que plus tard : un palier `local:`,
  `claudecode:` ou `cloud:`, et une app sans origines. `node --check` valide le
  fichier généré dans les tests, quand node est là — rien d'autre ici ne
  vérifie du JavaScript.
- Contrôle `apps` du doctor : combien, servies où, et surtout une app définie
  sans clé — elle a l'air prête et chacun de ses appels est refusé.
- `CORP_APPS_ENABLED` est **coupé par défaut**, comme les plugins et pour la
  même raison. `docs/apps.md` couvre le tunnel plutôt que d'ouvrir l'écoute.
- **Fixed: le pack de compétences de départ n'arrivait qu'à ceux qui avaient
  cloné le dépôt.** `skills install starter` s'était écrit sa propre recherche —
  racine du dépôt, puis `_MEIPASS` — et un wheel n'a ni l'une ni l'autre : les
  fichiers voyagent *dans* le paquet, sous `_data/`. Tout le monde recevait « le
  pack de départ n'est pas dans cette installation ». Il passe par
  `paths._resource`, seul endroit qui connaît les trois dispositions, et les
  deux manifestes d'empaquetage le nomment enfin. Vérifié en construisant un
  wheel, en l'installant, et en lançant la commande.

## 0.1.0 — 141 compétences qu'on ne peut pas déposer

- **`corparius skills import`** adapte un `SKILL.md` écrit pour un autre hôte.
  Mesuré sur `anthropics/knowledge-work-plugins` (17 plugins, 141 compétences,
  Apache-2.0), pas sur la présentation qui en est faite : leur en-tête est
  `name`/`description`/`argument-hint` et ne déclare **aucun** `allowed-tools`,
  leur médiane est ≈ 12 Ko contre un plafond de 4000 caractères pour le bloc
  entier, et leurs corps demandent à un humain de répondre en cours de route.
  Déposées telles quelles, les 141 entreraient dans **chaque** invite de
  **chaque** agent — la panne que le chargeur venait d'être durci à exposer.
- **La commande ne convertit pas.** Elle copie le corps verbatim et annonce
  l'arithmétique avant d'écrire : « 14182 caractères, plafond 4000, 71,8 % sera
  coupé à l'exécution ». Vérifié contre le fichier réel : le chargeur en a gardé
  3999 sur 14182. Un import silencieux aurait refait la panne qu'il documente.
- **Deux refus valent plus que la fonction.** Un nom que la table ne connaît pas
  ne reçoit **aucun** outil et la commande le dit fort : une portée inventée
  pointe de la prose vers le mauvais agent, en silence. Et un import n'écrase
  jamais une compétence — ce qui rend un import utilisable, c'est l'élagage fait
  après.
- **`corparius skills list`** montre enfin depuis un terminal ce que seuls le
  doctor et la console savaient : ce qui est chargé, et combien de caractères
  pèsent sur chaque invite.
- **Six compétences pour démarrer** (`corparius skills install starter`) :
  support, social, finance, concurrence, design, code — les métiers que le
  roster exerce et qui n'avaient aucune prose, en commençant par les deux
  paliers les plus fréquents. Adaptées de la bibliothèque ci-dessus, créditées
  dans l'en-tête où l'attribution ne coûte rien à l'exécution, ramenées de
  12–26 Ko à environ 1 Ko. Un test les tient à la barre qu'elles enseignent.
- **Un pack de compétences n'a plus besoin de code.** `PluginManifest` exigeait
  un `entrypoint` module:fonction, donc la seule façon de distribuer de la prose
  était d'écrire du Python qui tourne pour n'exécuter rien. Un manifeste
  `kinds: ["skills"]` peut l'omettre ; tout le reste doit encore nommer du code.
  La liste blanche vérifiée continue de s'appliquer, pour une raison qui n'est
  pas l'exécution : ce corps entre dans l'invite système avec l'autorité du
  prompt de rôle.
- **Fixed: les tests pouvaient écrire dans le dépôt.** L'arbre `skills/` pend à
  `CORP_HOME`, pas à `CORP_DATA_PATH` que la fixture hermétique épingle, et une
  source checkout résout `CORP_HOME` vers la racine du dépôt. Un import de test
  y a atterri. `/skills/` et les dossiers de plugins installés sont désormais
  ignorés par git.
- Dossier `docs/reverse-engineering/knowledge-work-plugins.md` : les mesures, ce
  qui a été repris, et ce qui a été écarté — la sélection par `description`
  (routage par le modèle), `argument-hint`, les connecteurs MCP par pack, et les
  treize plugins dont le métier n'existe pas ici.

## 0.1.0 — l'abonnement Claude, sans le piège

- **Fixed: `corparius claude` et la console écrivaient deux plans différents.**
  Le terminal appelait `claudecli.plan()` sans argument, ce qui se lit comme
  « aucun gratuit n'est connecté » et met **tous** les paliers sur l'abonnement
  — le défaut coûteux contre lequel la docstring de `plan()` met elle-même en
  garde. Il ignorait aussi `--all-tiers`, déclaré dans l'analyseur d'arguments
  et jamais lu, et le verdict machine mesuré ne l'atteignait pas. Il passe
  maintenant les mêmes entrées que la console : fournisseurs connectés et
  verdict local.
- **Fixed: le test qui aurait dû l'attraper comparait au même appel fautif.**
  `test_the_one_command_writes_exactly_the_console_plan` vérifiait le résultat
  contre `claudecli.plan()` — sans argument lui aussi — donc il était d'accord
  avec le bug. Ce sont les **entrées** qui doivent correspondre, pas seulement
  la fonction appelée.
- **« Installez Claude Code » se lisait comme « c'est déjà fait »** par
  quiconque possède Claude Desktop. Ce sont deux produits : Desktop est
  l'application de discussion, corparius pilote le CLI en mode headless, et une
  interface graphique ne répond pas à `claude -p … --output-format json`.
  corparius détecte l'application de bureau et le dit, en précisant que
  l'abonnement est le même et qu'il n'y a rien de plus à souscrire. La
  détection ne change que le message : `shutil.which("claude")` reste seul juge
  de ce qui est appelable.
- **Le message nomme la commande au lieu de renvoyer vers une page produit**, et
  `corparius claude --install` fait l'étape npm. Jamais implicite : poser un
  paquet global sur la machine de l'exploitant n'est pas une décision que prend
  un contrôle d'état. Même bouton sur la carte de la console, et un test tient
  que l'endpoint sondé n'installe jamais rien.

## 0.1.0 — « joignable » n'est pas « capable »

- **Fixed: le routage recommandé donnait le palier trivial au local dès qu'un
  port répondait.** Un seul bit — Ollama a-t-il répondu — décidait du palier
  **le plus fréquent** du roster (social toutes les 2 h, publicité et finance
  toutes les 6 h), et pouvait donc y installer un modèle de 9,6 Go sur un
  processeur qui met une minute à écrire un brouillon. Mesuré sur la machine de
  développement de ce dépôt : `gemma4:e4b`, le modèle que ce routage assignait,
  tourne à **2,2 jetons/s en CPU pur** — 232,7 s pour un brouillon de 512
  jetons. Ce n'était pas « lent », c'était cassé, et rien ne le disait.
- **`corparius bench`** mesure ce que la machine sait faire, l'affiche et le met
  en cache : débit, temps de chargement, placement GPU/CPU. Même bouton sur la
  carte Ollama de la console. Ce qui est mesuré arrivait déjà dans les réponses
  d'Ollama — `eval_count`, `eval_duration`, `load_duration` — et `OllamaProvider`
  le jetait, exactement comme le coût OpenRouter deux jours plus tôt.
- **Le verdict décide, et montre son calcul.** Un seuil est un jugement, donc il
  est réglable (`CORP_LOCAL_MIN_TOKENS_PER_SEC`, 15 par défaut) et le message
  donne l'arithmétique plutôt que de la cacher : on peut être en désaccord avec
  un seuil, pas avec « à 2,2 jetons/s, 512 jetons prennent 232,7 s ».
- **L'encombrement se juge sur la RAM totale, pas sur la RAM libre.** Mesurée à
  une heure d'écart sur la même machine, la RAM libre est passée de 4,0 à 1,9 Go
  parce qu'une suite de tests tournait. Un verdict qui change avec la météo n'en
  est pas un. La pression du moment est dite, elle ne refuse jamais.
- **Quand la machine ne peut rien servir**, le trivial part chez un fournisseur
  gratuit, puis Haiku, puis Sonnet. Haiku avant Sonnet parce que la chaîne de
  repli est partagée par tous les paliers : ce qu'on y met est ce vers quoi un
  *post social* raté escalade. Opus n'y figure pas — il reste le modèle du
  palier difficile, atteint parce qu'on le demande, jamais parce qu'autre chose
  est tombé. Le local **reste** le dernier maillon dans tous les cas.
- **Aucune mesure ne se déclenche toute seule.** Elle coûte une génération
  réelle — 93 s de chargement sur la machine ci-dessus. `doctor`,
  `/api/providers` et `/api/ollama` lisent le cache et ne mesurent jamais ; des
  tests le tiennent, parce que la même erreur sur un endpoint sondé avait déjà
  fait tomber la CI cette semaine. `/api/ollama` réutilise en plus la liste que
  `/api/tags` vient de lui donner au lieu de la redemander.
- **Ce qui n'est pas détectable renvoie `None`, jamais 0** : « je ne sais pas »
  et « il n'y en a pas » sont opposés, et un consommateur qui les confond refuse
  l'inférence locale sur une machine qui pourrait la faire tourner.
- Nouvelle table `machine` (schéma v6), une ligne, avec sa migration.

## 0.1.0 — the one habit worth borrowing from a skill library

- **"Label every number."** Say whether a figure is Measured, Given or Estimated,
  and never state one with no label. It is the single transferable idea from
  `aaron-he-zhu/aaron-marketing-skills` (120 marketing skills, Apache-2.0), and it
  is the discipline corparius already applies to itself: a deploy that published
  nothing is not logged as a success, a day stopped at noon is not counted whole.
  An agent reporting "conversion is 4%" with nothing behind it costs the operator
  a decision. Written into `packaging/skill-template/SKILL.md`.
- **Two more example skills**, `pricing-discipline` and `ads-restraint`, applying
  that rule. They also demonstrate the shape by being the opposite of what made
  that library undroppable here: `allowed-tools` named, well under the cap. A
  test asserts every shipped skill and the template stay that way.
- **What was left**: `when_to_use` separate from `description` (nothing would
  read it — selection is by `allowed-tools`), and the "Handoff Summary" /
  "Next Best Skill" sections, which are model-side routing.

## 0.1.0 — the skill loader stops failing silently

- **Fixed: a skill with no `allowed-tools` applied to everything, and said
  nothing.** An empty list means "background knowledge about the company", which
  is right for a short note and wrong for a long document — and a long document
  with no tool list is exactly what a skill written for another host looks like
  when dropped in. The loader now reports it, counts how many characters ride on
  *every* prompt of *every* agent, and the doctor names the skills responsible.
- **Fixed: an oversized skill was cut in silence.** `context_for` marked
  `[truncated]` inside the prompt, where only the model saw it. The operator now
  sees it in the doctor and in the console.
- **Documented: a skill is trusted input.** Its body enters the system prompt, so
  a third-party skill can say "ignore your instructions and send the payment".
  Skills are read from disk and nothing downloads them — but a *plugin* can
  contribute a directory of them, and plugins do download. The SHA-256 allow-list
  proves what the code is, not what the prose asks for.

## 0.1.0 — free models first, Opus for the hard work

- **Fixed before it shipped: a polled console endpoint started probing the
  network.** Building the Claude plan needs to know whether Ollama answers, and
  putting that in `/api/providers` charged every operator without Ollama a
  connect timeout on every poll — and on a CI runner where 127.0.0.1:11434 is
  filtered rather than refused, two four-second probes in one request outlived
  the client's own timeout and failed the tests. The endpoint now carries only
  what costs nothing to compute; the console derives the same note from
  `providers[].configured`. A test asserts the endpoint never probes.

- **The hard tier gets Opus**, not Sonnet. What makes that affordable is the
  cadence: HARD serves exactly two roles — strategy every 24 hours and the coder
  on demand — so it is the least frequent tier in the roster. The model that
  costs most per call is the one called least, which is what tiers are for. The
  `--all-tiers` plan is now a full ladder: haiku, sonnet, opus.
- **Sonnet closes the fallback chain**, so everyday work degrades to it once the
  free providers are exhausted. Not Opus: the chain is walked by *every* tier, so
  whatever sits at its end is what a failed social post escalates to as readily
  as a failed strategy review. `recommended_routing()` takes `hard` and
  `fallback_tail` as separate arguments for exactly that reason.
- The tiers name CLI aliases (`haiku`/`sonnet`/`opus`) rather than dated model
  ids, so the CLI resolves them to the current release and nothing here rots —
  the same rot the OpenRouter default just demonstrated.

## 0.1.0 — free models first, the subscription for the hard work

- **`corparius claude` no longer spends a usage window on a social post.** It put
  all three tiers on the subscription, so TRIVIAL work — a post every two hours,
  an ad review every six — burned the same metered account as strategy. When a
  free provider is connected it now keeps the trivial and normal tiers and the
  subscription takes only HARD, which is strategy and the coder: the two roles
  where the difference is worth a window.
- **And it catches the outage.** The subscription becomes the last remote step of
  `CORP_LLM_FALLBACK`, so a free provider going down escalates to Claude instead
  of dropping straight to a local model that may not be installed.
- With nothing free connected there is nothing to prefer, so it serves every tier
  as before. `--all-tiers` (and a second console button) asks for that on purpose.
- `recommended_routing()` takes a `hard` override, and `connected_providers()`
  now lives in `llm.py` instead of being computed inline in the console.

## 0.1.0 — a Claude subscription is one command

- **`corparius claude`.** Running every tier on a Claude subscription needs four
  settings to agree — mock off, cloud on, Claude Code on, tiers pointed at
  `claudecode:` — and that hidden conjunction was most of why nobody turned it
  on. The console has had a one-press card for it, but it sits in the Providers
  tab behind fourteen other providers, and an operator who drives corparius from
  a terminal never saw it. One command now, applying the same plan, and refusing
  to write anything if the CLI test fails: half-configuring "cloud on, mock off"
  against a CLI that cannot answer leaves the operator worse off than before.
- **It is now discoverable, not just available.** `corparius doctor` used to say
  "disabled" when the target was off; it now says so *and* names the command when
  the `claude` CLI is already installed on the machine. `start.py` says the same
  on a first run. Someone holding a subscription was otherwise paying for
  inference they could get from a login they already have.
- **Fixed: `cli._store()` escaped the test fixtures.** It read the import-time
  settings snapshot, taken at collection — before the hermetic fixture redirects
  `CORP_DATA_PATH`. Any test calling a `cmd_*` function therefore wrote to the
  developer's own store. It resolves `Settings()` at call time now, which is what
  every other surface already does.

## 0.1.0 — a model name that rots is now caught, not shipped

- **Fixed: the shipped OpenRouter default no longer existed.**
  `deepseek/deepseek-r1-0528:free` has been dropped from OpenRouter's catalogue
  while its paid variant stayed, so `recommended_routing()` — the one-click
  "coherent routing" feature — was writing a `CORP_HARD_MODEL` that 404s. It now
  points at `openai/gpt-oss-20b:free`, which is listed today.
- **And the durable half.** Every `default_model` in `OPENAI_COMPAT_PROVIDERS` is
  a string frozen on the day it was written, and all fourteen rot the same way.
  A new doctor check compares each configured tier against what the provider
  actually advertises at `/models` and warns when the model is gone. Silent in
  mock mode, without a key, or when the provider does not answer: an unreachable
  catalogue is not evidence that a model has been removed.

## 0.1.0 — spend measured in money, not only in tokens

- **Fixed: the cost was arriving and being thrown away.** OpenRouter reports what
  a call cost in the same `usage` block corparius already parsed for token
  counts, on the `/chat/completions` endpoint it already called.
  `OpenAICompatProvider.generate` read `prompt_tokens` and `completion_tokens`
  and dropped the rest, so the whole safety story was denominated in tokens while
  the operator it is written for budgets in euros. `Usage.cost` now carries it
  through the budget, the circuit breaker and the store, repair rounds included.
- **Zero means "not reported", never "free".** Thirteen of the fourteen
  OpenAI-compatible providers send no cost at all. `store.cost_reported()` says
  whether anything was ever reported, and the console prints money only when it
  was — printing "0.00" for a provider that reports nothing would tell an
  operator on a paid key that they spent nothing.
- **An opt-in money ceiling.** `CORP_SESSION_COST_BUDGET` (and `cost_budget` per
  company) stops a session the way the token budget does. Default 0, disabled:
  a second way for a run to stop has to be asked for, not inherited.
- Store schema v5, migrated in place; existing usage rows keep 0.

## 0.1.0 — an agent that does not know can now ask

- **A typed inbox beside the approvals.** Approvals answer "may I". Two things
  had nowhere to go. An agent lacking a fact could not ask for it: a deploy with
  no provider configured dead-ended inside its tool, left one line in the action
  log and was never seen again, while the company carried on as if nothing had
  happened — the same failure as inventing an answer, one layer down. And a
  session that froze itself could not say so, so a company could sit dead for a
  day unless the operator thought to read the log.
- **Questions block, notices do not.** A question parks the work that raised it
  exactly as an approval does — same `pending` result, same `waiting` task — and
  releases it when answered. `deploy_site` with no provider now asks instead of
  failing into the log, and `ask_operator` is a mappable tool so the CEO can
  queue "ask about X" and have it parked and released by machinery that already
  exists. A circuit-breaker freeze and an unreachable model each leave a notice.
- **Asked once, answered once.** The id is a hash of what is being asked, so a
  re-run of the same tick finds the question it already filed. An answer is
  matched on the title rather than the id, which folds in the agent: "which
  mailbox?" answered for outreach is answered for support, instead of the
  operator being asked the same thing once per role. Resolution is
  first-responder-wins — the waiting work has already moved on the first answer,
  and overwriting the record would leave the store disagreeing with what
  happened.
- Visible from every surface that already decides approvals: the console
  (Operations, counted in the "needs you" badge), `corparius inbox`, and the MCP
  tools `inbox` and `answer`. Store schema v4, migrated in place.

## 0.1.0 — what a company learns now outlives three days

- **Durable memory.** A company remembered exactly the last three end-of-day
  summaries. That guard is right — a `--loop` company that never re-read them
  would plan each morning as if it had just been born — but a three-day horizon
  erases everything it learns about its market. The CEO and strategy agents now
  carry a `remember` tool, and the most relevant facts are recalled into each
  prompt.
- **Kept apart from yesterday.** `ctx.memory` is still the three summaries, read
  positionally by `set_daily_plan`. Merging durable facts into that list would
  have made `memory[0]` a fact instead of yesterday, and broken that tool without
  breaking a test.
- **No vector store, no new dependency.** Ranking and deduplication reuse
  `safety.hash_embed`, the dependency-free bag-of-tokens embedding already
  written for the loop guard. It catches an observation restated with different
  word order, casing or punctuation — which is what an agent asked the same
  question daily actually produces — and deliberately does *not* catch true
  paraphrase: loosening it that far would start merging facts that only sound
  alike, which loses more than it saves. The docstring and a test say so rather
  than letting the code imply otherwise.
- **The operator owns it.** Facts are listed in the console and the CLI
  (`corparius memory`), pinnable and deletable. A pinned fact outranks relevance
  and is never dropped by `CORP_MEMORY_MAX`, which caps unpinned facts only —
  counting pinned ones against the cap would mean that pinning enough of them
  silently stops the company from learning. Store schema v3, migrated in place.
- **Fixed: the circuit breaker could talk itself down.** `record()` read
  `SAFE if mode == CONSERVATIVE else CONSERVATIVE`, so a session already in
  SECURISE dropped back to CONSERVATEUR on its very next spend. Whether a runaway
  day actually froze depended on whether it had spent an odd or an even number of
  times, and adding one tool to a playbook was enough to move that parity and
  stop the freeze. It now escalates monotonically while over the limit, and still
  recovers when the rolling 60s rate falls back under it. Found because adding
  `remember` to the CEO's playbook turned a passing orchestrator test red.
- **Consequence of that fix:** the example company's `tokens_per_minute` goes
  from 8000 to 60000. It is a wall-clock ceiling and a mock run compresses a
  whole simulated day into under a second, so the demo started tripping a limit
  no live run — where every tick waits on a real model — comes near. The number
  had been calibrated against a breaker that did not stick. The global default
  (10000) is unchanged, and it is the one to reason about for a company that is
  actually spending.

## 0.1.0 — a company can be taught its own trade

- **Skills.** A `SKILL.md` folder under `companies/<slug>/skills/` or the shared
  `skills/` directory carries what a company knows, in prose: the objection its
  market actually raises, the price it never discounts below, the two words its
  founder refuses to see in a post. Plugins already extended corparius with
  *code* — seven Python seams, an allow-list, a SHA-256 check — and none of that
  is a place to put a paragraph, so it was not being written down at all.
- **Selection is code, not a tool call.** OpenWorker injects a catalogue and lets
  the agent call `load_skill`; corparius has no tool-calling loop and wants none,
  so a skill is in scope when the tool about to run is named in its
  `allowed-tools`. That also makes the catalogue pointless in the prompt — the
  model cannot ask for a skill it was not given — so a turn pays for the skills
  that apply to it and nothing else. Cheaper than progressive disclosure, not
  merely as cheap.
- **Bounded and honest.** `CORP_SKILL_MAX_CHARS` (4000) caps what one prompt
  carries; past it a skill is truncated *and marked truncated* rather than
  silently halved. A company skill replaces a shared one of the same name instead
  of stacking with it — two sets of instructions for one job, both in context, is
  how a model gets told to do opposite things. Malformed frontmatter is skipped
  with a warning, as a plugin that fails to import already is.
- **Visible when wrong.** A skill naming a tool that does not exist is read,
  parsed, and then never applies — the one failure nothing else would show. The
  doctor warns about it by name. The console lists skills read-only in the
  Plugins tab (scope, size, tools reached, path) rather than becoming a second,
  worse text editor. Plugins can contribute directories via
  `PluginAPI.register_skill_dir`; a company skill still wins.
- On by default, unlike plugins: this is text read into a prompt, not third-party
  code executed in this process, so the supply-chain reason to ship it off does
  not apply. `CORP_SKILLS_ENABLED=false` turns it off.

## 0.1.0 — the gate says why, and stops idling the company

- **Permissions are decided, not flagged.** `corparius/permissions.py` replaces
  `tool.hitl or name in hitl_tools` with a resolution over three inputs: a risk
  class each tool declares (`read`, `write_local`, `external`, `code`, `money`,
  describing the effect on the outside world, not the subject), a mode
  (`CORP_PERMISSION_MODE`: discuss, interactive, auto, custom) and a threshold
  (`CORP_ASK_ABOVE`). It returns a `Decision` carrying the verdict *and* its
  motive, and the motive is written to the action log — a trail that says a tool
  ran but not why it was allowed to answers half the question you open it to ask.
- **Defaults are pinned to the old behaviour.** Threshold `external` plus the
  three shipped `hitl_tools` gates exactly `send_financial_transaction`,
  `publish_production_code` and `deploy_site`, as before. A test asserts that set
  literally, so a later change to a risk class cannot quietly widen or narrow
  what an existing company has to approve. Tighten with `CORP_ASK_ABOVE=read`.
- **A declared gate always wins.** Neither `auto` mode, nor `CORP_AUTO_ALLOW`,
  nor a standing rule can silence a tool named in `hitl_tools`. Otherwise the one
  guarantee the product makes would depend on the order you clicked in.
- **"Approve, and stop asking"** grants a standing rule scoped to one company and
  one tool, from the console or `corparius approve --always`; `run` expires with
  the run, `always` persists until `corparius rules --revoke`. Store schema v2,
  migrated in place.
- **Fixed: one unanswered approval idled the whole company.** A held tool broke
  the agent's turn, so a question about a payment stopped that agent from doing
  the nine other things in its playbook — and the backlog task behind it went
  back to `approved`, was claimed again next turn, and re-filed the same request.
  The company spent its budget re-asking and did nothing else until a human came
  back. Now a guard tripping halts the turn and a human being asked does not: the
  task is parked at `waiting` against the approval that would free it,
  `claim_next_task` skips it so the agent moves to the next one, and each tick
  reads back answers arriving from the console, the CLI or an MCP host. Blocked
  work is reported apart from WIP — counted, so the board does not flatter
  itself; not charged against the pull limit, or four unanswered questions would
  stop the company starting anything else.
- **A tool already waiting is not asked about twice.** Checked before the draft
  rather than after, so no model call is spent producing a duplicate request. It
  does not widen the gate: matching an approval to an execution still compares
  parameters exactly, so an approved 12 EUR payment still cannot authorise a
  12000 EUR one.

## 0.1.0 — what corparius takes from OpenWorker

- **A teardown of OpenWorker**, Andrew Ng's MIT-licensed desktop agent, in
  `docs/reverse-engineering/openworker.md`. It is the only comparable that shares
  corparius' self-hosted, bring-your-own-keys stance, so the dossier records four
  subsystems worth taking — risk-classed permissions, prose skills, persistent
  memory, a typed inbox — and argues, from the Polsia teardown, against taking its
  ReAct loop, its subagents or its OAuth connector fleet. The rule throughout:
  take the data model and the semantics, never the agency it grants the model.

## 0.1.0 — installable, formatted, and renamed to its own name

- **`pip install corparius`.** The package is now a proper distribution:
  `pyproject.toml` carries `[build-system]` (hatchling) and `[project]` metadata,
  and installing it puts a `corparius` command on PATH. Runtime deps stay the two
  the project has always had, `requests` and `PyYAML`; encryption and the MCP
  server remain optional extras (`corparius[secrets]`, `corparius[mcp]`).
- **The package is `corparius`, renamed from `app`.** `app` was generic enough
  that a `pip install` would have dropped a colliding top-level module into
  site-packages, which is why it was never installable. Running from source is
  unchanged (`python -m corparius.cli`, or the launchers).
- **Resources and state resolve correctly whether run from source, frozen, or
  installed.** A wheel has no sibling `companies/` or `plugins/` in
  site-packages, so the console HTML, the example company and the plugin registry
  ride inside it and are found there; the operator's store, `.env` and companies
  go to a per-OS directory, never into site-packages. A CI job builds the wheel,
  installs it clean and runs a day offline to keep that true.
- **`ruff format` and import sorting** are adopted across the tree and checked in
  CI, and `mypy corparius/` is clean at the default level.

## 0.1.0 — the console holds up under load and under a hostile tab

- **Fixed: concurrent writes lost rows.** The console built a new SQLite
  connection per HTTP request and never closed it, while the run loop wrote from
  a background thread. Measured on twelve concurrent writers, nine died with
  `database is locked`. One shared connection now serves the process, guarded by
  a re-entrant lock, with WAL enabled for the read-only settings layer and the
  CLI. Sharing it *without* that lock is worse than the original bug — threads
  land inside each other's transaction and rows vanish with no error — so the
  lock is load-bearing. Concurrent polls during a run went from 635 to 1940.
- **Fixed: any web page you visited could drive the console.** Binding localhost
  never protected against the browser already running on it: a hostile tab could
  `fetch()` `http://127.0.0.1:8600` and start a run, save provider keys, publish
  the site or delete a company. Writes now require `Sec-Fetch-Site`/`Origin` to
  say the request came from the console's own page. **No configuration, no login
  screen, no CSRF token**, and clients that send neither header (curl, scripts,
  the MCP server) still work, so offline use is unchanged.
- **Fixed: DNS rebinding.** `CORP_UI_ALLOWED_HOSTS` (new, environment/`.env`
  only — never the settings store, which it protects) pins the `Host` names the
  console answers to. Loopback binds need nothing.
- **Breaking, if you run behind a reverse proxy:** a bind off-loopback now warns
  in `doctor` until `CORP_UI_ALLOWED_HOSTS` names your hostname. Requests with an
  unrecognised `Host` get a 403 that names the variable to set. Loopback and
  Docker-with-published-ports are unaffected.
- **`CORP_UI_TOKEN` now covers reads.** It guarded mutations only, so with a
  token set `/api/settings` and `/api/company` still served company configs,
  paths and provider status to anyone. With no token set, nothing changes.
- **Request bodies are capped at 1 MiB**, malformed `Content-Length` is a 400
  rather than a 500, chunked bodies are refused, and the token comparison is
  constant-time.
- **The Docker image runs as a non-root user** and carries a `HEALTHCHECK`.
- **The console's two 60- and 85-line `if/elif` dispatch chains are one route
  table.** That duplication was why the token check existed in one of them only;
  a route is now authenticated unless it opts out, and a test pins the public set
  so a new exception has to be written down.
- **CI runs the platforms we ship**: Python 3.10/3.12/3.14 on Linux, 3.12/3.14 on
  Windows, 3.12 on macOS. Adds `pyproject.toml` (tool configuration only) and
  tests for the previously untested toolbox, roster, approval gate and backups.
  171 tests → 243.

## 0.1.0 — a double-click start, accessible, no raw tracebacks

- **Double-click launchers.** `start-windows.bat`, `start-macos.command` and
  `start-linux.sh` bootstrap everything without a terminal, and say plainly what
  to install if Python is missing. `.gitattributes` forces LF on them so a
  Windows checkout does not ship a CRLF shebang that fails on macOS/Linux.
  `start.py` now handles a missing `python3-venv` and a failed pip with an
  instruction instead of a traceback.
- **Accessibility pass.** Audited across every tab: no unnamed buttons, no images
  without alt, no duplicate ids, `lang` set, tabs already keyboard-navigable. The
  four inputs that relied on a placeholder alone (site headline, mail test
  recipient, local-server preset, delete confirmation) got real `aria-label`s, so
  a screen reader names them and the label survives typing.
- **Unexpected errors are a sentence, not a traceback.** The console's 500
  handlers and the background run worker now show a localized "something went
  wrong, see the server log" rather than `str(exc)`; the full detail is logged.

## 0.1.0 — works on a phone, and a friendlier first launch

- **The console is usable on a phone.** Operations and Providers overflowed a
  390px screen because `.stack` was an implicit-`auto` grid: one wide card (the
  action-log table) stretched the whole column and every sibling with it.
  Constraining the track to `minmax(0, 1fr)`, plus stacking the provider rows and
  wrapping the approval card, brings horizontal overflow to zero on all tabs.
  Desktop is unchanged.
- **A port already in use is a sentence, not a traceback.** `start.py` and the CLI
  probe the port before binding (allow_reuse_address makes the bind result
  unreliable, especially on Windows) and say plainly that another console is
  likely running, with how to pick a free port. `ui` exits non-zero cleanly.

## 0.1.0 — fewer papercuts, and a CEO that can act

- **The CEO chat can do things, not only answer.** When the operator asks to run
  a day, publish the site, back up, or switch to their Claude subscription, the
  reply comes with a confirm button. One structured call classifies the intent
  and writes the reply (dogfooding the harness); the button calls the same
  audited endpoint the UI buttons use, so nothing runs on the model's say-so and
  money still hits the HITL gate. In mock or on a weak model it degrades to plain
  conversation. Intent classification is provider-agnostic via the harness.
- **Diagnosis strings are bilingual.** Testing mail, Claude, a provider or Ollama
  in a French console now answers in French; the CLI stays English. One
  `corparius/i18n.pick(lang, en, fr)` keeps both strings at the call site.
- **A proactive diagnostics banner.** If the doctor reports a failure on load,
  the console surfaces it with a link to the fix, instead of leaving it unseen in
  a tab. Dismissible per session.
- **`.env.example` slimmed** to the bootstrap keys plus the LLM tiers, with a
  pointer to the console and docs. The console sets everything else, so the file
  is no longer a wall to read.

## 0.1.0 — starter templates

- **The wizard offers a business to start from.** SaaS, online shop, agency,
  newsletter — each prefills the ICP, channels, price and the right agents, so a
  newcomer edits a starting point instead of facing a blank ICP and price. The
  typed name and product still win over the template's examples. Blank is still
  an option. Templates live in `corparius/company.py`, one source for the console.

## 0.1.0 — a guided first run

- **A "Getting started" thread on the overview.** A blank powerful tool is now a
  path: connect a model (or stay in mock), run a day, make a decision. Each step
  reflects real state and ticks itself off; the card removes itself when the
  three are done, or when hidden. Not a tour and not a modal (both banned), just
  an honest status list. Staying in mock counts as step one done, since running
  offline is a real choice, not an unfinished one; and only the operator's own
  approve/reject completes the last step, never the company's own task
  completions.
- **The offline sales site no longer shows mock gibberish.** In mock mode the
  draft is the echoed prompt; feeding it as the site's H1 made the product look
  broken on first use. It now falls back to the company's own tagline.

## 0.1.0 — plug in any LLM, get the same shape out

### Same structure, whatever the model

`corparius/structured.py` is a provider-agnostic harness: ask ten models to draft a
post and you get ten shapes (prose, JSON, JSON in a fence, a preamble, a
refusal); the harness returns one validated dict every time. It works at the
text level (instruct, extract, validate, repair once, then a deterministic
fallback) rather than on any provider's native structured-output feature,
because the 14 free tiers, Anthropic and the Claude CLI each support that
differently or not at all — relying on it would fragment the very thing this
unifies. A tool opts in with a `schema`; `draft_social_post` is converted as the
first. The MockProvider answers structured prompts offline, so structure holds
with no network. The fallback keeps the agent turn alive when a weak local model
cannot produce JSON at all.

### Plug in an LLM without a shell

- **Use your Claude subscription in one press.** A card in Providers tests the
  `claude` CLI, then flips mock off, cloud on, Claude Code on, and points the
  tiers at `claudecode:`. It was four scattered settings plus hand-edited tier
  strings that nobody found. **Windows fix:** the CLI npm installs is
  `claude.cmd`, which subprocess cannot launch by bare name (WinError 2), so
  `claudecode:` was broken on Windows; every caller now uses the resolved path.
- **A Test button on every free-tier provider.** One minimal real call, a
  readable verdict, the fix named instead of the HTTP status. The 14 tiers were
  wired already; this is how you tell a good key from a typo.
- **Ollama from the console.** A card shows what is installed and which tier
  models are missing, and pulls them in the background.
- **Local server presets.** LM Studio, Jan, Ollama's OpenAI endpoint, llama.cpp,
  vLLM and LocalAI fill the `custom:` endpoint from a dropdown.

### Design: blue, not yellow

The interface was too warm — ivory text and an amber accent read as a generic AI
dashboard. It is now one blue instrument: the owner's blue ramp carries
structure, action and selection; the only non-blue accents are petrol for health
and red for danger. Ivory and amber are gone. See DESIGN.md.

Also fixed: a `locale`/`stateBadge` scope bug introduced when render() was split,
which threw on every log render and surfaced as a connection-error banner.

## Earlier unreleased — the console runs the whole thing

The console can now set everything corparius reads. No file needs a text editor.

### Read this before you upgrade

**Your `.env` starts working.** Nothing in the Python ever read it: `start.py`
copied `.env.example` into place and only docker-compose loaded it, so on the
documented `python start.py` path every line of that file was inert and the app
silently ran in mock mode. It is loaded now. If your `.env` says
`CORP_LLM_MOCK=false` with a cloud provider enabled, **the next start goes live
and spends money.** That is the fix working, so it is announced rather than
sprung: `start.py` prints the resolved mode before serving, and the doctor
reports it.

**Settings saved from the console used to vanish on restart.** They were written
to `os.environ` and to that unread `.env`. They are stored now, and survive.

**docker-compose no longer uses `env_file:`.** It injected every line of `.env`
into the process environment, the highest-precedence layer, which would leave the
settings screen entirely read-only. The `.env` mount is read directly instead, so
your values are unchanged; only their precedence is, in the direction that lets
the console work. The `loop` service gained the same mount.

**Two tests change meaning by design.** `test_providers_never_leak_keys_and_persist_env`
asserted that a saved key landed in `.env` and in `os.environ`; neither is true
now. See `tests/test_cfg.py` for the layering the suite asserts instead.

### Settings

- `corparius/cfg.py`: one resolver, four layers, highest wins — process environment,
  then settings saved from the console, then `.env`, then the default in the
  code. `.env` is deliberately not loaded into `os.environ`: that would outrank
  the console and silently ignore what the operator just saved.
- `Settings()` re-reads the environment. Every field evaluated `os.environ.get`
  at class-definition time, so a second instance handed back the values the
  process started with and every console edit looked inert. `_fresh_settings()`
  now does what its docstring always claimed.
- A settings screen driven by `corparius/settings_spec.py`: adding a setting is one
  row, not an HTML change. Each field shows which layer answers for it and goes
  read-only when the process environment pins it. Nothing is ignored in silence.
- Secrets are write-only and stored in the clear in `data/corparius.sqlite`, as
  they were in `.env`. They are therefore in `backup` zips; the panel and the
  doctor say so. The store is chmod 0600 on POSIX.
- The page sends `X-Corp-Token` and offers to enter one on a 401. Setting
  `CORP_UI_TOKEN` used to make the console read-only, because the client never
  sent the header.

### Company

- `corparius/company.py`: one loader, one validator, one atomic writer, shared by the
  CLI, the console and the MCP server. An empty `company.yaml` raised
  `AttributeError` from inside `setdefault(None)`; it now opens for repair with
  its problems named.
- A full editor: every field, including the eight the wizard hardcoded out of
  reach (price, billing, payment link, channels, pains, HITL tools, tokens per
  minute, ad budget). Saving rewrites the file from those fields, so hand-written
  comments are not kept.
- Delete asks you to type the slug and moves the config to `companies/.trash/`.
- `icp.channels` and `budgets.daily_ad_spend_eur` were written by the example and
  the wizard and read by nobody: every post claimed LinkedIn and every ad review
  claimed "0 EUR/day, within cap" whatever the config said. Both are wired up.

### Mail

- One account, both directions. Pick a provider, give the address and an app
  password; hosts and ports are derived. "Test this account" sends a real message
  and reads the real mailbox, and reports the two halves separately.
- **Port 465 never worked.** The code always called `starttls()`, but 465 is
  implicit TLS — and 465 is what Gmail, Fastmail and Infomaniak document. It
  failed with an error no operator could read.
- Diagnostics name the fix, not the protocol.
- `corparius/mailbox.py`: IMAP reading, read-only. corparius never marks a message
  seen, moves it or deletes it. `triage_inbox` returned a fixed "3 support,
  1 sales, 0 urgent" for every company, configured or not; it reads now.
- New `scan_replies` tool and an `outreach` table: the company knows which
  prospects answered. It could email people and never learn whether anyone
  replied, which is the one signal it exists to chase.

### Runtime

- **A `--loop` company was amnesiac.** `memory` was read once before the loop and
  never again, so it wrote an end-of-day summary every day and read none of them,
  planning each morning as if newborn. Verified over six days before and after.
  It is re-read at each day boundary, along with the settings.
- A loop can be started and stopped from the console. Stopping lands within a
  tick, and only the hours actually played are banked.
- Deploy, backup, a site headline and task editing are in the console. A deploy
  that published nothing was wrapped in `_ok()` and logged as a success; it now
  returns a failure and says which providers were skipped and why.
- The doctor gained the checks that matter: `.env` and its precedence, settings
  the environment shadows, secrets at rest, deploy order (`local` is always
  available, so anything after it never runs), and a **failure** when the console
  is bound off-localhost with no token.

### Design

- The blue ramp (#002FA7, #263F7F, #4C7EFF) carries structure. Selection is now a
  role of its own — focus, active tab, toggles, links — which is what leaves amber
  to mean the one primary action in view.
- What waits on your decision leads the pulse, reads sand, and takes you there.
- Motion conveys state: a view arrives once per navigation, a decision leaves the
  queue, a number travels to its new value. Nothing pulses or loops idle.
  `prefers-reduced-motion` collapses transitions **and** animations; it only ever
  killed transitions before.
