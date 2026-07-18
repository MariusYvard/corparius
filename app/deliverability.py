"""Outreach deliverability guard: a suppression list and a daily cap (the cap
doubles as domain warmup, raise it over time). Consulted before every send so
outreach stays responsible and does not burn a sending domain.
"""
from __future__ import annotations
import json
import os
import time

from . import cfg, paths


def _suppressed(email: str) -> bool:
    path = cfg.get("CORP_SUPPRESSION_FILE", "")
    if not path or not os.path.isfile(path):
        return False
    target = email.strip().lower()
    with open(path, encoding="utf-8") as fh:
        return any(line.strip().lower() == target for line in fh)


def _counter_path() -> str:
    return os.path.join(cfg.get("CORP_DATA_PATH", paths.default_data_dir()), "outreach_counter.json")


def _today() -> str:
    return time.strftime("%Y-%m-%d")


def _sent_today() -> int:
    try:
        with open(_counter_path(), encoding="utf-8") as fh:
            return int(json.load(fh).get(_today(), 0))
    except (OSError, ValueError):
        return 0


def can_send(email: str) -> tuple[bool, str]:
    """Return (allowed, reason). Enforces the suppression list then the daily cap
    (CORP_OUTREACH_DAILY_CAP; 0 or unset means no cap)."""
    if _suppressed(email):
        return False, "on suppression list"
    cap = cfg.get_int("CORP_OUTREACH_DAILY_CAP", 0)
    if cap > 0 and _sent_today() >= cap:
        return False, f"daily cap {cap} reached"
    return True, "ok"


def record_send() -> None:
    path = _counter_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    data: dict = {}
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            data = {}
    day = _today()
    data[day] = int(data.get(day, 0)) + 1
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
