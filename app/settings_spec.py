"""The registry of settings the console may write.

One row per setting, and everything downstream reads from here: what the API
accepts, what the page renders, which fields are secret, which need a restart.
Adding a setting is one row, not an HTML change.

The keys are the same environment variables corparius has always read, so the
console is not a second configuration system: it writes layer 2 of app/cfg.py
(see the precedence table in the README), and anything you export in your shell
still wins and is shown as read-only rather than quietly overwritten.
"""
from __future__ import annotations
from dataclasses import dataclass

from . import cfg
from .llm import OPENAI_COMPAT_PROVIDERS

# Groups, in the order the page shows them. `warn` marks the ones whose keys
# authorise real-world side effects, and carries the banner text.
GROUPS: list[dict] = [
    {"name": "access", "label_en": "Console access", "label_fr": "Accès à la console",
     "help_en": "Where the console listens and who may use it. These apply on restart.",
     "help_fr": "Où la console écoute et qui peut s'en servir. Effectif au redémarrage."},
    {"name": "inference", "label_en": "Local inference", "label_fr": "Inférence locale",
     "help_en": "The Ollama server behind every local tier and the loop guard's embeddings.",
     "help_fr": "Le serveur Ollama derrière chaque palier local et les embeddings du garde-boucle."},
    {"name": "safety", "label_en": "Safety and cadence", "label_fr": "Sécurité et cadence",
     "help_en": "The ceilings that stop an agent running away with your budget.",
     "help_fr": "Les plafonds qui empêchent un agent d'emballer votre budget."},
    {"name": "payments", "label_en": "Payments", "label_fr": "Encaissement",
     "warn": True,
     "help_en": "Stripe. A live key reads and reports real money.",
     "help_fr": "Stripe. Une clé live lit et rapporte de l'argent réel."},
    {"name": "mail", "label_en": "Mail account", "label_fr": "Compte mail",
     "warn": True, "preset": True, "test": "mail",
     "help_en": "One account, both directions: the outreach agent writes from it, and "
                "reads it to see who replied. Pick your provider, give the address and "
                "an app password. Everything else is derived. Reading is read-only: "
                "corparius never marks a message seen, moves it or deletes it.",
     "help_fr": "Un compte, dans les deux sens : l'agent outreach écrit depuis lui, et "
                "le lit pour savoir qui a répondu. Choisissez le fournisseur, donnez "
                "l'adresse et un mot de passe d'application. Le reste est déduit. La "
                "lecture est en seule lecture : corparius ne marque jamais un message "
                "comme lu, ne le déplace pas et ne le supprime pas."},
    {"name": "publishing", "label_en": "Publishing", "label_fr": "Publication",
     "warn": True,
     "help_en": "Where the sales site goes. The local provider is always available, "
                "so anything ordered after it never runs.",
     "help_fr": "Où part le site. Le provider local est toujours disponible, donc "
                "tout ce qui est ordonné après lui ne s'exécute jamais."},
    {"name": "leads", "label_en": "Leads and signals", "label_fr": "Prospects et signaux",
     "help_en": "Where lead research and buying signals come from.",
     "help_fr": "D'où viennent la recherche de prospects et les signaux d'achat."},
]

# Known mail providers, both directions at once: the operator picks their
# provider, not four hostnames. Nobody remembers these, and the port is the
# single most common way a mail setup fails silently (465 and 993 are implicit
# TLS, 587 and 143 are STARTTLS; the wrong one gives a protocol error that reads
# like nothing). The note names the credential to use, which is almost never the
# account password.
MAIL_PRESETS: list[dict] = [
    {"id": "gmail", "label": "Gmail / Google Workspace",
     "host": "smtp.gmail.com", "port": 587,
     "imap_host": "imap.gmail.com", "imap_port": 993,
     "note_en": "Needs a 16-character app password, created under 2-step verification. "
                "Your normal password will be refused.",
     "note_fr": "Exige un mot de passe d'application de 16 caractères, créé sous la "
                "validation en deux étapes. Votre mot de passe habituel sera refusé."},
    {"id": "fastmail", "label": "Fastmail",
     "host": "smtp.fastmail.com", "port": 465,
     "imap_host": "imap.fastmail.com", "imap_port": 993,
     "note_en": "Create an app password scoped to SMTP in Settings, Privacy and Security.",
     "note_fr": "Créez un mot de passe d'application limité à SMTP dans Réglages, "
                "Confidentialité et sécurité."},
    {"id": "proton", "label": "Proton Mail (Bridge)",
     "host": "127.0.0.1", "port": 1025,
     "imap_host": "127.0.0.1", "imap_port": 1143,
     "note_en": "Requires Proton Mail Bridge running locally; it prints the password to use.",
     "note_fr": "Nécessite Proton Mail Bridge lancé en local ; il affiche le mot de passe."},
    {"id": "infomaniak", "label": "Infomaniak",
     "host": "mail.infomaniak.com", "port": 465,
     "imap_host": "mail.infomaniak.com", "imap_port": 993,
     "note_en": "Use the full address as the user.",
     "note_fr": "Utilisez l'adresse complète comme identifiant."},
    {"id": "ovh", "label": "OVH",
     "host": "ssl0.ovh.net", "port": 465,
     "imap_host": "ssl0.ovh.net", "imap_port": 993,
     "note_en": "Use the full address as the user.",
     "note_fr": "Utilisez l'adresse complète comme identifiant."},
    {"id": "scaleway", "label": "Scaleway TEM (sending only)",
     "host": "smtp.tem.scw.cloud", "port": 587,
     "note_en": "The user is your project ID; the password is the API secret key.",
     "note_fr": "L'identifiant est l'ID de projet ; le mot de passe est la clé secrète API."},
    {"id": "brevo", "label": "Brevo (sending only)",
     "host": "smtp-relay.brevo.com", "port": 587,
     "note_en": "The user is the login shown on the SMTP page, not your account email.",
     "note_fr": "L'identifiant est celui affiché sur la page SMTP, pas votre email de compte."},
    {"id": "mailgun", "label": "Mailgun (sending only)",
     "host": "smtp.mailgun.org", "port": 587,
     "note_en": "Use the postmaster user shown for your sending domain.",
     "note_fr": "Utilisez l'utilisateur postmaster affiché pour votre domaine d'envoi."},
    {"id": "local", "label": "Local relay (no auth)",
     "host": "localhost", "port": 25,
     "imap_host": "localhost", "imap_port": 143,
     "note_en": "For a homelab MTA on the same machine. Leave user and password empty.",
     "note_fr": "Pour un MTA de homelab sur la même machine. Laissez identifiant et mot "
                "de passe vides."},
]

# Local OpenAI-compatible servers for the `custom:` target. Each runs on your
# machine with no key, so "plug in an LLM" is: start the app, pick it here, point
# a tier at custom:<model>. Ports are the projects' defaults.
LLM_SERVER_PRESETS: list[dict] = [
    {"id": "lmstudio", "label": "LM Studio", "url": "http://localhost:1234/v1",
     "note_en": "Start the local server in LM Studio (Developer tab), then load a model.",
     "note_fr": "Démarrez le serveur local dans LM Studio (onglet Developer), puis chargez un modèle."},
    {"id": "jan", "label": "Jan", "url": "http://localhost:1337/v1",
     "note_en": "Enable the local API server in Jan's settings.",
     "note_fr": "Activez le serveur d'API local dans les réglages de Jan."},
    {"id": "ollama-openai", "label": "Ollama (OpenAI endpoint)", "url": "http://localhost:11434/v1",
     "note_en": "Ollama also speaks the OpenAI dialect here, if you prefer the custom target to the local one.",
     "note_fr": "Ollama parle aussi le dialecte OpenAI ici, si vous préférez la cible custom à la cible locale."},
    {"id": "llamacpp", "label": "llama.cpp server", "url": "http://localhost:8080/v1",
     "note_en": "`llama-server` from llama.cpp exposes this by default.",
     "note_fr": "`llama-server` de llama.cpp l'expose par défaut."},
    {"id": "vllm", "label": "vLLM", "url": "http://localhost:8000/v1",
     "note_en": "vLLM's OpenAI-compatible server default.",
     "note_fr": "Défaut du serveur compatible OpenAI de vLLM."},
    {"id": "localai", "label": "LocalAI", "url": "http://localhost:8080/v1",
     "note_en": "LocalAI's default OpenAI-compatible port.",
     "note_fr": "Port compatible OpenAI par défaut de LocalAI."},
]

WARN_EN = ("These keys authorise real-world effects: Stripe reports real money, SMTP "
           "writes to real addresses, publishing puts a site online. They are stored "
           "in the clear in the store and are included in backups.")
WARN_FR = ("Ces clés autorisent des effets réels : Stripe rapporte de l'argent réel, "
           "SMTP écrit à de vraies adresses, la publication met un site en ligne. Elles "
           "sont stockées en clair dans la base et incluses dans les sauvegardes.")


@dataclass(frozen=True)
class FieldSpec:
    key: str
    group: str
    type: str = "text"        # text | password | bool | int | float | select
    default: str = ""
    secret: bool = False
    label_en: str = ""
    label_fr: str = ""
    help_en: str = ""
    help_fr: str = ""
    choices: tuple = ()
    # Derived from the provider preset or from another field. Real, editable,
    # and folded away: an operator connecting Gmail should answer three
    # questions, not thirteen.
    advanced: bool = False

    @property
    def bootstrap(self) -> bool:
        """Bootstrap keys are stored in .env and only apply on restart: they must
        be readable before the store they would otherwise live in can open."""
        return self.key in cfg.BOOTSTRAP


def _f(key, group, **kw) -> FieldSpec:
    return FieldSpec(key=key, group=group, **kw)


SPEC: list[FieldSpec] = [
    # --- access (bootstrap: written to .env, applied on restart) -------------
    _f("CORP_UI_HOST", "access", default="127.0.0.1",
       label_en="Bind address", label_fr="Adresse d'écoute",
       help_en="127.0.0.1 keeps the console on this machine. Anything else needs a token.",
       help_fr="127.0.0.1 garde la console sur cette machine. Autre chose exige un token."),
    _f("CORP_UI_PORT", "access", type="int", default="8600",
       label_en="Port", label_fr="Port"),
    _f("CORP_UI_TOKEN", "access", type="password", secret=True,
       label_en="Access token", label_fr="Token d'accès",
       help_en="Required in the X-Corp-Token header on every write. Empty means no check, "
               "which is fine on localhost and not fine anywhere else.",
       help_fr="Exigé dans l'en-tête X-Corp-Token à chaque écriture. Vide = aucun contrôle, "
               "acceptable en localhost et nulle part ailleurs."),
    _f("CORP_DATA_PATH", "access", default="./data",
       label_en="Data directory", label_fr="Dossier de données",
       help_en="Holds the store: actions, tokens, approvals, tasks and saved settings.",
       help_fr="Contient la base : actions, tokens, approbations, tâches et réglages."),
    _f("CORP_LOG_LEVEL", "access", type="select", default="INFO",
       choices=("DEBUG", "INFO", "WARNING", "ERROR"),
       label_en="Log level", label_fr="Niveau de log"),
    _f("CORP_SECRET_KEY", "access", type="password", secret=True,
       label_en="Encrypt secrets at rest", label_fr="Chiffrer les secrets au repos",
       help_en="Off by default. A passphrase here encrypts the secret settings (API "
               "keys, tokens) in the store and in backups, using the 'cryptography' "
               "package. Applies on restart. Keep it safe: lose it and the encrypted "
               "secrets cannot be recovered. See docs/securite.md.",
       help_fr="Désactivé par défaut. Une phrase secrète ici chiffre les réglages "
               "secrets (clés API, tokens) dans la base et les sauvegardes, via le "
               "paquet 'cryptography'. Effectif au redémarrage. Gardez-la : la perdre "
               "rend les secrets chiffrés irrécupérables. Voir docs/securite.md."),
    _f("CORP_PLUGINS_ENABLED", "access", type="bool", default="false",
       label_en="Enable plugins", label_fr="Activer les plugins",
       help_en="Off by default. When on, corparius loads installed plugins at startup to "
               "extend its providers, tools, templates and agents. Applies on restart. "
               "Only verified plugins (in the curated registry) load unless you allow "
               "unverified ones below. See docs/plugins.md.",
       help_fr="Désactivé par défaut. Activé, corparius charge au démarrage les plugins "
               "installés pour étendre ses providers, outils, gabarits et agents. Effectif "
               "au redémarrage. Seuls les plugins vérifiés (du registre curaté) se chargent, "
               "sauf si vous autorisez les non vérifiés ci-dessous. Voir docs/plugins.md."),
    _f("CORP_PLUGINS", "access",
       label_en="Enabled plugins", label_fr="Plugins activés",
       help_en="Comma-separated plugin names to load. Empty loads every installed, "
               "non-disabled plugin. Managed from the Plugins tab.",
       help_fr="Noms de plugins à charger, séparés par des virgules. Vide = tous les "
               "plugins installés et non désactivés. Géré depuis l'onglet Plugins."),
    _f("CORP_PLUGINS_ALLOW_UNVERIFIED", "access", type="bool", default="false",
       label_en="Allow unverified plugins", label_fr="Autoriser les plugins non vérifiés",
       help_en="Off by default. Allows loading and installing plugins that are NOT in the "
               "curated registry — arbitrary third-party code. Only turn this on for plugins "
               "you have audited yourself.",
       help_fr="Désactivé par défaut. Autorise le chargement et l'installation de plugins "
               "ABSENTS du registre curaté — du code tiers arbitraire. À n'activer que pour "
               "des plugins que vous avez audités vous-même."),
    _f("CORP_UPDATE_CHECK", "access", type="bool", default="false",
       label_en="Check for updates", label_fr="Vérifier les mises à jour",
       help_en="Off by default. When on, corparius asks GitHub once at startup whether a "
               "newer release exists and shows a link. It never downloads anything and "
               "makes no other network call. This is the only outbound request the "
               "packaged app makes on its own.",
       help_fr="Désactivé par défaut. Activé, corparius demande une fois à GitHub au "
               "démarrage s'il existe une version plus récente et affiche un lien. Il ne "
               "télécharge jamais rien et ne fait aucun autre appel réseau. C'est la seule "
               "requête sortante que l'application packagée émet d'elle-même."),

    # --- local inference ----------------------------------------------------
    _f("CORP_OLLAMA_URL", "inference", default="http://localhost:11434",
       label_en="Ollama URL", label_fr="URL Ollama"),
    _f("CORP_OLLAMA_TIMEOUT", "inference", type="int", default="420",
       label_en="Timeout (seconds)", label_fr="Délai (secondes)",
       help_en="CPU-only machines can take minutes per generation. Raise it rather than "
               "letting runs die.",
       help_fr="Une machine sans GPU peut prendre des minutes par génération. Augmentez "
               "plutôt que de laisser les runs mourir."),
    _f("CORP_EMBED_MODEL", "inference", default="nomic-embed-text",
       label_en="Embedding model", label_fr="Modèle d'embedding",
       help_en="Used by the loop guard to measure semantic stutter.",
       help_fr="Utilisé par le garde-boucle pour mesurer le bégaiement sémantique."),

    # --- safety -------------------------------------------------------------
    _f("CORP_SESSION_TOKEN_BUDGET", "safety", type="int", default="100000",
       label_en="Session token budget", label_fr="Budget de tokens par session",
       help_en="Hard ceiling per session. Spent means halted. A company's own budget "
               "overrides this.",
       help_fr="Plafond dur par session. Épuisé = arrêt. Le budget propre à une "
               "entreprise prime sur celui-ci."),
    _f("CORP_TOKENS_PER_MINUTE_LIMIT", "safety", type="int", default="10000",
       label_en="Tokens per minute", label_fr="Tokens par minute",
       help_en="Spend velocity. A sustained burst past this trips the circuit breaker.",
       help_fr="Vélocité de dépense. Un dépassement soutenu déclenche le disjoncteur."),
    _f("CORP_LOOP_SIMILARITY_THRESHOLD", "safety", type="float", default="0.95",
       label_en="Loop similarity threshold", label_fr="Seuil de similarité du garde-boucle",
       help_en="Above this cosine similarity between successive outputs, the turn is "
               "suspended as a stutter.",
       help_fr="Au-dessus de cette similarité cosinus entre sorties successives, le tour "
               "est suspendu pour bégaiement."),
    _f("CORP_MAX_IDENTICAL_TOOL_CALLS", "safety", type="int", default="2",
       label_en="Max identical tool calls", label_fr="Appels d'outil identiques max"),
    _f("CORP_HITL_TOOLS", "safety",
       default="send_financial_transaction,publish_production_code,deploy_site",
       label_en="Tools that need approval", label_fr="Outils exigeant une approbation",
       help_en="Comma-separated. These never run until a human approves them. A company "
               "can override the list.",
       help_fr="Séparés par des virgules. Ils ne s'exécutent jamais sans approbation "
               "humaine. Une entreprise peut redéfinir la liste."),
    _f("CORP_WIP_LIMIT", "safety", type="int", default="4",
       label_en="WIP limit per agent", label_fr="Limite d'en-cours par agent",
       help_en="The CEO stops queueing for an agent already holding this many open tasks.",
       help_fr="Le CEO cesse d'alimenter un agent qui a déjà ce nombre de tâches ouvertes."),
    _f("CORP_CEO_APPROVE_CAP", "safety", type="int", default="3",
       label_en="CEO approvals per review", label_fr="Approbations CEO par revue"),
    _f("CORP_OUTREACH_MAX_PER_RUN", "safety", type="int", default="20",
       label_en="Outreach emails per run", label_fr="Emails d'outreach par run"),

    # --- payments -----------------------------------------------------------
    _f("STRIPE_API_KEY", "payments", type="password", secret=True,
       label_en="Stripe API key", label_fr="Clé API Stripe",
       help_en="A restricted read key is enough: corparius reads the balance and charges, "
               "it never creates one.",
       help_fr="Une clé restreinte en lecture suffit : corparius lit le solde et les "
               "paiements, il n'en crée jamais."),
    _f("CORP_STRIPE_PAYMENT_LINK", "payments",
       label_en="Payment link", label_fr="Lien de paiement",
       help_en="The sales-site button target, when a company sets no link of its own.",
       help_fr="Cible du bouton du site, quand une entreprise n'a pas son propre lien."),

    # --- mail account -------------------------------------------------------
    # The three that matter. Everything below them is filled by the provider
    # preset or falls back to these.
    _f("CORP_SMTP_USER", "mail",
       label_en="Email address", label_fr="Adresse email",
       help_en="The account the company sends from and reads. Also used as the IMAP "
               "user unless you override it below.",
       help_fr="Le compte depuis lequel la société écrit et qu'elle lit. Sert aussi "
               "d'identifiant IMAP, sauf si vous le changez plus bas."),
    _f("CORP_SMTP_PASSWORD", "mail", type="password", secret=True,
       label_en="App password", label_fr="Mot de passe d'application",
       help_en="Almost never your account password: most providers issue a separate "
               "one for mail clients. Reused for IMAP unless overridden.",
       help_fr="Presque jamais celui de votre compte : la plupart des fournisseurs en "
               "délivrent un séparé pour les clients mail. Réutilisé pour IMAP sauf "
               "si vous le changez."),
    _f("CORP_OUTREACH_TEST_TO", "mail",
       label_en="Send tests and fallbacks to", label_fr="Envoyer tests et replis à",
       help_en="Where the Test button writes, and where openers go when no lead has an "
               "address. Use your own inbox.",
       help_fr="Où écrit le bouton Tester, et où partent les messages quand aucun "
               "prospect n'a d'adresse. Utilisez la vôtre."),

    _f("CORP_SMTP_HOST", "mail", advanced=True,
       label_en="SMTP host", label_fr="Serveur SMTP",
       help_en="Filled by the provider above. Unset means the outreach agent keeps "
               "writing to its mock instead of sending.",
       help_fr="Rempli par le fournisseur ci-dessus. Vide = l'agent outreach continue "
               "d'écrire dans son mock au lieu d'envoyer."),
    _f("CORP_SMTP_PORT", "mail", type="int", default="587", advanced=True,
       label_en="SMTP port", label_fr="Port SMTP",
       help_en="465 is implicit TLS, 587 is STARTTLS. corparius picks the right one "
               "from the number.",
       help_fr="465 = TLS implicite, 587 = STARTTLS. corparius choisit le bon "
               "transport d'après le numéro."),
    _f("CORP_SMTP_FROM", "mail", advanced=True,
       label_en="From address", label_fr="Adresse d'expédition",
       help_en="Defaults to the address above. Most providers refuse a sender that "
               "does not match the account.",
       help_fr="Reprend l'adresse ci-dessus par défaut. La plupart des fournisseurs "
               "refusent un expéditeur qui ne correspond pas au compte."),
    _f("CORP_IMAP_HOST", "mail", advanced=True,
       label_en="IMAP host", label_fr="Serveur IMAP",
       help_en="Filled by the provider above. Unset means inbox triage uses sample "
               "counts and prospect replies go unnoticed.",
       help_fr="Rempli par le fournisseur ci-dessus. Vide = le triage utilise des "
               "chiffres d'exemple et les réponses des prospects passent inaperçues."),
    _f("CORP_IMAP_PORT", "mail", type="int", default="993", advanced=True,
       label_en="IMAP port", label_fr="Port IMAP",
       help_en="993 is implicit TLS, 143 is STARTTLS.",
       help_fr="993 = TLS implicite, 143 = STARTTLS."),
    _f("CORP_IMAP_USER", "mail", advanced=True,
       label_en="IMAP user", label_fr="Utilisateur IMAP",
       help_en="Only if reading uses a different account from sending.",
       help_fr="Seulement si la lecture utilise un autre compte que l'envoi."),
    _f("CORP_IMAP_PASSWORD", "mail", type="password", secret=True, advanced=True,
       label_en="IMAP password", label_fr="Mot de passe IMAP",
       help_en="Only if reading uses a different password from sending.",
       help_fr="Seulement si la lecture utilise un autre mot de passe que l'envoi."),
    _f("CORP_IMAP_FOLDER", "mail", default="INBOX", advanced=True,
       label_en="Folder to read", label_fr="Dossier à lire",
       help_en="Point it at a dedicated folder if you filter prospect replies into one.",
       help_fr="Visez un dossier dédié si vous y filtrez les réponses de prospects."),
    _f("CORP_OUTREACH_DAILY_CAP", "mail", type="int", default="0", advanced=True,
       label_en="Daily send cap", label_fr="Plafond d'envoi quotidien",
       help_en="0 means no cap. Warm a new domain up slowly.",
       help_fr="0 = aucun plafond. Chauffez un domaine neuf progressivement."),
    _f("CORP_SUPPRESSION_FILE", "mail", advanced=True,
       label_en="Suppression list", label_fr="Liste de suppression",
       help_en="Path to a file of addresses never to contact, one per line.",
       help_fr="Chemin d'un fichier d'adresses à ne jamais contacter, une par ligne."),

    # --- publishing ---------------------------------------------------------
    _f("CORP_DEPLOY_PROVIDERS", "publishing", default="local,netlify,s3,ssh",
       label_en="Provider order", label_fr="Ordre des providers",
       help_en="Tried in order, first that works wins. 'local' is always available, so "
               "put it last if you want to publish anywhere else.",
       help_fr="Essayés dans l'ordre, le premier qui marche gagne. « local » est toujours "
               "disponible : mettez-le en dernier pour publier ailleurs."),
    _f("CORP_DEPLOY_LOCAL_DIR", "publishing",
       label_en="Local directory", label_fr="Dossier local",
       help_en="Where the 'local' provider copies the site. Defaults to data/sites/published.",
       help_fr="Où le provider « local » copie le site. Par défaut data/sites/published."),
    _f("NETLIFY_AUTH_TOKEN", "publishing", type="password", secret=True,
       label_en="Netlify token", label_fr="Token Netlify",
       help_en="Also needs the netlify CLI on PATH.",
       help_fr="Nécessite aussi le CLI netlify sur le PATH."),
    _f("NETLIFY_SITE_ID", "publishing", label_en="Netlify site ID", label_fr="ID du site Netlify"),
    _f("CORP_S3_BUCKET", "publishing", label_en="S3 bucket", label_fr="Bucket S3",
       help_en="Also needs boto3 installed; it is not a corparius dependency.",
       help_fr="Nécessite aussi boto3 installé ; ce n'est pas une dépendance de corparius."),
    _f("CORP_S3_ENDPOINT", "publishing", label_en="S3 endpoint", label_fr="Endpoint S3",
       help_en="Set it for MinIO, Cloudflare R2 or any S3-compatible host.",
       help_fr="À renseigner pour MinIO, Cloudflare R2 ou tout hôte compatible S3."),
    _f("CORP_S3_REGION", "publishing", label_en="S3 region", label_fr="Région S3"),
    _f("CORP_S3_KEY", "publishing", type="password", secret=True,
       label_en="S3 access key", label_fr="Clé d'accès S3"),
    _f("CORP_S3_SECRET", "publishing", type="password", secret=True,
       label_en="S3 secret key", label_fr="Clé secrète S3"),
    _f("CORP_DEPLOY_SSH_TARGET", "publishing",
       label_en="rsync target", label_fr="Cible rsync",
       help_en="user@host:/var/www/site. Needs rsync on PATH and key-based auth.",
       help_fr="user@host:/var/www/site. Nécessite rsync sur le PATH et une auth par clé."),

    # --- leads --------------------------------------------------------------
    _f("CORP_LEAD_SOURCES", "leads", default="browser,local",
       label_en="Lead sources", label_fr="Sources de prospects",
       help_en="Tried in order. 'browser' needs playwright installed.",
       help_fr="Essayées dans l'ordre. « browser » nécessite playwright installé."),
    _f("CORP_LEADS_CSV", "leads", label_en="Local lead CSV", label_fr="CSV de prospects local"),
    _f("CORP_LEADS_URL", "leads", label_en="Lead search URL", label_fr="URL de recherche",
       help_en="{query} is replaced with the company's ICP segment.",
       help_fr="{query} est remplacé par le segment ICP de l'entreprise."),
    _f("CORP_BROWSER_UA", "leads", default="Mozilla/5.0 (compatible; corparius/0.1)",
       label_en="Browser user agent", label_fr="User agent du navigateur"),
    _f("CORP_ENRICHERS", "leads", default="local",
       label_en="Enrichers", label_fr="Enrichisseurs"),
    _f("CORP_ENRICH_DOMAIN", "leads",
       label_en="Enrichment domain", label_fr="Domaine d'enrichissement",
       help_en="Guessed email domain when a lead has a name but no address.",
       help_fr="Domaine d'email deviné quand un prospect a un nom mais pas d'adresse."),
    _f("CORP_SIGNAL_SOURCES", "leads", default="browser,local",
       label_en="Signal sources", label_fr="Sources de signaux"),
    _f("CORP_SIGNALS_FILE", "leads", label_en="Local signals file", label_fr="Fichier de signaux local"),
    _f("CORP_SIGNALS_URL", "leads", label_en="Signals URL", label_fr="URL des signaux"),
]

BY_KEY: dict[str, FieldSpec] = {f.key: f for f in SPEC}

# Provider keys and routing tiers keep their own panel (Providers), so they are
# settable but not rendered by the settings registry.
_PROVIDER_VARS = ({spec["key_env"] for spec in OPENAI_COMPAT_PROVIDERS.values()}
                  | {spec["base_env"] for spec in OPENAI_COMPAT_PROVIDERS.values()
                     if "base_env" in spec}
                  | {"ANTHROPIC_API_KEY"})
_TOGGLE_VARS = {"CORP_CLOUD_ENABLED", "CORP_LLM_MOCK", "CORP_CLAUDE_CODE"}
_TIER_VARS = {"CORP_TRIVIAL_MODEL", "CORP_NORMAL_MODEL", "CORP_HARD_MODEL",
              "CORP_LLM_FALLBACK", "CORP_LOCAL_MODEL"}

WRITABLE: set[str] = set(BY_KEY) | _PROVIDER_VARS | _TOGGLE_VARS | _TIER_VARS
SECRETS: set[str] = ({f.key for f in SPEC if f.secret}
                     | {spec["key_env"] for spec in OPENAI_COMPAT_PROVIDERS.values()}
                     | {"ANTHROPIC_API_KEY"})


def coerce(spec: FieldSpec, raw) -> tuple[str | None, str]:
    """Validate one value against its spec. Returns (clean, error); clean is None
    when the operator is clearing the field."""
    value = str(raw).strip()
    if value == "":
        return None, ""
    if spec.type == "int":
        try:
            return str(int(value)), ""
        except ValueError:
            return None, f"{spec.key}: expected a whole number, got '{value}'"
    if spec.type == "float":
        try:
            return str(float(value)), ""
        except ValueError:
            return None, f"{spec.key}: expected a number, got '{value}'"
    if spec.type == "bool":
        if value.lower() not in ("true", "false"):
            return None, f"{spec.key}: expected true or false, got '{value}'"
        return value.lower(), ""
    if spec.type == "select" and value not in spec.choices:
        return None, f"{spec.key}: expected one of {', '.join(spec.choices)}, got '{value}'"
    return value, ""


def describe(key: str, lang_fields: bool = True) -> dict:
    """One field as the page needs it: never the value of a secret, always the
    layer that answers for it and whether the console can actually change it."""
    spec = BY_KEY[key]
    src = cfg.source(key)
    value = cfg.get(key, spec.default)
    out = {
        "key": key, "group": spec.group, "type": spec.type,
        "secret": spec.secret, "default": spec.default,
        "configured": bool(value.strip()),
        "source": src,
        "editable": src != "env",
        "restart_required": spec.bootstrap,
        "advanced": spec.advanced,
    }
    out["value"] = None if spec.secret else value
    if spec.choices:
        out["choices"] = list(spec.choices)
    if lang_fields:
        out.update({"label_en": spec.label_en or key, "label_fr": spec.label_fr or key,
                    "help_en": spec.help_en, "help_fr": spec.help_fr})
    return out
