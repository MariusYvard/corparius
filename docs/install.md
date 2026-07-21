# Installation

Trois façons de lancer corparius, de la plus simple à la plus souple. Toutes
démarrent en mode mock hors-ligne : aucune clé, aucun modèle, aucun compte, aucun
appel réseau.

1. **Binaire téléchargé** — un fichier, un double-clic. Aucun Python, aucun terminal.
2. **Image Docker** — une commande, sans dépôt cloné.
3. **`pip install`** — pour qui a déjà Python et veut la commande `corparius` sur le PATH.
4. **Depuis les sources** — `python start.py` ou les lanceurs double-clic (Python 3.10+ requis).

## 1. Binaire téléchargé (le plus simple)

Récupérez le fichier de votre système depuis la [dernière release](https://github.com/MariusYvard/corparius/releases/latest).

| Système | Fichier | Ensuite |
| --- | --- | --- |
| Windows x64 | `corparius-windows-x64.exe` | double-cliquez |
| macOS (Apple Silicon) | `corparius-macos-arm64.zip` | décompressez, puis clic-droit sur `corparius.app` → Ouvrir |
| macOS (Intel) | `corparius-macos-x64.zip` | décompressez, puis clic-droit sur `corparius.app` → Ouvrir |
| Linux x64 | `corparius-linux-x64` | `chmod +x corparius-linux-x64 && ./corparius-linux-x64` |

Au premier lancement, corparius prépare son dossier de données, crée la société
d'exemple, lance le doctor, puis ouvre la console dans votre navigateur sur
`http://127.0.0.1:8600`. Une fenêtre de terminal reste ouverte et affiche les
lignes `[corparius] …` : c'est voulu (transparence). Fermez-la ou faites Ctrl+C
pour arrêter proprement.

### Avertissements de premier lancement (builds non signés)

Les binaires ne sont pas signés (pas de certificat payant), donc le système
affiche un avertissement la première fois. C'est normal et sans danger ; voici
comment passer.

- **Windows / SmartScreen** : « Windows a protégé votre ordinateur ». Cliquez sur
  **Informations complémentaires**, puis **Exécuter quand même**.
- **macOS / Gatekeeper** : ne double-cliquez pas la première fois. Faites
  **clic-droit sur `corparius.app` → Ouvrir**, puis confirmez **Ouvrir**. Si macOS
  refuse en indiquant que l'app est « endommagée » (attribut de quarantaine posé
  au téléchargement), retirez-le une fois :
  `xattr -dr com.apple.quarantine /chemin/vers/corparius.app`.
- **Linux** : rendez le fichier exécutable (`chmod +x`), puis lancez-le. Le binaire
  est construit sur une glibc récente ; sur une distribution ancienne, préférez
  l'image Docker ou les sources.

Vous pouvez vérifier l'intégrité avant d'exécuter : chaque release publie un
fichier `SHA256SUMS`. Comparez-y l'empreinte de votre téléchargement
(`sha256sum <fichier>` sous Linux, `shasum -a 256 <fichier>` sous macOS,
`certutil -hashfile <fichier> SHA256` sous Windows).

## 2. Image Docker

Sans dépôt cloné, en une commande, en mode mock et liée à localhost :

```bash
docker run -d -p 127.0.0.1:8600:8600 -v corparius_data:/app/data ghcr.io/mariusyvard/corparius
```

L'image est multi-arch (amd64 et arm64), taguée `:vX.Y.Z` et `:latest`, avec une
attestation de provenance SLSA. Le volume `corparius_data` conserve le store et
les réglages. Voir [deploiement.md](deploiement.md) pour compose et les profils.

## 3. `pip install`

Si vous avez déjà Python 3.10+ :

```bash
pip install corparius
corparius              # lance la console sur http://127.0.0.1:8600
```

La commande `corparius` expose les mêmes sous-commandes que depuis les sources
(`corparius run`, `corparius doctor`, `corparius plugin …`). Le mode mock reste
le défaut : les deux seules dépendances installées sont `requests` et `PyYAML`.
Le chiffrement au repos et le serveur MCP sont des extras optionnels :
`pip install "corparius[secrets]"`, `pip install "corparius[mcp]"`.

Au premier lancement, corparius crée la société d'exemple et écrit son store,
son `.env` et vos sociétés dans un dossier de données par système (voir « Où
vivent vos données » ci-dessous) — jamais dans `site-packages`.

## 4. Depuis les sources

`python start.py` prépare l'environnement virtuel, les dépendances, le `.env` et
la société d'exemple, puis sert la console. Les lanceurs double-clic
(`start-windows.bat`, `start-macos.command`, `start-linux.sh`) font de même. Seul
prérequis : Python 3.10+.

## Où vivent vos données

Le binaire packagé écrit dans un dossier par système, **hors** de l'exécutable, ce
qui fait que retélécharger une version ne touche à rien :

| Système | Dossier de données |
| --- | --- |
| Windows | `%LOCALAPPDATA%\corparius` |
| macOS | `~/Library/Application Support/corparius` |
| Linux | `$XDG_DATA_HOME/corparius` (défaut `~/.local/share/corparius`) |

On y trouve le store SQLite (`data/corparius.sqlite`), le `.env`, les sociétés que
vous créez (`companies/`) et les sauvegardes (`backups/`). Depuis les sources, tout
reste comme avant, dans le dépôt (`./data`, `./companies`, `./.env`).

Deux variables redirigent ces emplacements, utiles pour pointer une instance vers
un dossier existant ou en migrer un entre installs :

- `CORP_HOME` — la racine inscriptible entière (données, `.env`, sociétés, backups).
- `CORP_DATA_PATH` — uniquement le store et les sites générés.

### Secrets au repos

Les clés API enregistrées depuis la console sont stockées **en clair** dans
`data/corparius.sqlite`, et incluses dans les sauvegardes. corparius pose des
permissions propriétaire-seul sur POSIX (dossier `0700`, base `0600`) ; sous
Windows, le dossier `%LOCALAPPDATA%` est déjà propre à votre compte. Traitez ce
fichier comme un mot de passe. Le doctor le rappelle et vérifie les permissions.

## Mettre à jour

- **Binaire** : téléchargez la nouvelle version et remplacez l'ancien fichier. Vos
  données (dossier par OS ci-dessus) sont conservées telles quelles.
- **Notification** : la vérification de version est **désactivée par défaut**. Vous
  pouvez l'activer dans la console (Réglages → « Vérifier les mises à jour », clé
  `CORP_UPDATE_CHECK`). Activée, corparius demande une fois à GitHub, au démarrage,
  s'il existe une version plus récente et affiche un lien. Il ne télécharge jamais
  rien et ne fait aucun autre appel réseau — c'est la seule requête sortante que
  l'application émet d'elle-même.
- **Docker** : `docker pull ghcr.io/mariusyvard/corparius` puis recréez le
  conteneur ; le volume conserve tout.

## Désinstaller

Supprimez le binaire (ou `corparius.app`). Pour tout effacer, supprimez aussi le
dossier de données de votre système (voir le tableau ci-dessus) — il contient vos
sociétés et vos clés, donc ne le faites qu'à dessein. Sauvegardez d'abord si un
doute subsiste (console → Sauvegardes, ou `python -m corparius.cli backup` depuis les
sources).

## Le port est déjà pris

Si `8600` est occupé, corparius le dit et ne démarre pas silencieusement. Une autre
console tourne peut-être déjà (ouvrez `http://127.0.0.1:8600`), ou choisissez un
autre port : réglez `CORP_UI_PORT` (console → Réglages, ou `.env`).

## Options lourdes non incluses

Pour rester léger, le binaire packagé **n'embarque pas** les extras optionnels : le
navigateur Playwright/Chromium (source de leads navigateur) et boto3 (déploiement
S3). Si vous en avez besoin, utilisez le chemin sources (`pip install`) ou Docker.
Tout le reste — mode mock, providers gratuits, Ollama, Claude Code CLI, mail,
Stripe, publication locale — fonctionne dans le binaire.
