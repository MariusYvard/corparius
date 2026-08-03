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
| `.png` `.jpg` `.jpeg` `.webp` `.gif` | envoyé tel quel à un modèle qui sait le lire, jamais décrit ici (voir « Les images » plus bas) |

## Ce qui n'est pas inventé

C'est la règle qui gouverne toutes les autres entrées et elle s'applique ici: **une extraction fausse est pire qu'aucune extraction.** Elle mettrait des mots inventés dans le contexte d'un agent, et cela ressemblerait exactement à du savoir.

Donc chaque échec porte un nom plutôt qu'un silence:

| État | Ce que la console dit |
| --- | --- |
| `no-text-layer` | scanné ou compressé: aucune couche de texte à lire |
| `no-extractor` | aucun extracteur pour ce format |
| `empty` | aucun texte dedans |
| `image` | envoyé comme image à un modèle qui sait la lire |
| `os-error` | n'a pas pu être ouvert, avec ce que le système a répondu |

Un PDF scanné répond « aucune couche de texte » au lieu de rendre du bruit. Aucun texte n'est inventé pour une image : décrire une image demande un modèle qui la voit, donc c'est le fichier lui-même qui part.

L'état voyage comme un **code**, pas comme une phrase. La console parle deux langues, et la phrase, elle, part dans une invite dont la langue est l'anglais: une seule des deux se traduit.

## Le budget d'invite, et ce qu'il laisse dehors

Le bloc envoyé aux agents est borné. Il roule sur chaque invite des agents qui le demandent, et ce projet a déjà appris ce qu'une compétence non cadrée de 3 815 caractères coûte par tour.

Deux plafonds, chacun dit à voix haute:

- **4 000 caractères par document.** Au-delà, le document est coupé et l'invite porte « first 4000 of 12345 characters »: un agent qui raisonne sur un document tronqué doit savoir qu'il l'est. La console montre les deux nombres, le réel comme un nombre et non comme une phrase.
- **6 000 caractères pour le bloc entier.** Le plus récent d'abord, donc un document déposé ce matin déplace celui du mois dernier plutôt que de ne jamais être atteint. Ce qui dépasse n'atteint aucun agent.

**C'est ce second plafond qui compte pour l'exploitant.** Une entreprise peut avoir douze documents au dossier et n'en donner que deux à ses agents. Mesuré sur neuf fichiers réels: quatre atteignent les agents, trois specs parfaitement lisibles sont hors budget et rien ne les lit. Rien dans le produit ne le disait avant que la carte existe.

`context()` et l'inventaire de la console partagent **une seule boucle de sélection**. Écrite deux fois elle aurait dérivé, et une console qui se porte garante d'un document qu'aucun agent n'a jamais vu coûte plus cher que le silence qu'elle remplace.

## Les images

Pendant deux versions, ce module, la console, cette page et le README annonçaient tous qu'une image était « proposée aux modèles qui acceptent les images ». C'était faux : `documents.images()` n'avait aucun appelant, aucun signal de capacité vision n'existait, et rien n'envoyait jamais d'image à un modèle. Elle était listée, nommée, puis jetée. Ce qui suit décrit ce qui se passe désormais.

**Trois conditions, toutes requises.** Une image ne part que si :

1. **l'outil l'a demandée** — `Tool(sees_images=True)`, déclaré outil par outil. Une capture sert un brief de design et ne sert à rien pour rapprocher des paiements Stripe. Aujourd'hui : `draft_design_brief` et `scan_competitors` ;
2. **l'entreprise en a une** dans son dossier ;
3. **le modèle sait la lire.** Mesuré d'abord, déclaré ensuite.

**Mesuré bat déclaré, ici comme partout.** `corparius preflight` envoie une vraie image de test — un carré bleu sur jaune, généré en code, 79 octets, aucun binaire en dépôt — et demande les deux couleurs dans l'ordre. Une seule couleur serait devinable par un modèle qui ne voit rien, et une sonde qu'un modèle aveugle réussit ne mesure rien. Le verdict va dans `model_probes.vision_ok`, et **`NULL` est un troisième état** : « jamais demandé » n'est pas « ne voit pas », et confondre les deux ferait dire à la console qu'un modèle est aveugle parce que personne n'a vérifié.

À défaut de mesure, le catalogue : `architecture.input_modalities` arrivait déjà dans la réponse que `modelinfo.fetch` lisait, et était jeté. Mesuré sur le catalogue réel : **180 entrées sur 337 déclarent l'image en entrée, et seulement 5 d'entre elles sont gratuites** — ce qui compte pour un projet qui route vers le gratuit. Sans mesure ni déclaration, rien n'est envoyé : une image postée à un modèle textuel est payée puis jetée par le fournisseur.

**Donner des yeux à un seul rôle.** C'est là que la capacité était inatteignable : seuls trois paliers sont réglables, et neuf rôles sur dix prennent le leur dans l'un d'eux. Router l'agent de design vers un modèle multimodal voulait donc dire déplacer tout le palier normal. Mesuré sur une configuration réelle, l'échange était mauvais : **535 tok/s vers 49** pour le CEO, la prospection, le support *et* le design, afin de donner la vue à un seul d'entre eux.

Un rôle peut désormais être épinglé, dans la conversation avec le CEO, comme la cadence et la mise en veille :

> « pour le design, utilise openrouter:nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free »

Le pin est une directive `(kind="model", target=rôle, note=modèle)` par entreprise, relue à chaque tour — il prend effet au tour suivant, pas au redémarrage. Le reste du roster ne bouge pas.

**Le préfixe doit être écrit.** `local:gemma4:e4b`, pas `gemma4:e4b`. `llm._split` rabat exprès un préfixe inconnu sur `local` pour que les étiquettes Ollama fonctionnent dans les paliers — ce qui rend `opnerouter:typo` indiscernable d'une étiquette Ollama. Un pin validé par ce chemin accepterait la faute de frappe et enverrait tous les tours de ce rôle vers Ollama, ce qui se lit comme une journée lente et non comme une erreur. Le refus est donc **nommé dans la réponse**, pour que l'exploitant apprenne le préfixe au lieu de se demander pourquoi un rôle a ralenti.

**Chaque fournisseur dans son dialecte.** `content` reste une chaîne dans `messages` — `_flatten`, le Mock et le `system` d'Anthropic la joignent — donc les images voyagent dans un argument à part, jamais glissées dans un message. OpenAI-compatible : `image_url` en URI `data:`. Anthropic : un bloc `source` en base64. Ollama : son tableau `images`. Le CLI Claude Code ne peut pas en porter, le déclare (`accepts_images = False`) et n'en reçoit donc pas. `base64` est dans la bibliothèque standard : toujours deux dépendances.

Un fournisseur fourni par un greffon et écrit avant les images continue de fonctionner : le mot-clé est **absent** plutôt que passé vide, ce qui n'appelle jamais une signature à trois arguments avec un quatrième.

**Borné, et dit.** `CORP_IMAGE_MAX_PER_CALL` images par appel — deux par défaut — et 3 Mio chacune avant base64, qui coûte un tiers de plus. Ce qui dépasse n'est pas envoyé et est **nommé** dans le journal avec sa taille réelle, parce que « pas de troncature silencieuse » couvre une image laissée de côté comme un document coupé. Une image manquant en silence d'une invite, c'est un tour qui raisonne sur ce qu'il ne voit pas.

**Et zéro veut dire jamais.** C'est la raison d'être du réglage, plus que le nombre lui-même. Le texte d'un document est extrait sur votre machine ; une image, elle, doit en sortir pour être lue — et une capture d'écran peut contenir les données d'un client. Avant ce réglage, le seul refus disponible était `CORP_CLOUD_ENABLED=false`, qui coupe aussi tout le texte : rien ne permettait de garder le texte dans le cloud en refusant les images, alors que l'image est la plus sensible des deux. À zéro, les fichiers ne sont ni lus, ni encodés, et le journal le dit une fois par tour plutôt que de laisser croire qu'il n'y avait rien à envoyer.

Le plafond d'octets reste une constante : c'est une décision de forme, comme la taille maximale d'un dépôt. Le nombre d'images est un réglage parce que l'exploitant a une raison d'y toucher.

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
