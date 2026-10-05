"""Orientation: what a session is told on its first prompt so it can work toward the human's goals.

A matched session gets: the faction's intent and strategy, the arc's goal and definition of complete,
the quest's why / done / next (when it's specific), and recent sibling sessions on the same goal.
An unmatched session gets a compact map of the goals and is asked to attach itself if one fits.
"""
from __future__ import annotations

import json
import time
from datetime import datetime

from . import bindings, config as cfgmod, ledger, match, store

MAX_CHARS = 1600
STATE = cfgmod.STATE_DIR / "oriented"


def _short(s: str, n: int) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _siblings(cfg: cfgmod.Config, faction: str, arc: str, exclude: str) -> list[str]:
    rows = ledger.recent(cfg, faction=faction, arc=arc or None, days=10, limit=3, exclude=exclude)
    if len(rows) < 3 and arc:
        more = ledger.recent(cfg, faction=faction, days=10, limit=3, exclude=exclude)
        rows += [r for r in more if r["id"] not in {x["id"] for x in rows}][: 3 - len(rows)]
    out = []
    for r in rows:
        day = datetime.fromtimestamp(r.get("ended", r.get("recorded", 0))).strftime("%b %d")
        out.append(f"- {day} `{r['id'][:8]}` {_short(r.get('title', ''), 50)}: {_short(r.get('digest', ''), 140)}")
    return out


def briefing(cfg: cfgmod.Config, session_id: str = "", cwd: str = "", prompt: str = "") -> str:
    hit = None
    bound = bindings.quest_for(session_id) if session_id else None
    if bound:
        q = store.find(bound, cfg)
        if q:
            hit = match.Hit(q.faction, q.arc, q.ref, 99, "bound to this quest")
    if hit is None:
        prior = ledger.session(cfg, session_id) if session_id else None
        if prior and prior.get("faction"):
            hit = match.Hit(prior["faction"], prior.get("arc", ""), (prior.get("quests") or [""])[0], 5, "seen before")
    if hit is None:
        hit = match.best(cfg, cwd=cwd, text=prompt)

    lines: list[str] = []
    if hit and hit.score >= match.STRONG:
        f = cfg.faction(hit.faction)
        a = f.arc(hit.arc) if f and hit.arc else None
        lines.append(f"## Orientation (questlog): this session likely serves **{f.name if f else hit.faction}**"
                     + (f" › **{a.name}**" if a else "") + f"  ({hit.why})")
        if f and f.intent:
            lines.append(f"- {cfg.human}'s aim: {_short(f.intent, 200)}")
        if f and f.strategy:
            lines.append(f"- Strategy: {_short(f.strategy, 220)}")
        if a and a.goal:
            lines.append(f"- Arc goal: {_short(a.goal, 180)}" + (f" Complete when: {_short(a.complete_when, 140)}"
                                                                    if a.complete_when else ""))
        q = store.find(hit.quest, cfg) if hit.quest else None
        if q:
            lines.append(f"- Quest `{q.ref}`: {q.title}. Why: {_short(q.why, 120) or '-'}. "
                         f"Done when: {_short(q.done, 120) or '-'}. Next: {_short(q.next, 120) or '-'}")
        elif f:
            open_q = [x for x in store.load(cfg, faction=f.id, arc=hit.arc or None) if x.status in ("active", "blocked", "waiting")]
            if open_q:
                lines.append("- Open quests here: " + "; ".join(f"`{x.ref}` {_short(x.title, 50)}" for x in open_q[:4]))
        sib = _siblings(cfg, hit.faction, hit.arc, session_id)
        if sib:
            lines.append("Sibling sessions on the same goal (recent):")
            lines += sib
        lines.append("Use this to make suggestions that serve the aim, not just the literal ask. "
                     "If this session is working on one of these quests, call `quest_attach` so progress is saved; "
                     "`questlog recall <id>` (or the session id) shows what a sibling did.")
    else:
        lines.append(f"## Orientation (questlog): {cfg.human}'s goals, in case this session serves one")
        if hit and hit.score > 0:
            hf = cfg.faction(hit.faction)
            if hf:
                lines.append(f"- Possibly **{hf.name}** ({hit.why}). Strategy: {_short(hf.strategy, 160) or '-'}")
        for f in cfg.factions:
            if f.private:
                continue
            arcs = ", ".join(a.name for a in f.arcs[:4])
            lines.append(f"- **{f.name}**: {_short(f.intent, 90)}" + (f" (arcs: {arcs})" if arcs else ""))
        lines.append("If the work fits one, mention it and use its aim to guide suggestions; "
                     "`quest_attach` binds the session to a quest so progress is saved.")
    text = "\n".join(lines)
    return text if len(text) <= MAX_CHARS else text[: MAX_CHARS - 1] + "…"


def hook(stdin_json: str) -> str | None:
    """UserPromptSubmit hook: orient once per session. Returns hook JSON or None."""
    import os
    if os.environ.get("QUESTLOG_SCRIBE"):
        return None
    try:
        data = json.loads(stdin_json or "{}")
    except ValueError:
        return None
    sid = data.get("session_id") or ""
    STATE.mkdir(parents=True, exist_ok=True)
    mark = STATE / f"{sid or 'none'}"
    if sid and mark.exists():
        return None
    cfg = cfgmod.load()
    text = briefing(cfg, sid, data.get("cwd", ""), data.get("prompt", ""))
    if sid:
        mark.write_text(str(time.time()))
        # Old marks only matter during a session's life.
        cutoff = time.time() - 14 * 86400
        for m in STATE.iterdir():
            try:
                if m.stat().st_mtime < cutoff:
                    m.unlink()
            except OSError:
                pass
    return json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": text}})
