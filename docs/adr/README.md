# Décisions d'architecture

Une décision par fichier, courte, et **datée de sa mesure**. Le format tient en quatre
sections : le contexte, la décision, ce qui a été mesuré, et ce que ça coûte.

Ces sept premières ne sont pas nouvelles. Six d'entre elles étaient déjà écrites — dans les
docstrings du code, avec leurs chiffres — et n'ont été qu'extraites ici pour être trouvables
sans lire 23 000 lignes. La septième est la seule vraiment prise aujourd'hui.

C'est délibéré, et ça dit quelque chose sur ce codebase : les décisions y sont documentées
là où elles s'appliquent, avec la mesure qui les justifie. Un ADR qui résumerait la
docstring en la remplaçant serait une perte. **Ces fichiers pointent vers le code ; ils ne
le remplacent pas**, et une décision qui change se change aux deux endroits.

| # | Décision | Mesure qui la porte |
| --- | --- | --- |
| [0001](0001-deux-dependances.md) | Deux dépendances d'exécution, et pas une de plus | `requests`, PyYAML |
| [0002](0002-une-connexion-verrouillee.md) | Une connexion au store, sérialisée par un `RLock` | 414 lignes gardées sur 3 200 |
| [0003](0003-wal-et-son-echec-avale.md) | WAL, et pourquoi son échec est avalé exprès | Un lecteur exclu par un écrivain |
| [0004](0004-trois-modes-de-distribution.md) | Trois modes de distribution, un seul résolveur | 9 endroits épelaient le même chemin |
| [0005](0005-le-prompt-sur-stdin.md) | Le prompt du CLI Claude part sur stdin | 8 000 passent, 8 100 échouent |
| [0006](0006-sept-coutures-de-greffons.md) | Sept coutures de greffons, consommées paresseusement | — |
| [0007](0007-les-couches-sont-des-rangs.md) | Les couches sont des rangs, tenus par un test | 4 arêtes montantes, 5 cycles |
