"""The event journal: what changed, so agents can be told.

Every quest write is diffed against what was on disk and turned into events, appended to
<root>/.questlog/events.jsonl. Agents read them through their inbox (a per-session cursor),
which reaches them on their next prompt, in MCP responses, and in the hub's toasts.

Kinds: quest_added, activated (became active, e.g. its prerequisites were met), assigned (new lead),
objective_done, blocked, unblocked, waiting (needs the game master), answered (waiting cleared),
completed, parked, suggested.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from . import config as cfgmod


def _file(cfg: cfgmod.Config) -> Path:
    cfg.meta_dir.mkdir(parents=True, exist_ok=True)
    return cfg.meta_dir / "events.jsonl"


def emit(cfg: cfgmod.Config, kind: str, *, ref: str = "", title: str = "", faction: str = "", arc: str = "",
         lead: str = "", summary: str = "", by: str = "") -> dict:
    ev = {"ts": time.time(), "kind": kind, "ref": ref, "title": title, "faction": faction, "arc": arc,
          "lead": lead, "summary": summary[:240], "by": by or os.environ.get("QUESTLOG_AGENT", "")}
    with _file(cfg).open("a") as fh:   # single small appends are atomic enough for a log
        fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return ev


def read(cfg: cfgmod.Config, since: float = 0.0) -> list[dict]:
    f = cfg.meta_dir / "events.jsonl"
    if not f.exists():
        return []
    out = []
    for line in f.read_text().splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("ts", 0) > since:
            out.append(ev)
    return out


def diff(cfg: cfgmod.Config, old, new) -> list[dict]:
    """Events implied by a quest going from `old` (None if new) to `new`."""
    base = {"ref": new.ref, "title": new.title, "faction": new.faction, "arc": new.arc, "lead": new.lead}
    out: list[tuple[str, str]] = []
    if old is None:
        out.append(("quest_added", f"New quest: {new.title}" + (f". Next: {new.next}" if new.next else "")))
        if new.status == "parked" and new.after:
            out.append(("parked", f"Locked until {new.after} is done"))
    else:
        if old.status != new.status:
            if new.status == "done":
                out.append(("completed", f"Quest complete: {new.title}"))
            elif new.status == "blocked":
                out.append(("blocked", f"Blocked: {new.next or new.save_state[:120]}"))
            elif old.status == "blocked" and new.status == "active":
                out.append(("unblocked", f"Unblocked. Next: {new.next}"))
            elif new.status == "active" and old.status in ("parked", "done"):
                out.append(("activated", f"Now active. Next: {new.next}"))
            elif new.status == "parked":
                out.append(("parked", "Parked for now"))
        if new.waiting and new.waiting != old.waiting:
            out.append(("waiting", f"Waiting on the game master: {new.waiting}"))
        elif old.waiting and not new.waiting:
            out.append(("answered", f"No longer waiting ({old.waiting[:80]}). Next: {new.next}"))
        if new.lead and new.lead != old.lead:
            out.append(("assigned", f"{new.lead} now leads this quest. Next: {new.next}"))
        old_done = {t for c, t in old.objectives if c}
        for c, t in new.objectives:
            if c and t not in old_done:
                out.append(("objective_done", f"Objective done: {t}"))
    return [{"kind": k, "summary": s, **base} for k, s in out]
