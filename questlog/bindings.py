"""Which quest a session is working on.

Two ways in: the QUESTLOG_QUEST environment variable (set by whatever launched the session),
or bindings.json, written when an agent calls quest_attach for its own session.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from . import config as cfgmod

FILE = cfgmod.STATE_DIR / "bindings.json"
ENV_VARS = ("QUESTLOG_QUEST",)


def _load() -> dict:
    try:
        return json.loads(FILE.read_text())
    except (OSError, ValueError):
        return {}


def attach(session_id: str, quest_ref: str) -> None:
    FILE.parent.mkdir(parents=True, exist_ok=True)
    data = _load()
    data[session_id] = {"quest": quest_ref, "at": time.time()}
    # Bindings only matter while a session is alive; keep the file small.
    cutoff = time.time() - 30 * 86400
    data = {k: v for k, v in data.items() if v.get("at", 0) > cutoff}
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    os.replace(tmp, FILE)


def quest_for(session_id: str | None = None) -> str | None:
    """The quest ref (or path) for this session: env first, then bindings."""
    for var in ENV_VARS:
        if os.environ.get(var):
            return os.environ[var]
    if session_id:
        rec = _load().get(session_id)
        if rec:
            return rec["quest"]
    return None
