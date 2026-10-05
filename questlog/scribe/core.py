"""The scribe: after (and during) every session, record what it did and which goals it served.

One cheap LLM pass per session (throttled while it's live) returns:
  - where it belongs: faction / arc / quest (or none), with confidence
  - a short digest and the decisions made (so sibling sessions can learn from it)
  - deeds: what it accomplished, sized for XP
  - for a quest-bound session: the quest's new save state, next step, waiting and status
  - a suggested quest, when the work fits an arc but no existing quest
It never runs inside its own LLM call (QUESTLOG_SCRIBE), and a quest is only marked done
when the transcript shows its definition of done is met.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import date, datetime
from pathlib import Path

from .. import bindings, config as cfgmod, ledger, store
from . import claude_code

STATE = cfgmod.STATE_DIR / "scribe"
LOG = cfgmod.STATE_DIR / "scribe.log"
MIN_GROWTH = 2000      # bytes of new transcript before another pass is worth it
MIN_SIZE = 6000        # sessions smaller than this are too slight to record
HIGH_CONFIDENCE = 0.75
HEADLESS = ("sdk-cli", "sdk-py", "sdk-ts")  # `claude -p` / SDK runs: helpers, not the human's sessions

PROMPT = """You are the scribe for {human}'s quest log. Read the work session below and record what it did
for {human}'s goals. Be concrete and faithful: only what actually happened in the transcript.

{human}'s goals (faction > arc > open quests; ids and refs in backticks):
{goal_map}

{bound_block}{voice_block}
Reply with ONLY a JSON object:
{"faction": "<faction id or empty>", "arc": "<arc id or empty>", "quest": "<quest ref or empty>",
 "confidence": <0..1, how sure the session serves that faction/arc/quest>,
 "title": "<5-8 word title for the session>",
 "digest": "<2-4 sentences: what was done and where it stands, useful to a sibling session>",
 "journal_entry": "<one line for the quest's log: what this session moved forward>",
 "decisions": ["<decision or dead end worth remembering>"],
 "deeds": [{"text": "<a concrete accomplishment>", "size": "small" | "medium" | "large"}],
 "suggested_quest": {"faction": "...", "arc": "...", "title": "...", "done": "...", "why": "..."} or null,
 "quest_update": {"save_state": "<where the bound quest stands, at most 10 short lines>",
                  "next": "<one small next action>", "waiting": "<what's blocked on {human}, or empty>",
                  "status": "active" | "blocked" | "waiting" | "done",
                  "done_met": true | false,
                  "objectives_done": ["<exact text of objectives completed>"]} or null}

Rules: deeds are real outcomes (a decision made, a draft written, a bug fixed, research done), not chatter;
most sessions have 0-3. Sizes: "small" = a step, "medium" = a meaningful piece of work, "large" = a milestone
(something shipped, published or completed); at most one large per session. Keep the digest, decisions and
deeds discreet: describe progress at the level of the project, never intimate or personal detail, because
they're shown to other sessions and on a dashboard. quest_update only if a quest is bound above. Status "done"
only if done_met is true, meaning the definition of done is visibly met. suggested_quest only if the work
clearly serves an arc and none of its quests fit.

=== SESSION ===
{transcript}
"""


def _log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(f"{datetime.now():%F %T} {msg}\n")


def _resolve(ref_or_path: str, cfg: cfgmod.Config) -> store.Quest | None:
    p = Path(os.path.expanduser(ref_or_path))
    if p.suffix == ".md":
        if p.exists():
            return store.quest_from_path(p, cfg)
        return store.find(p.stem, cfg)  # the quest moved (e.g. into an arc); find it by name
    return store.find(ref_or_path, cfg)


def goal_map(cfg: cfgmod.Config) -> str:
    lines = []
    qs = [q for q in store.load(cfg) if q.status != "done"]
    for f in cfg.factions:
        lines.append(f"- faction `{f.id}` {f.name}: {f.intent}"[:220])
        for a in f.arcs:
            lines.append(f"  - arc `{a.id}` {a.name}: {a.goal}"[:200])
            lines += [f"    - quest `{q.ref}` {q.title}"[:160] for q in qs if q.faction == f.id and q.arc == a.id]
        lines += [f"  - quest `{q.ref}` {q.title}"[:160] for q in qs if q.faction == f.id and not q.arc]
    return "\n".join(lines)


def _call(cfg: cfgmod.Config, prompt: str) -> dict | None:
    env = {**os.environ, "QUESTLOG_SCRIBE": "1"}
    for var in ("QUESTLOG_QUEST",):
        env.pop(var, None)
    try:
        res = subprocess.run([*cfg.scribe_command, prompt], capture_output=True, text=True, timeout=240, env=env)
    except (OSError, subprocess.TimeoutExpired) as e:
        _log(f"scribe command failed: {e}")
        return None
    m = re.search(r"\{.*\}", res.stdout, re.S)
    if not m:
        _log(f"no JSON from scribe: {(res.stderr or res.stdout).strip()[:200]}")
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None


def _xp(cfg: cfgmod.Config, size: str) -> int:
    return cfg.xp.get(f"deed_{size}", cfg.xp["deed_small"])


def run(session_id: str, quest_ref: str | None = None, *, throttle: bool = False,
        cfg: cfgmod.Config | None = None, force: bool = False) -> str:
    cfg = cfg or cfgmod.load()
    tpath = claude_code.transcript_path(session_id)
    if tpath is None:
        return "no transcript"
    size = tpath.stat().st_size
    bound = _resolve(quest_ref, cfg) if quest_ref else None
    if not bound and size < MIN_SIZE:
        return "too small"
    if not bound and claude_code.meta(tpath).get("entrypoint") in HEADLESS:
        return "headless helper run, skipped"
    STATE.mkdir(parents=True, exist_ok=True)
    sf = STATE / f"{session_id}.json"
    try:
        st = json.loads(sf.read_text())
    except (OSError, ValueError):
        st = {}
    if not force:
        if size <= st.get("size", 0) + MIN_GROWTH:
            return "nothing new"
        if throttle and time.time() - st.get("at", 0) < cfg.scribe_throttle_minutes * 60:
            return "throttled"

    bound_block = ""
    if bound:
        bound_block = f"This session is BOUND to quest `{bound.ref}`. Its file as it stands:\n{bound.path.read_text()}\n"
    voice_block = ("\nVOICE: write each deed's text and the journal_entry in the voice of an in-world RPG "
                   "quest journal (vivid, a little playful, past tense), while staying faithful and specific: no "
                   "invented events. Keep digest, decisions, save_state and next plain and factual; agents read those.\n"
                   if cfg.journal_voice else "")
    prompt = (PROMPT.replace("{human}", cfg.human).replace("{goal_map}", goal_map(cfg)).replace("{voice_block}", voice_block)
              .replace("{bound_block}", bound_block).replace("{transcript}", claude_code.condense(tpath)))
    out = _call(cfg, prompt)
    if out is None:
        return "scribe failed"

    faction, arc = out.get("faction") or "", out.get("arc") or ""
    quest_ref = out.get("quest") or ""
    try:
        conf = float(out.get("confidence") or 0)
    except (TypeError, ValueError):
        conf = 0.0
    if bound:
        faction, arc, quest_ref, conf = bound.faction, bound.arc, bound.ref, 1.0
    f = cfg.faction(faction) if faction else None
    if faction and not f:
        faction, arc, quest_ref, conf = "", "", "", 0.0
    if f and arc and not f.arc(arc):
        arc = ""
    keep = conf >= 0.5
    meta = claude_code.meta(tpath)
    now = tpath.stat().st_mtime
    ledger.record_session(cfg, {
        "id": session_id, "harness": "claude-code", "cwd": meta.get("cwd", ""),
        "started": meta.get("started", 0), "ended": now,
        "title": out.get("title") or meta.get("first_prompt", "")[:60],
        "faction": faction if keep else "", "arc": arc if keep else "",
        "quests": [quest_ref] if quest_ref and keep else [],
        "digest": out.get("digest", ""), "decisions": out.get("decisions") or [], "confidence": conf,
    })
    deeds = []
    large_seen = False
    for d in out.get("deeds") or []:
        if isinstance(d, dict) and d.get("text"):
            sz = d.get("size") if d.get("size") in store.SIZES else "small"
            if sz == "large":
                sz = "medium" if large_seen else sz
                large_seen = True
            deeds.append({"ts": now, "session": session_id, "faction": faction if keep else "",
                          "arc": arc if keep else "", "quest": quest_ref if keep else "",
                          "text": d["text"], "size": sz, "xp": _xp(cfg, sz)})
    ledger.replace_session_deeds(cfg, session_id, deeds)

    sq = out.get("suggested_quest")
    if isinstance(sq, dict) and sq.get("title") and cfg.faction(sq.get("faction") or ""):
        ledger.suggest(cfg, {**sq, "session": session_id})

    target = bound or (store.find(quest_ref, cfg) if quest_ref and conf >= HIGH_CONFIDENCE else None)
    if target:
        upd = out.get("quest_update") if bound else None
        today = date.today().isoformat()

        def apply(q: store.Quest) -> None:
            if isinstance(upd, dict):
                q.save_state = (upd.get("save_state") or q.save_state).strip()
                q.next = upd.get("next") or q.next
                q.waiting = upd.get("waiting", q.waiting) or ""
                status = upd.get("status")
                if status == "done" and not upd.get("done_met"):
                    status = "active"  # never close a quest whose definition of done isn't visibly met
                if status == "done" and (q.authority or "autonomous") != "autonomous":
                    q.waiting = "Sign-off: the session believes the definition of done is met"
                    status = None      # the game master closes it
                if status in cfgmod.STATUS_KEYS:
                    q.status = status
                finished = {s.strip().lower() for s in upd.get("objectives_done") or [] if isinstance(s, str)}
                q.objectives = [(c or t.lower() in finished, t) for c, t in q.objectives]
            if session_id[:8] not in q.sessions:
                q.sessions.append(session_id[:8])
            line = out.get("journal_entry") or out.get("digest") or (deeds[0]["text"] if deeds else "")
            if line:
                q.log.append(f"{today} `{session_id[:8]}`: {' '.join(line.split())[:220]}")

        with store.locked(target.path):
            fresh = store.parse(target.path, target.faction, target.arc)
            apply(fresh)
            store.save(fresh, cfg)

    sf.write_text(json.dumps({"size": size, "at": time.time()}))
    where = "/".join(x for x in (faction, arc) if x) or "unclassified"
    return f"{where} ({conf:.2f}); {len(deeds)} deeds" + (f"; updated {target.ref}" if target else "")


def hook(stdin_json: str, *, throttle: bool) -> None:
    """Entry point for Stop / SessionEnd hooks. Silent and safe: never blocks or fails the session."""
    if os.environ.get("QUESTLOG_SCRIBE"):
        return
    try:
        data = json.loads(stdin_json or "{}")
    except ValueError:
        return
    sid = data.get("session_id")
    if not sid:
        return
    ref = bindings.quest_for(sid)
    os.environ["QUESTLOG_AGENT"] = "scribe"   # events this process emits are the scribe's
    cfg = cfgmod.load()
    if not ref and not cfg.scribe_every_session:
        return
    try:
        msg = run(sid, ref, throttle=throttle, cfg=cfg)
    except Exception as e:  # noqa: BLE001 - a hook must never break the session
        msg = f"error: {type(e).__name__}: {e}"
    _log(f"{sid[:8]} {ref or '-'} {msg}")


def backfill(days: float = 7, limit: int = 200, cfg: cfgmod.Config | None = None, progress=print) -> int:
    """Run the scribe over the last `days` of Claude Code sessions not yet in the ledger."""
    cfg = cfg or cfgmod.load()
    seen = set(ledger.sessions(cfg))
    cutoff = time.time() - days * 86400
    files = [p for p in claude_code.PROJECTS.glob("*/*.jsonl")
             if "subagents" not in p.parts and p.stem not in seen
             and p.stat().st_mtime >= cutoff and p.stat().st_size >= MIN_SIZE
             and claude_code.meta(p).get("entrypoint") not in HEADLESS]
    files.sort(key=lambda p: p.stat().st_mtime)
    for i, p in enumerate(files[:limit]):
        progress(f"[{i + 1}/{min(len(files), limit)}] {p.stem[:8]} {run(p.stem, None, cfg=cfg, force=True)}")
    return min(len(files), limit)
