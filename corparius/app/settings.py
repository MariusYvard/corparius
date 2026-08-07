"""Writing a setting, to whichever of the two layers can hold it. Rank 5.

This was `webui._persist(state, values, unset)`, and the signature is the point of moving it.
`state` is a `UiState` — a console object — so the only caller that could ever reach this was
the console. Taking `(store, env_file)` instead means the command line can write a setting on a
headless box, which until now took editing .env by hand.

The layer rule is not a preference here, it is arithmetic:

  * **Bootstrap keys go to .env.** They have to be readable before the store can be opened —
    you cannot ask the database where the database is — so they cannot live in it.
  * **Everything else goes to the settings table**, which outranks .env and survives a restart.
  * **Nothing is written to `os.environ`.** That layer belongs to whoever started the process.
    Writing it here would promote a console value above every later edit and make
    `cfg.source()` report "env" for a value the console itself set. A key the process
    environment already defines is reported back as *shadowed* rather than silently ignored.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..config import cfg, settings_spec
from ..kernel import dotenv

SECRET_VARS = settings_spec.SECRETS


def persist(
    store,
    env_file: Path,
    values: dict[str, str],
    unset: list[str] | None = None,
) -> dict:
    """Write these settings and report what the caller should say about it.

    Raises `kernel.dotenv.LineBreakRefused` when a value contains a newline — the failure, not
    a status code. The console turns that into a 400; a terminal shows it. A service that
    raised the console's own exception could only ever be called by the console, which is the
    thing this move exists to fix.

    Returns the meta a caller merges into its answer: which keys are shadowed by the process
    environment, which need a restart, and whether the stored secrets were rewritten.
    """
    unset = unset or []
    boot = {k: v for k, v in values.items() if k in cfg.BOOTSTRAP}
    stored = {k: v for k, v in values.items() if k not in cfg.BOOTSTRAP}
    if boot:
        dotenv.merge_into(env_file, boot)
    if stored or unset:
        for key, value in stored.items():
            store.set_setting(key, value, secret=key in SECRET_VARS)
        for key in unset:
            store.delete_setting(key)
        if any(k in cfg.BOOTSTRAP for k in unset):
            dotenv.merge_into(env_file, {k: "" for k in unset if k in cfg.BOOTSTRAP})
    cfg.invalidate()
    meta: dict = {}
    # Setting or clearing the passphrase has to rewrite what is already stored, exactly as
    # `corparius secrets on` does. Without this the field looked like it encrypted the
    # operator's keys and only affected the next write — the trap that made the setting mean
    # less than it said.
    if "CORP_SECRET_KEY" in values or "CORP_SECRET_KEY" in unset:
        from ..config import secretbox

        try:
            changed = store.rewrite_secrets(to_encrypted=secretbox.enabled())
        except Exception:  # noqa: BLE001 - a wrong passphrase must not take down the caller
            meta["secrets_error"] = (
                "The stored secrets could not be rewritten with that passphrase. "
                "It has to be the one they were encrypted with."
            )
        else:
            meta["secrets_rewritten"] = sorted(changed)
    shadowed = [k for k in list(values) + unset if os.environ.get(k) is not None]
    if shadowed:
        meta["shadowed"] = sorted(shadowed)
    restart = sorted(k for k in list(values) + unset if k in cfg.BOOTSTRAP)
    if restart:
        meta["restart_required"] = restart
    return meta


def validate(
    values: dict, unset: list[str] | None = None
) -> tuple[dict[str, str], list[str], list[str]]:
    """(accepted, to clear, refusals) against the field registry.

    Lifted out of the console's handler unchanged, so the command line refuses the same values
    for the same reasons. A registry only one caller consults is a registry that drifts — this
    project has the receipts, and `tests/test_registries.py` exists because of them.

    An empty value **clears** the setting rather than storing an empty string, so the layer
    below shows through again. That distinction is why this returns three lists and not two.
    """
    clean: dict[str, str] = {}
    drop: list[str] = [k for k in (unset or []) if k in settings_spec.BY_KEY]
    errors: list[str] = []
    for key, raw in values.items():
        spec = settings_spec.BY_KEY.get(key)
        if spec is None:
            errors.append(f"unknown setting '{key}'")
            continue
        value, err = settings_spec.coerce(spec, raw)
        if err:
            errors.append(err)
        elif value is None:
            drop.append(key)
        else:
            clean[key] = value
    return clean, drop, errors
