# Pipeline de prospection et mémoire

Quatre briques prolongent la boucle autonome. Chacune suit le même motif que le reste du dépôt: des fournisseurs interchangeables avec repli, et une option locale qui fonctionne hors ligne.

## Enrichissement

Après la recherche, chaque lead passe par une chaîne d'enrichisseurs. L'enrichisseur local comble les manques hors ligne, une société déduite du domaine de l'adresse, une adresse devinée à partir du nom et d'un domaine connu (CORP_ENRICH_DOMAIN). Il n'écrase jamais une donnée déjà présente. Un enrichisseur par API se branche dans le même registre, la chaîne gardant le local en repli.

## Délivrabilité

Avant chaque envoi, un garde-fou vérifie deux choses. La liste de suppression (CORP_SUPPRESSION_FILE) écarte les adresses à ne pas contacter. Le plafond quotidien (CORP_OUTREACH_DAILY_CAP) limite le volume et sert de montée en charge progressive du domaine, à relever au fil du temps. Un envoi bloqué renvoie un motif clair au lieu de partir.

## Mémoire d'entreprise

La mémoire reste simple. Le journal d'actions sert de mémoire longue. Au démarrage d'un cycle, les derniers résumés de fin de journée sont chargés dans le contexte, et l'agent CEO formule le plan du jour en tenant compte de la veille. Aucun moteur de consolidation, aucune structure séparée.

## Veille de signaux

L'agent concurrence surveille des signaux d'achat par mots-clés, tirés des douleurs et du segment de l'ICP. La source locale lit un fichier (CORP_SIGNALS_FILE), la source navigateur ouvre CORP_SIGNALS_URL en Chromium headless. La responsabilité est la même que pour la recherche de leads, décrite dans leads.md.
