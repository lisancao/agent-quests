"""End-of-session nudge (Stop hook): ask the agent, once, to leave the quest log better than it found it.

Fires at most once per session and never while Claude is already continuing from a Stop hook.
Bound session: the quest wasn't updated this session, has no next step, or has every objective ticked
but is still open. Unbound session that was oriented to a goal and did real work: attach it or propose
a quest. Otherwise silent.
"""
from __future__ import annotations

import json
import os
import time

from . import bindings, config as cfgmod, inbox, orient, store

DIR = cfgmod.STATE_DIR / "nudged"
MIN_TRANSCRIPT = 30_000   # bytes: below this, an unbound session is too slight to nudge


def check(session_id: str, transcript_path: str = "", cfg: cfgmod.Config | None = None) -> str | None:
    cfg = cfg or cfgmod.load()
    if not cfg.nudge:
        return None
    started = 0.0
    mark = orient.STATE / session_id
    if mark.exists():
        try:
            started = float(mark.read_text() or 0)
        except ValueError:
            started = mark.stat().st_mtime
    ref = bindings.quest_for(session_id)
    q = store.find(ref, cfg) if ref else None
    if q:
        reasons = []
        if started and q.path.stat().st_mtime < started:
            reasons.append(f"its state hasn't been updated this session")
        if not q.next:
            reasons.append("it has no next step")
        if q.objectives and all(c for c, _ in q.objectives) and q.status != "done":
            if (q.authority or "autonomous") == "autonomous":
                reasons.append("every objective is ticked but it's still open (is the definition of done met?)")
            elif not q.waiting:
                reasons.append("every objective is ticked: ask the game master to sign it off (put it in `waiting`)")
        if not reasons:
            return None
        return (f"Before you finish: this session worked on quest `{q.ref}` ({q.title}), and "
                + "; ".join(reasons) + ". Update it with `quest_update` (save_state, next, waiting, status), and if "
                "you see follow-up work, propose it (`quest_create`, or note it for the game master). One short pass.")
    scope = inbox.state(session_id)
    try:
        size = os.path.getsize(transcript_path) if transcript_path else 0
    except OSError:
        size = 0
    if scope.get("faction") and size >= MIN_TRANSCRIPT:
        f = cfg.faction(scope["faction"])
        name = f.name if f else scope["faction"]
        return (f"Before you finish: this session looked like work toward **{name}**"
                + (f" › {f.arc(scope['arc']).name}" if f and scope.get("arc") and f.arc(scope["arc"]) else "")
                + ". If it moved a quest forward, `quest_attach` this session to it (and `quest_update` the next step); "
                "if it started something new, propose a quest with `quest_create`. Skip if it doesn't fit.")
    return None


def hook(stdin_json: str) -> str | None:
    if os.environ.get("QUESTLOG_SCRIBE"):
        return None
    try:
        data = json.loads(stdin_json or "{}")
    except ValueError:
        return None
    sid = data.get("session_id")
    if not sid or data.get("stop_hook_active"):
        return None
    DIR.mkdir(parents=True, exist_ok=True)
    done = DIR / sid
    if done.exists():
        return None
    reason = check(sid, data.get("transcript_path", ""))
    if not reason:
        return None
    done.write_text(str(time.time()))
    return json.dumps({"decision": "block", "reason": reason})
