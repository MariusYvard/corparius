# Plugins

Les plugins étendent corparius sans toucher au cœur : ils ajoutent des providers
(LLM, déploiement, sources de leads, enrichers), des outils, des gabarits
d'entreprise, ou personnalisent un agent existant. Le tout reste fidèle à
l'éthique du projet : local-first, auditable, mock hors-ligne toujours
fonctionnel, aucune télémétrie.

## Principes de confiance

- **Désactivés par défaut.** Rien ne se charge tant que `CORP_PLUGINS_ENABLED`
  n'est pas à `true`. Le chargement n'a lieu qu'aux points d'entrée réels (CLI,
  console, binaire) — jamais à l'import, donc les tests et les imports restent
  déterministes.
- **Curatés par défaut.** Un plugin est *vérifié* quand son nom figure dans le
  registre du dépôt (`plugins/registry.json`), une liste revue et checksummée.
  Un plugin *non vérifié* (déposé à la main, ou installé depuis une URL
  arbitraire) ne se charge qu'avec `CORP_PLUGINS_ALLOW_UNVERIFIED=true`, avec un
  avertissement « code non audité ».
- **Isolés.** Un plugin qui échoue au chargement est journalisé et ignoré ; il ne
  peut jamais faire tomber la console ou un run.
- **Gardés.** Un outil ajouté par un plugin passe par les mêmes barrières que les
  autres : validation humaine (HITL) et pare-feu de sécurité au dispatch.

## Installer un plugin

Depuis le registre vérifié (console ou CLI) :

```bash
corparius plugin list                 # installés + disponibles
corparius plugin install <nom>        # télécharge au ref épinglé, vérifie le sha256
corparius plugin enable <nom>
corparius plugin disable <nom>
corparius plugin remove <nom>
```

Depuis la **console** : onglet *Plugins* → *Installer* sur une entrée du registre
(plugins vérifiés uniquement), puis redémarrez. Activer les plugins d'abord dans
Réglages → *Activer les plugins*.

Un plugin **non vérifié** (à vos risques, code tiers non audité) s'installe
seulement en ligne de commande, derrière l'opt-in :

```bash
CORP_PLUGINS_ALLOW_UNVERIFIED=true corparius plugin install monplugin --url https://.../monplugin.tar.gz
```

Les plugins vivent dans `<dossier-de-données>/plugins/<nom>/` (voir
[install.md](install.md) pour l'emplacement par OS), donc ça marche à l'identique
depuis les sources, Docker et les binaires figés.

## Écrire un plugin

Le squelette est dans [`packaging/plugin-template/`](../packaging/plugin-template/).
Un plugin, c'est un manifeste plus un point d'entrée `register(api)` :

`corparius_plugin.json` :

```json
{
  "name": "monplugin",
  "version": "0.1.0",
  "api_version": 1,
  "entrypoint": "monplugin:register",
  "kinds": ["llm", "deploy"],
  "needs_network": false,
  "description": "Ce que fait le plugin."
}
```

`monplugin/__init__.py` :

```python
def register(api):
    api.register_llm_provider("monai", base="https://api.exemple.com/v1", key_env="MON_API_KEY")
    # api.register_deploy_provider(instance)   # sous-classe corparius.deploy.DeployProvider
    # api.register_lead_source(instance)       # sous-classe corparius.leadsource.LeadSource
    # api.register_enricher(instance)          # sous-classe corparius.enrich.Enricher
    # api.register_tool(tool)                  # corparius.tools.Tool (HITL + firewall s'appliquent)
    # api.register_template(dict)              # gabarit d'entreprise
    # api.customize_agent("strategy", system_prompt="...", playbook=[...])
```

Deux modes de chargement, couverts par le même manifeste :

- **Drop-in** (partout, y compris binaires figés) : copiez le dossier dans
  `<dossier-de-données>/plugins/<nom>/`.
- **pip** (sources / Docker) : un `pyproject.toml` déclarant le point d'entrée
  `corparius.plugins` rend le paquet découvrable après `pip install`.

Les agents : `AgentRole` est un enum figé, donc en v1 un plugin **personnalise un
rôle existant** (prompt, playbook, cadence, modèle) ; ajouter un rôle inédit n'est
pas encore supporté.

## Proposer un plugin via GitHub

Pour qu'un plugin devienne installable en un clic par tout le monde :

1. Forkez [`packaging/plugin-template/`](../packaging/plugin-template/) dans votre
   propre dépôt GitHub, et publiez-le.
2. Ouvrez une PR sur corparius qui **ajoute une entrée** à `plugins/registry.json` :

   ```json
   { "name": "monplugin", "repo": "https://github.com/vous/monplugin",
     "ref": "v0.1.0", "sha256": "<sha256 de l'archive du tag>",
     "kinds": ["llm"], "description": "..." }
   ```

   Le `sha256` est celui de `https://github.com/vous/monplugin/archive/v0.1.0.tar.gz`.
3. La CI (`.github/workflows/plugins-validate.yml`) valide le manifeste,
   télécharge votre ref épinglé, vérifie le sha256 et charge le plugin contre la
   version d'API courante. Une fois la PR fusionnée, votre plugin est vérifié.

## Diagnostic

`python -m corparius.cli doctor` (et l'onglet Réglages de la console) affiche l'état des
plugins : activés ou non, combien d'installés et chargés, et un avertissement si
un plugin **non vérifié** est chargé.
