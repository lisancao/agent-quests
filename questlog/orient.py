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
        line = f"- {day} `{r['id'][:8]}` {_short(r.get('title', ''), 50)}: {_short(r.get('digest', ''), 140)}"
        if r.get("advice"):
            line += f" Tip: {_short(r['advice'], 140)}"
        out.append(line)
    return out


def _quest_tip(cfg: cfgmod.Config, ref: str, exclude: str) -> str:
    """The most recent concrete advice left by a session that worked on this quest."""
    rows = [r for r in ledger.sessions(cfg).values()
            if ref in (r.get("quests") or []) and r.get("advice") and r.get("id") != exclude]
    if not rows:
        return ""
    r = max(rows, key=lambda r: r.get("ended", r.get("recorded", 0)))
    return f"- Tip from the last session on it (`{r['id'][:8]}`): {_short(r['advice'], 220)}"


def resolve(cfg: cfgmod.Config, session_id: str = "", cwd: str = "", prompt: str = "") -> "match.Hit | None":
    """Which goal this session serves: its bound quest, what the ledger says, or the best match."""
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
    return hit


def briefing(cfg: cfgmod.Config, session_id: str = "", cwd: str = "", prompt: str = "",
             hit: "match.Hit | None" = None) -> str:
    hit = hit or resolve(cfg, session_id, cwd, prompt)
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
                         f"Done when: {_short(q.done, 120) or '-'}. Next: {_short(q.next, 120) or '-'}"
                         + (f". Objective {q.progress}: {q.current_objective}" if q.current_objective else ""))
            tip = _quest_tip(cfg, q.ref, session_id)
            if tip:
                lines.append(tip)
            auth = q.authority or "autonomous"
            if auth != "autonomous":
                lines.append(f"- Authority: {auth}: {store.AUTHORITY_NOTE[auth]}")
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
    """UserPromptSubmit hook. First prompt: orientation. Later prompts: what changed since, if anything."""
    import os
    from . import inbox
    if os.environ.get("QUESTLOG_SCRIBE"):
        return None
    try:
        data = json.loads(stdin_json or "{}")
    except ValueError:
        return None
    sid = data.get("session_id") or ""
    STATE.mkdir(parents=True, exist_ok=True)
    mark = STATE / f"{sid or 'none'}"
    cfg = cfgmod.load()
    agent = os.environ.get("QUESTLOG_AGENT", "")
    if sid and mark.exists():
        evs = inbox.read(sid, agent, cfg)
        if not evs:
            return None
        text = ("## Since you last looked (questlog)\n" + inbox.render(evs) +
                "\nIf any of this changes your plan, say so; keep the quest current with `quest_update`.")
    else:
        hit = resolve(cfg, sid, data.get("cwd", ""), data.get("prompt", ""))
        text = briefing(cfg, sid, data.get("cwd", ""), data.get("prompt", ""), hit=hit)
        if sid:
            mark.write_text(str(time.time()))
            if hit and hit.score >= match.STRONG:
                inbox.set_scope(sid, hit.faction, hit.arc, hit.quest, agent)
            else:
                inbox.set_scope(sid, agent=agent)
            cutoff = time.time() - 14 * 86400   # marks only matter during a session's life
            for m in STATE.iterdir():
                try:
                    if m.stat().st_mtime < cutoff:
                        m.unlink()
                except OSError:
                    pass
    return json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": text}})
