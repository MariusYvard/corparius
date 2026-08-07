# Hermes Agent

Hermes Agent est l'agent publié par Nous Research. Ce n'est pas un comparable produit de
corparius : il ne prétend pas faire tourner une entreprise, il fait tourner *un* agent, très
bien outillé — plus de quarante outils, sept back-ends de terminal (local, Docker, SSH,
Singularity, Modal, Daytona, Vercel Sandbox), une passerelle unique vers Telegram, Discord,
Slack, WhatsApp et Signal. Rien de tout cela n'est transposable, et rien de tout cela n'est
l'intérêt.

L'intérêt est une seule phrase de son README : **« a closed learning loop »**. Hermes est le
premier de ces dépôts à traiter l'apprentissage d'un agent comme un sous-système à part
entière, avec ses déclencheurs, ses garde-fous et — c'est la partie que personne d'autre n'a
— son entretien. Corparius a la moitié consommatrice de cette boucle, complète et testée, et
lui manque l'autre moitié.

## Le mécanisme, tel qu'il est écrit

Trois pièces, dans cet ordre.

**`agent/learn_prompt.py` — écrire une compétence.** La commande `/learn` prend une entrée
libre et, quand elle est vide, vaut par défaut *« the workflow we just went through in this
conversation »*. L'agent rassemble ses sources avec les outils qu'il a déjà, puis rédige **un
seul `SKILL.md`** par l'outil `skill_manage`. Le format est contraint durement : nom en
minuscules-tirets ≤ 64 caractères, description *« ONE sentence, ≤60 characters, ends with a
period »* — le compte de caractères est appliqué, pas suggéré —, et un corps dont les
sections sont dans un ordre imposé : intro, When to Use, Prerequisites, How to Run, Quick
Reference, Procedure, Pitfalls, Verification.

**`agent/background_review.py` — le déclencheur.** Après un tour de conversation, un agent
*forké* rejoue la session et décide seul s'il faut écrire en mémoire ou corriger une
compétence. Il écrit directement dans les magasins ; la conversation principale n'est pas
touchée. Par défaut il tourne **sur le même modèle que le parent, pour réutiliser le cache
de préfixe chaud** ; routé vers un modèle moins cher, il rejoue un digest compact des
messages anciens et garde les tours récents verbatim.

Deux phrases de ce prompt méritent d'être citées, parce qu'elles disent le contraire de ce
qu'on écrirait spontanément :

> Be ACTIVE — most sessions produce at least one skill update, even if small. A pass that
> does nothing is a missed learning opportunity, not a neutral outcome.

> « Nothing to save. » is a real option but should NOT be the default.

Et le garde-fou, qui est la chose la plus transférable du dépôt entier :

> Do NOT capture (these become persistent self-imposed constraints that bite you later when
> the environment changes)

suivi des catégories exclues : les échecs dépendants de l'environnement, et les échecs
transitoires.

**`agent/curator.py` — l'entretien.** C'est la pièce qui rend les deux premières viables, et
sa docstring nomme le mode de défaillance à l'avance : sans elle on obtient *« hundreds of
narrow skills where each one captures one session's specific bug »* au lieu d'une
bibliothèque d'instructions au niveau de la classe. Le curateur tourne sur inactivité —
`interval_hours` 7 jours, `min_idle_hours` 2 heures — et fait deux choses de nature
différente :

- des transitions **déterministes, sans modèle** : périmé après `stale_after_days` 30,
  archivé après `archive_after_days` 90 sans usage, jamais pour une compétence épinglée ou
  citée par une tâche planifiée, et jamais pour une compétence encore inutilisée avant 30
  jours ;
- une passe de consolidation **par modèle**, `curator.consolidate` à **false par défaut** :
  elle repère les grappes par préfixe (`pdf-*`, `anthropic-*`) et fusionne sous une compétence
  parapluie, en rétrogradant le contenu trop étroit vers `references/`, `templates/` ou
  `scripts/`.

Règle dure : **il n'efface jamais, il archive**. Et il écrit un rapport par passe, lisible par
une machine (`run.json`) et par une personne (`REPORT.md`), avec les instructions de
récupération.

## Ce que corparius a déjà, mesuré

Il faut le poser avant de conclure quoi que ce soit, parce que la moitié consommatrice existe
et est plus solide que ce que le README de Hermes laisse deviner du sien.

`corparius/skills.py` définit une compétence comme un dossier à `SKILL.md` avec en-tête, la
parse (`parse`, `parse_text`), la porte à un outil (`applies_to`, `core_for`), la charge par
entreprise (`SkillLoader.for_company`), la sélectionne **par le code et non par le modèle**
(`for_tool`, `context_for`) et — la bonne surprise — mesure déjà le coût :
`always_on_chars()` compte les caractères qu'une compétence non portée fait payer à **chaque**
prompt, avec une docstring qui dit pourquoi : *« un dossier de compétences non portées est un
impôt permanent sur le budget de jetons »*.

En face, le côté producteur :

| Ce que Hermes fait | Ce que corparius fait |
| --- | --- |
| Un agent écrit un `SKILL.md` | **Aucun.** `write_skill`, `create_skill`, `save_skill` : zéro occurrence dans le paquet |
| Un fork rejoue la session après le tour | `remember`, un outil de playbook porté par deux rôles |
| L'entrée est ce qui s'est passé | L'entrée est la question « qu'avez-vous appris aujourd'hui ? » |
| Compte d'usage, péremption, archive | **Aucun.** Ni `use_count`, ni `last_used`, ni archive |
| Consolidation par un curateur | Sans objet, faute de production |

## Ce que corparius en tire

Quatre choses, et une refusée.

### 1. La boucle est fermée sur des faits, pas sur des procédures

`remember` écrit un fait : *« ce qui reste vrai le mois prochain — sur le marché, l'offre ou
les clients »*, plafonné à 200 caractères plus 200 de justification. C'est de la connaissance
déclarative. Une compétence est de la connaissance **procédurale** : quand s'en servir, la
procédure, les pièges, la vérification. Les deux ne se remplacent pas, et corparius n'a que
la première.

C'est la forme de défaut que ce projet traque déjà sous un autre nom : **atteignable et jamais
atteint**. Tout le chargeur de compétences existe, il est testé, il a même son compteur de
coût — et rien dans le produit ne peut y écrire. Seul l'opérateur peut, à la main.

### 2. Le déclencheur est un calendrier, pas une expérience

`remember` part parce qu'un tour de playbook est arrivé, et son prompt demande *« qu'a appris
l'entreprise aujourd'hui »* à un modèle qui n'a pas la trace de la journée sous les yeux. Il
ne peut produire que ce qu'il peut reconstituer.

C'est exactement le défaut de `plan_from_documents` lisant `end-of-day.md` : **l'entrée est un
résumé, pas les événements**. La correction est la même — passer ce qui s'est réellement
produit, pas une invitation à s'en souvenir.

### 3. Le garde-fou négatif, à reprendre mot pour mot

> ces choses deviennent des contraintes permanentes auto-imposées qui vous mordent plus tard
> quand l'environnement change

Corparius s'est déjà fait mordre deux fois par cette forme. La contrainte
`promesse-clinique` voyageait sur les 36 appels d'outils d'une passe de playbook complète —
48 % de caractères économisés une fois découpée, soit 66 423 caractères. Et
`TRIES_BEFORE_STAND_DOWN` existe précisément parce qu'une boucle réessayait une chose que
l'environnement ne permettait pas.

Sans cette règle, la première compétence qu'un agent écrira sera « le serveur SMTP ne répond
pas », et l'entreprise portera cette croyance pour toujours.

### 4. Une docstring qui écarte une option qu'elle n'a pas essayée — mesuré, puis abandonné

`store.recall` classe par `cosine(hash_embed(requête), hash_embed(fait + pourquoi))`, et sa
docstring justifiait ce choix ainsi : pousser le tri dans SQL voudrait dire *« soit une
extension vectorielle, soit un LIKE qui compare des mots au lieu du sens »*.

Ce dilemme est faux, et c'est vérifiable : **FTS5 est compilé dans le `sqlite3` de la
bibliothèque standard** — SQLite 3.50.4, `CREATE VIRTUAL TABLE … USING fts5` accepté,
`ORDER BY rank` renvoyant du BM25. Ni extension vectorielle, ni `LIKE`, et zéro dépendance.

**Ma conclusion l'était aussi.** J'en ai déduit qu'il fallait donc remplacer le cosinus ici.
Mesuré sur la mémoire réelle de `vigil` — 55 faits, 13 933 caractères, fait moyen 137
caractères — c'est non, pour une raison qui n'a rien à voir avec la qualité du classement :

- **la requête est un prompt entier**, pas des mots-clés. `agents._recall` passe
  `tool.draft_prompt(ctx)`, de 40 à 613 caractères. `MATCH` prend une expression, donc
  l'utiliser demande d'écrire un extracteur de mots-clés — et celui de la mesure a eu besoin
  d'une liste d'arrêt tenue à la main. Une heuristique de plus, pas une de moins ;
- **il ne remplit pas le top k** : sur quatre prompts réels, 5, 5, **2 et 1** candidats ;
- recouvrement de 0 à 2 sur 5, et **aucune donnée étiquetée** pour trancher.

Ce que la mesure a confirmé, en revanche : le classement actuel **discrimine** — écart de 0,32
à 0,41 entre le meilleur et le pire, médiane nettement sous le meilleur. `hash_embed` compare
des sacs de mots, et un prompt est un sac de mots. La docstring dit maintenant cela, et FTS5
reste le bon outil pour une barre de recherche, ce que ceci n'est pas.

C'est la valeur d'une exigence que le plan portait déjà : *la migration doit venir avec sa
mesure, sinon on remplace une intuition par une autre.* Elle a coûté une heure et évité un
mauvais échange.

### Ce qui est refusé

**Le fork après chaque tour.** Hermes le peut parce qu'un tour est une conversation avec une
personne, et parce que son fork réutilise le cache de préfixe chaud du parent — le coût
marginal est faible. Corparius fait tourner **dix rôles sur une boucle de ticks sans
personne devant**, sur un abonnement mesuré en fenêtres d'usage. Un fork par tour d'agent
doublerait les appels de la journée pour produire, la plupart du temps, « rien à retenir ».

La cadence est déjà le levier de coût de ce produit — c'est le raisonnement écrit dans
`claudecli.HARD_TIER` : Opus sur le palier le moins fréquent, parce que le modèle le plus cher
doit être celui qu'on appelle le moins. L'apprentissage suit la même règle : il s'accroche à
la frontière de journée que corparius a déjà, là où le CEO écrit son résumé, avec la trace de
la journée en entrée. Une passe par jour et par entreprise, pas une par tour.

**Et le curateur n'est pas optionnel.** Chez Hermes, une compétence de trop coûte un dossier.
Chez corparius, une compétence non portée coûte des jetons **sur chaque prompt de chaque
tour** — `always_on_chars()` est déjà là pour le dire. Livrer la production sans l'entretien
serait construire une fuite dont le compteur existe déjà.

## Ce qui a été livré

Rien de ceci n'a été une étape nouvelle : les quatre points sont tombés dans des étapes que le
plan prévoyait déjà, ce qui était la raison de les inscrire plutôt que de les empiler après.

| Point | État | Où |
| --- | --- | --- |
| Le compte d'usage | **fait**, schéma 17 | `store.record_skill_use`, appelé depuis `SkillLoader.context_for` — pas depuis `for_tool`, parce qu'afficher une compétence n'est pas l'utiliser |
| L'outil d'écriture | **fait** | `tools/effects.write_skill`, sur le playbook du CEO, avec la portée fixée par le code |
| Le garde-fou négatif | **fait** | `tools/effects.NEVER_RECORD` |
| Le curateur | **fait** | `corparius/curator.py`, au passage de journée, sans passe par modèle |
| Le rappel FTS5 | **abandonné, mesuré** | voir le point 4 ci-dessus |

Trois choses ont été décidées à l'exécution et méritent d'être notées, parce qu'aucune n'était
dans l'étude :

- **la portée d'une compétence écrite par un agent est fixée par le code**, jamais par le
  modèle : c'est l'outil qui a échoué. Une compétence non portée est donc *impossible* à
  produire, ce qui retire structurellement le seul risque que cette fonctionnalité posait —
  l'impôt sur chaque prompt de chaque tour ;
- **le compteur a été livré avant le producteur**, parce que le curateur ne peut rien décider
  sans lui. Livrer dans l'autre ordre, c'était construire la fuite à côté de sa jauge ;
- **`forget_skill_use` est un vrai bug évité** : sans lui, une compétence réécrite sous le même
  nom héritait d'un `last_used` d'avant l'archivage, donc le balayage suivant l'archivait
  aussitôt — la compagnie répondant à une question et se faisant retirer la réponse.
