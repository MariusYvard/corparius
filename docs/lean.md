# Organisation lean

L'organisation des agents s'inspire des outils lean présentés dans les supports fournis (Arts & Métiers x Capgemini, Sustainable Manufacturing et Sustainable Supply Chain, 2025). Le principe commun est de livrer de la valeur en réduisant le gaspillage.

## Flux tiré et limite d'en-cours

Le lean produit en flux tiré: une tâche ne se lance que lorsque la demande existe, et les en-cours sont limités (principe du Kanban). Le CEO ne remplit donc pas le backlog sans borne. Sa création de tâches est plafonnée par CORP_WIP_LIMIT en-cours par rôle, ce qui évite la surproduction, premier gaspillage du lean.

## Cartographie du flux

À la manière de la Value Stream Mapping et du Takt Time, corparius mesure le flux. La commande flow donne le débit (tâches terminées), l'en-cours, le goulot d'étranglement (le rôle dont la file ouverte est la plus longue) et l'efficience en jetons par tâche terminée. La commande board affiche le tableau visuel par colonne (proposed, approved, in_progress, done).

## Amélioration continue

Le Kaizen et le cycle PDCA visent de petites améliorations régulières. L'agent stratégie exécute un pas kaizen: il lit les métriques de flux, repère le goulot et propose au CEO une tâche pour le desserrer. La décision reste au CEO, conformément à la gouvernance du backlog.

## Efficience des ressources

Le volet durable des supports insiste sur la réduction des ressources (les 6R: réduire, recycler, réutiliser, récupérer, redessiner, remanufacturer). Ici la ressource est le calcul. L'indicateur jetons par tâche terminée et la déduplication des tâches réduisent le gaspillage de calcul, équivalent numérique de la réduction de matière.

## Chasse au gaspillage

Le lean nomme sept gaspillages (muda): attente, mouvement, transport, corrections, surproduction, stock, surprocessing. corparius en suit deux mesurables, les corrections (actions en échec) et l'attente (validations humaines en file). La commande flow les affiche à côté du débit, pour viser la part à valeur ajoutée plutôt que le volume produit.

## Tour de contrôle

À la manière d'un MES (Manufacturing Execution System), l'orchestrateur exécute et surveille les tâches en temps réel. Les commandes board et flow tiennent lieu de tableau de bord d'atelier, une vue unique de l'état et du débit.

## Rituels

Le stand-up et le Genba walk du lean se retrouvent dans le rythme quotidien: le plan du matin et le résumé du soir du CEO, les commandes status et board tiennent lieu de management visuel et de synchronisation.

## Sources

Supports fournis: Arts & Métiers x Capgemini, "Sustainable Manufacturing" et "Sustainable Supply Chain", 2025, et l'aide-mémoire d'expertise associé.
