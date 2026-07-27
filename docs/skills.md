# Compétences

Une compétence est ce que votre entreprise sait d'un métier, écrit pour l'agent qui l'exerce. C'est de la prose: pas de Python, pas de dépendance, rien d'exécuté. Les plugins étendent corparius avec du code; les compétences l'étendent avec du savoir.

La distinction compte parce qu'une micro-entreprise produit du second dès son premier jour. La manière dont sa prospection est tournée, l'objection que son marché soulève réellement, le ton que son fondateur veut: rien de tout cela n'est du code, et exiger un paquet Python pour le porter revient à exiger qu'il ne soit pas écrit.

## Où les mettre

```
companies/<slug>/skills/<nom>/SKILL.md   pour une seule entreprise
skills/<nom>/SKILL.md                    pour toutes celles de cette machine
```

Un gabarit commenté est fourni dans `packaging/skill-template/SKILL.md`, et l'entreprise d'exemple en embarque une, `companies/example/skills/outreach-voice/`.

Une compétence d'entreprise portant le même `name` qu'une compétence partagée la **remplace** au lieu de s'y ajouter. Deux jeux d'instructions pour le même métier, tous les deux dans le contexte, c'est la façon dont un modèle se fait dire de faire l'inverse de ce qu'on lui demande.

Un plugin peut contribuer un répertoire de compétences via `PluginAPI.register_skill_dir`. Ces répertoires sont cherchés en premier, donc une compétence d'entreprise du même nom garde le dernier mot: c'est la personne qui exploite l'entreprise qui tranche.

## Le fichier

```markdown
---
name: outreach-voice
description: Comment CVBoost écrit à un inconnu, et ce qu'il ne prétend jamais.
allowed-tools: send_outreach, draft_support_reply
---

Écrire à une personne, à propos d'un problème qu'elle a déjà eu...
```

`name` identifie la compétence, et prend par défaut le nom du dossier. `description` est ce que la console affiche. `allowed-tools` accepte une liste séparée par des virgules ou une liste YAML.

`allowed-tools` est la partie qui décide de tout: le corps du fichier n'entre dans l'invite que si l'outil sur le point de tourner y figure. Omettre la clé rend la compétence applicable à tous les outils, ce qui convient à une connaissance générale sur l'entreprise et ne convient pas à des instructions sur un métier précis.

Un fichier sans en-tête est lu entièrement comme corps, et prend le nom de son dossier. Une note écrite à la main reste donc utilisable avant que son auteur ait lu quoi que ce soit de cette page.

## Comment la sélection est faite

C'est ici que corparius s'écarte d'OpenWorker, dont le sous-système est par ailleurs le modèle de celui-ci (voir `docs/reverse-engineering/openworker.md`). Là-bas, un catalogue de noms et de descriptions est injecté, et l'agent appelle un outil `load_skill` quand il juge une compétence pertinente. Corparius n'a pas de boucle à appel d'outils et n'en veut pas: la pertinence est décidée par le code, une compétence est en portée quand l'outil sur le point de tourner est nommé dans son `allowed-tools`.

Cela rend le catalogue inutile dans l'invite: le modèle n'a aucun moyen de réclamer une compétence qu'on ne lui a pas donnée, donc lui énumérer les autres serait des jetons dépensés pour une offre que rien ne peut saisir. Le catalogue est tout de même construit, pour la console. Le résultat est moins cher que la divulgation progressive, et pas seulement aussi peu cher: un tour paie les compétences qui s'y appliquent et rien d'autre.

## Écrire un corps utile

Tout ce qui suit l'en-tête part dans l'invite système de l'agent. Écrivez ce que vous diriez à une nouvelle recrue son premier jour, pas ce que vous mettriez dans une plaquette.

`CORP_SKILL_MAX_CHARS` plafonne ce qu'une invite transporte (4000 caractères par défaut). Au-delà, une compétence est tronquée et signalée comme tronquée plutôt qu'écartée en silence, donc ce sont les premiers paragraphes qui survivent: mettez la règle qui compte en premier.

Préférez ce qui est vrai de *votre* marché: l'objection que vous recevez réellement et la réponse qui marche réellement, le prix sous lequel vous ne descendez jamais et pourquoi, les deux mots que votre fondateur refuse de voir dans un message, le segment qu'il faut laisser tranquille. Évitez de répéter ce que l'agent lit déjà dans `company.yaml` — son nom, son offre, son prix et ses canaux sont dans chaque invite.

## Vérifier

`corparius doctor` compte les compétences chargées et **avertit** sur celles dont `allowed-tools` nomme un outil qui n'existe pas: ce fichier est lu, analysé, puis comparé à un nom qui n'existe nulle part, et c'est la seule panne que rien d'autre ne rend visible.

La console les liste dans l'onglet Plugins, en lecture seule: nom, portée, taille, outils atteints, chemin. Une compétence est un fichier que l'exploitant a écrit; la console dit lesquelles sont en jeu, elle ne devient pas un deuxième éditeur de texte en moins bien.

`CORP_SKILLS_ENABLED` coupe l'ensemble. Contrairement aux plugins, c'est activé par défaut: du texte lu dans une invite n'est pas du code tiers exécuté dans ce processus, donc la raison de chaîne d'approvisionnement qui justifie l'inverse ne s'applique pas.
