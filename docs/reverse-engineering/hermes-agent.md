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

### 4. Le rappel n'a pas besoin d'un plongement bricolé

`store.recall` classe par `cosine(hash_embed(requête), hash_embed(fait + pourquoi))`, et sa
docstring justifie ce choix ainsi : pousser le tri dans SQL voudrait dire *« soit une
extension vectorielle, soit un LIKE qui compare des mots au lieu du sens »*.

C'est un faux dilemme, et il est vérifiable. **FTS5 est compilé dans le `sqlite3` de la
bibliothèque standard** — mesuré sur cette machine, SQLite 3.50.4, `CREATE VIRTUAL TABLE …
USING fts5` accepté, `ORDER BY rank` renvoyant un score BM25. Ce n'est ni une extension
vectorielle ni un `LIKE` : c'est un classement lexical réel, avec radicalisation et
pondération par rareté, à zéro dépendance. `hash_embed` est un sac de mots hachés écrit pour
la détection de boucles ; il rend un service correct sur quelques dizaines de lignes et
personne n'a mesuré ce qu'il vaut sur quelques centaines.

Les deux se composent plutôt qu'ils ne s'opposent : FTS5 pour rappeler, le cosinus pour
dédupliquer à l'écriture (`recall` s'en sert déjà à 0,95 pour refuser un doublon).

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

## Où ça s'inscrit

Rien de ceci n'est une étape nouvelle. Les quatre points tombent dans des étapes que le plan
de refonte prévoit déjà, et c'est la raison de les inscrire maintenant plutôt que de les
empiler après :

- l'outil d'écriture d'une compétence est une entrée du registre que **l'étape 3** coupe en
  deux (`domain/tools/spec.py` en données, `registry.py` en effets), et il vit dans
  `domain/skills`, où l'étape 3 envoie déjà `skillimport` ;
- le compte d'usage et la péremption sont des colonnes, donc un mixin et une migration à
  **l'étape 4**, avec le reste de `store/` ;
- le rappel FTS5 est une requête de la table `memory`, donc le même mixin, à la même étape —
  et c'est là que la docstring qui dit « soit une extension vectorielle, soit un LIKE » se
  corrige ;
- le curateur est un travail périodique du domaine, avec les mêmes garde-fous déterministes
  que Hermes (archiver, jamais effacer ; épinglé intouchable ; passe par modèle **désactivée
  par défaut**), et il se planifie comme le reste — donc `domain/`, après l'étape 3.
