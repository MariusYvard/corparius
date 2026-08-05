# 0005 — Le prompt du CLI Claude part sur stdin

## Contexte

Le fournisseur `claudecode:` appelle le CLI local `claude -p`, ce qui donne accès aux modèles
Anthropic via l'abonnement, sans crédits API. Le prompt partait en argument de ligne de
commande.

## Ce qui a été mesuré

Sur Windows, le CLI installé par npm est `claude.CMD`, donc chaque appel passe par cmd.exe,
qui **coupe la ligne de commande à 8 191 caractères**. Mesuré sur le CLI 2.1.220 :

- 8 000 caractères de prompt atteignent le modèle ;
- **8 100 échouent** avec `claude CLI exited 1: La ligne de commande est trop longue`.

Ce n'est pas un cas limite : une entreprise avec des documents et des skills dépasse ça au
premier tour de son agent design. Et l'échec arrivait comme une erreur de fournisseur
ordinaire, donc le routeur passait à l'étape suivante — un modèle gratuit incapable de
produire du JSON. Le pin Opus de l'exploitant n'a jamais tourné une seule fois, et rien dans
le journal ne le disait.

Sur stdin : **25 268 caractères, rc 0**, mesuré.

## Décision

Le prompt part sur stdin (`claude -p` sans argument de prompt). Seuls les drapeaux restent
sur la ligne de commande. Le prompt système reste dans `--append-system-prompt` tant qu'il
tient dans `ARGV_BUDGET` (7 800 sur Windows, 128 000 ailleurs) ; au-delà il est **replié dans
le prompt plutôt que perdu**, parce qu'un appel qui perd en silence les règles de la maison
répond avec assurance dans la mauvaise voix.

## Coût

Une branche par plateforme sur un budget de caractères, et un cas de repli à tester.

## Où c'est appliqué

`corparius/llm.py:721-737` (le budget et sa mesure), `tests/test_claudecode_prompt.py`.
