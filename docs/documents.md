# Documents

Le vrai savoir d'une entreprise est rarement dans `company.yaml`. Il est dans une présentation, un cahier des charges, un tarif, la capture d'écran de la page d'un concurrent. Jusqu'ici rien de tout cela ne pouvait atteindre un agent: les seules entrées étaient la config, une compétence écrite à la main, et ce dont le modèle se souvenait par hasard.

Les compétences sont ce que l'entreprise sait, en prose. Les documents sont ce qu'elle a déjà, en fichiers.

## Où les mettre

```
companies/<slug>/documents/            ce que vous déposez
companies/<slug>/documents/written/     ce que ses agents écrivent
```

Le glisser-déposer de l'onglet Documents écrit dans le premier. Le second est rempli par les agents. Les deux comptent comme contexte; la séparation existe pour que la provenance se lise dans le chemin, et pour qu'un nettoyage de l'un ne supprime jamais l'autre.

Déposer un fichier à la main dans le dossier marche exactement pareil: rien n'est indexé, rien n'est mis en cache, le dossier est lu à la demande.

## Ce qui est lu, et sans quoi

Aucune dépendance nouvelle. Un PDF et un `.docx` sont des conteneurs zip dont les parties sont lisibles, un CSV est un CSV, et la bibliothèque standard suffit pour les cinq.

| Extension | Lu par |
| --- | --- |
| `.md` `.txt` `.markdown` `.rst` `.log` | lecture directe |
| `.pdf` | les opérateurs de texte non compressés que la plupart des exporteurs émettent |
| `.docx` `.pptx` `.xlsx` | le zip et son XML, mêmes trois lignes pour les trois |
| `.csv` | l'en-tête et un échantillon: mille lignes dans une invite sont du bruit |
| `.png` `.jpg` `.jpeg` `.webp` `.gif` | proposé aux modèles qui acceptent les images, jamais décrit ici |

## Ce qui n'est pas inventé

C'est la règle qui gouverne toutes les autres entrées et elle s'applique ici: **une extraction fausse est pire qu'aucune extraction.** Elle mettrait des mots inventés dans le contexte d'un agent, et cela ressemblerait exactement à du savoir.

Donc chaque échec porte un nom plutôt qu'un silence:

| État | Ce que la console dit |
| --- | --- |
| `no-text-layer` | scanné ou compressé: aucune couche de texte à lire |
| `no-extractor` | aucun extracteur pour ce format |
| `empty` | aucun texte dedans |
| `image` | proposé aux modèles qui acceptent les images |
| `os-error` | n'a pas pu être ouvert, avec ce que le système a répondu |

Un PDF scanné répond « aucune couche de texte » au lieu de rendre du bruit. Décrire une image demande un appel multimodal, donc l'image est proposée aux modèles qui la prennent et ignorée par les autres — jamais silencieusement jetée, jamais légendée par personne.

L'état voyage comme un **code**, pas comme une phrase. La console parle deux langues, et la phrase, elle, part dans une invite dont la langue est l'anglais: une seule des deux se traduit.

## Le budget d'invite, et ce qu'il laisse dehors

Le bloc envoyé aux agents est borné. Il roule sur chaque invite des agents qui le demandent, et ce projet a déjà appris ce qu'une compétence non cadrée de 3 815 caractères coûte par tour.

Deux plafonds, chacun dit à voix haute:

- **4 000 caractères par document.** Au-delà, le document est coupé et l'invite porte « first 4000 of 12345 characters »: un agent qui raisonne sur un document tronqué doit savoir qu'il l'est. La console montre les deux nombres, le réel comme un nombre et non comme une phrase.
- **6 000 caractères pour le bloc entier.** Le plus récent d'abord, donc un document déposé ce matin déplace celui du mois dernier plutôt que de ne jamais être atteint. Ce qui dépasse n'atteint aucun agent.

**C'est ce second plafond qui compte pour l'exploitant.** Une entreprise peut avoir douze documents au dossier et n'en donner que deux à ses agents. Mesuré sur neuf fichiers réels: quatre atteignent les agents, trois specs parfaitement lisibles sont hors budget et rien ne les lit. Rien dans le produit ne le disait avant que la carte existe.

`context()` et l'inventaire de la console partagent **une seule boucle de sélection**. Écrite deux fois elle aurait dérivé, et une console qui se porte garante d'un document qu'aucun agent n'a jamais vu coûte plus cher que le silence qu'elle remplace.

## Les agents écrivent aussi

C'est la moitié facile à manquer. Quatre outils produisaient une vraie prose et n'en gardaient que les 120 premiers caractères comme ligne de journal:

| Outil | Écrit |
| --- | --- |
| `draft_design_brief` | `written/design-brief.md` |
| `scan_competitors` | `written/competitor-scan.md` |
| `update_pricing` | `written/pricing-note.md` |
| `write_eod_summary` | `written/end-of-day.md` |

Le reste était jeté au moment de l'écriture — y compris pour l'agent qui en aurait eu besoin au tour suivant. Le brief de design mesuré passe de 120 à 512 caractères et revient dans l'invite du tour d'après.

Chaque écriture **remplace** la précédente au lieu de s'y ajouter: le dernier brief chasse l'ancien, parce qu'un dossier de dix-neuf briefs quasi identiques est le problème de la file de brouillons dans un autre costume.

Dans l'invite, un document est nommé par son chemin relatif et non par son nom de fichier. Un `design-brief.md` que vous avez déposé et celui que l'agent de design a écrit étaient deux en-têtes identiques dans la même invite, sans rien pour les distinguer; le chemin les sépare et dit au modèle lequel des deux l'entreprise a rédigé elle-même.

## Depuis la console

L'onglet **Documents** porte deux cartes.

**Ajouter des documents** est une zone de glisser-déposer, avec un vrai champ de fichier à côté pour qui n'utilise pas la souris. Un fichier part seul dans sa requête, en base64 dans le corps JSON que la console analyse déjà: pas de parseur multipart, donc toujours deux dépendances d'exécution. Un fichier par requête et non un lot, parce qu'un lot rendrait un seul verdict pour dix fichiers.

Ce que la page annonce — formats acceptés, taille limite — vient du serveur qui en décide. Une seconde copie de la liste dans le HTML serait une promesse que le serveur peut rompre.

Un refus n'est pas une requête ratée. `ok` qualifie la requête, et demander à ranger un `.zip` est une demande parfaitement formée: la réponse est `stored: false`, avec lequel de vos fichiers et pourquoi. Sont refusés le format sans extracteur, le fichier vide, le fichier au-delà de 6 Mo, et un nom commençant par un point — celui-là serait écrit puis ignoré pour toujours par la lecture, ce qui est le pire des trois états possibles.

**Ce que l'entreprise a sur ses dossiers** liste tout, le plus récent d'abord, avec par ligne: l'état vis-à-vis du budget, la provenance, le chemin, la date, le texte extrait derrière un dépli, et un bouton pour le retirer. L'en-tête donne le vrai total, jamais le total de ce qui est affiché — la liste est bornée à soixante et le dit quand elle coupe.

Retirer **déplace** dans `documents/.trash/` et ne détruit pas, comme une entreprise supprimée: vos fichiers ne sont pas à nous, et une pastille mal lue doit être réversible. La console dit où le fichier est parti.

Le point d'API n'est jamais sur le sondage de 5 secondes: il ouvre et extrait chaque fichier qu'il liste. Il se recharge à l'arrivée, au changement d'entreprise, à la fin d'un run, et sur le bouton.

## Vérifier

```bash
python -m pytest tests/test_documents.py tests/test_documents_api.py tests/test_documents_render.py -q
```

Le troisième fichier extrait le rendu livré de `webui.html` et l'exécute sous node: une pastille « hors budget » ne doit pas ressembler à « atteint les agents », la carte française ne doit pas fuir d'anglais, et un nom de fichier ne doit pas pouvoir fermer la balise qui le contient.
