# Recherche de leads

corparius recherche des prospects via des sources interchangeables, essayées dans un ordre configurable, avec repli. Un jeu de données local est toujours disponible et fonctionne hors ligne. Une source navigateur, en Chromium headless, lit une page publique que vous configurez.

## Responsabilité

Vous êtes l'opérateur. Respectez les conditions d'utilisation de chaque source et le droit applicable, dont le RGPD. Préférez les données publiques et les API officielles. Le module ne contient aucune technique de contournement des protections d'un site.

## Sources

La source locale lit un fichier CSV (colonnes name, company, title, email) désigné par CORP_LEADS_CSV. La source navigateur ouvre CORP_LEADS_URL en Chromium headless, le marqueur {query} étant remplacé par la requête, extrait les adresses de contact du texte rendu et requiert Playwright. Le navigateur tourne toujours en mode headless.

## Ordre et repli

CORP_LEAD_SOURCES fixe l'ordre, par défaut "browser,local". Une source indisponible ou sans résultat passe la main à la suivante, et le premier résultat non vide est retourné. En gardant local en fin de chaîne, la recherche renvoie un résultat exploitable dès qu'un jeu local existe.

## Contact

L'agent de prospection appelle find_targets pour obtenir les leads, posés sur le contexte du cycle, puis send_outreach rédige l'accroche et l'envoie à chaque lead via le SMTP configuré (voir integrations.md), sous le garde-fou de délivrabilité et un plafond par cycle (CORP_OUTREACH_MAX_PER_RUN). Sans SMTP configuré, l'envoi retombe sur une adresse de test puis sur le mode mock.
