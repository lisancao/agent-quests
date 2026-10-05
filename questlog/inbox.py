"""Per-session inbox: the events that matter to one agent session, since it last looked.

Scope comes from the session's quest (bound via QUESTLOG_QUEST / quest_attach) or from what its
first prompt was oriented to; an agent also hears about quests it leads. The cursor advances on read.
"""
from __future__ import annotations

import json
import time

from . import bindings, config as cfgmod, events, store

DIR = cfgmod.STATE_DIR / "inbox"
BROAD = ("quest_added", "activated", "completed")                       # news worth hearing faction-wide
FOR_LEAD = ("assigned", "activated", "quest_added", "answered", "unblocked", "completed")


def _path(session_id: str):
    DIR.mkdir(parents=True, exist_ok=True)
    return DIR / f"{session_id or 'none'}.json"


def state(session_id: str) -> dict:
    try:
        return json.loads(_path(session_id).read_text())
    except (OSError, ValueError):
        return {}


def set_scope(session_id: str, faction: str = "", arc: str = "", quest: str = "", agent: str = "") -> None:
    st = state(session_id)
    st.update({k: v for k, v in (("faction", faction), ("arc", arc), ("quest", quest), ("agent", agent)) if v})
    st.setdefault("cursor", time.time())
    _path(session_id).write_text(json.dumps(st))


def _scope(cfg: cfgmod.Config, session_id: str, agent: str) -> dict:
    st = state(session_id)
    ref = bindings.quest_for(session_id)
    if ref:
        q = store.find(ref, cfg)
        if q:
            st.update({"quest": q.ref, "arc": q.arc, "faction": q.faction})
    if agent:
        st["agent"] = agent
    return st


def relevant(ev: dict, scope: dict) -> bool:
    if scope.get("quest") and ev.get("ref") == scope["quest"]:
        return True
    if scope.get("arc") and ev.get("arc") == scope["arc"] and ev.get("faction") == scope.get("faction"):
        return True
    if scope.get("faction") and ev.get("faction") == scope["faction"] and ev.get("kind") in BROAD:
        return True
    if scope.get("agent") and ev.get("lead") == scope["agent"] and ev.get("kind") in FOR_LEAD:
        return True
    return False


def read(session_id: str, agent: str = "", cfg: cfgmod.Config | None = None, advance: bool = True) -> list[dict]:
    cfg = cfg or cfgmod.load()
    st = _scope(cfg, session_id, agent)
    cursor = st.get("cursor", time.time() - 3600)
    evs = [e for e in events.read(cfg, since=cursor) if relevant(e, st)]
    if advance:
        st["cursor"] = time.time()
        _path(session_id).write_text(json.dumps(st))
    return evs


def render(evs: list[dict], limit: int = 6) -> str:
    lines = []
    for e in evs[-limit:]:
        lines.append(f"- [{e['kind']}] `{e['ref']}` {e['title']}: {e['summary']}")
    more = len(evs) - limit
    return "\n".join(lines) + (f"\n- … {more} more (`inbox`)" if more > 0 else "")
