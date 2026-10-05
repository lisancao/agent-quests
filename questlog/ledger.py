"""The session ledger: what every session did and which goals it served.

<root>/.questlog/sessions.jsonl   one record per session (latest wins)
<root>/.questlog/deeds.jsonl      one line per deed (a thing a session accomplished), with XP
<root>/.questlog/suggestions.jsonl quests the scribe thinks should exist
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import config as cfgmod, store


def _file(cfg: cfgmod.Config, name: str) -> Path:
    cfg.meta_dir.mkdir(parents=True, exist_ok=True)
    return cfg.meta_dir / name


def _append(cfg: cfgmod.Config, name: str, rows: list[dict]) -> None:
    if not rows:
        return
    f = _file(cfg, name)
    with store.locked(f):
        with f.open("a") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def _read(cfg: cfgmod.Config, name: str) -> list[dict]:
    f = cfg.meta_dir / name
    if not f.exists():
        return []
    out = []
    for line in f.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


# --- sessions ---------------------------------------------------------------------

def record_session(cfg: cfgmod.Config, rec: dict) -> None:
    rec = {**rec, "recorded": time.time()}
    _append(cfg, "sessions.jsonl", [rec])


def sessions(cfg: cfgmod.Config) -> dict[str, dict]:
    """session id -> latest record."""
    out: dict[str, dict] = {}
    for r in _read(cfg, "sessions.jsonl"):
        if r.get("id"):
            out[r["id"]] = {**out.get(r["id"], {}), **r}
    return out


def session(cfg: cfgmod.Config, sid: str) -> dict | None:
    return sessions(cfg).get(sid)


def recent(cfg: cfgmod.Config, faction: str | None = None, arc: str | None = None, days: float = 7,
           limit: int = 5, exclude: str | None = None) -> list[dict]:
    """Sibling sessions: recent records for the same faction / arc, newest first."""
    cutoff = time.time() - days * 86400
    rows = [r for r in sessions(cfg).values()
            if r.get("ended", r.get("recorded", 0)) >= cutoff and r.get("id") != exclude
            and (not faction or r.get("faction") == faction) and (not arc or r.get("arc") == arc)]
    rows.sort(key=lambda r: r.get("ended", r.get("recorded", 0)), reverse=True)
    return rows[:limit]


# --- deeds ------------------------------------------------------------------------

def add_deeds(cfg: cfgmod.Config, deeds: list[dict]) -> None:
    _append(cfg, "deeds.jsonl", deeds)


def deeds(cfg: cfgmod.Config, since: float = 0, faction: str | None = None) -> list[dict]:
    rows = [d for d in _read(cfg, "deeds.jsonl") if d.get("ts", 0) >= since and (not faction or d.get("faction") == faction)]
    rows.sort(key=lambda d: d.get("ts", 0), reverse=True)
    return rows


def replace_session_deeds(cfg: cfgmod.Config, sid: str, new: list[dict]) -> None:
    """A session's deeds are recomputed each scribe pass; keep only the latest set."""
    f = _file(cfg, "deeds.jsonl")
    with store.locked(f):
        keep = [d for d in _read(cfg, "deeds.jsonl") if d.get("session") != sid]
        tmp = f.with_suffix(".tmp")
        tmp.write_text("".join(json.dumps(d, ensure_ascii=False) + "\n" for d in keep + new))
        tmp.replace(f)


# --- suggestions --------------------------------------------------------------------

def suggest(cfg: cfgmod.Config, suggestion: dict) -> None:
    existing = {(s.get("faction"), s.get("title", "").lower()) for s in suggestions(cfg)}
    if (suggestion.get("faction"), suggestion.get("title", "").lower()) not in existing:
        _append(cfg, "suggestions.jsonl", [{**suggestion, "ts": time.time(), "state": "open"}])


def suggestions(cfg: cfgmod.Config, open_only: bool = True) -> list[dict]:
    latest: dict[tuple, dict] = {}
    for s in _read(cfg, "suggestions.jsonl"):
        latest[(s.get("faction"), s.get("title", "").lower())] = s
    rows = list(latest.values())
    return [s for s in rows if s.get("state") == "open"] if open_only else rows


def resolve_suggestion(cfg: cfgmod.Config, faction: str, title: str, state: str) -> None:
    for s in suggestions(cfg, open_only=False):
        if s.get("faction") == faction and s.get("title", "").lower() == title.lower():
            _append(cfg, "suggestions.jsonl", [{**s, "state": state, "ts": time.time()}])
            return
