# 0003 — WAL, et pourquoi son échec est avalé exprès

## Contexte

`corparius/config/cfg.py` ouvre le store **en lecture seule** comme couche de réglages, et la CLI
doit pouvoir tourner pendant que la console est ouverte. Sous le journal de rollback par
défaut, un écrivain exclut les lecteurs, et SQLite renvoie `BUSY` immédiatement plutôt que
d'invoquer le gestionnaire d'attente quand deux connexions tentent d'élever un verrou en même
temps — donc attendre plus longtemps n'aide pas.

## Décision

`PRAGMA journal_mode=WAL` et `synchronous=NORMAL`, dans un `try/except sqlite3.Error: pass`.

## Ce qui a été mesuré, et pourquoi l'échec est avalé

WAL est enregistré dans l'en-tête du fichier : il se pose une fois et persiste.

Mais il n'est pas disponible partout — **certains systèmes de fichiers réseau refusent le
fichier de mémoire partagée dont WAL a besoin**. Un volume Docker sur un backend inhabituel
doit se dégrader vers l'ancien comportement plutôt que refuser de démarrer. C'est le seul
`except: pass` de ce module, et il est délibéré.

`busy_timeout=5000` est posé inconditionnellement : Python applique déjà 5 s via
`connect(timeout=5.0)`, et l'écrire empêche que ça change en silence sous nos pieds.

## Coût

Deux fichiers annexes (`-wal`, `-shm`) à côté de la base, dont la sauvegarde doit tenir
compte.

## Où c'est appliqué

`corparius/store.py:412-435`.
