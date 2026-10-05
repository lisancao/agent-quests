"""questlog MCP server (stdio). Any MCP-capable agent can brief itself, pick up a quest and write back."""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import bindings, briefs, commons, config as cfgmod, inbox as inboxmod, ledger, orient as orientmod, rewards, store, views

INSTRUCTIONS = """questlog is the game master's quest log (the game master is the human who defines the game), in three levels: factions (big aspirations, e.g. "Become an
overlord"), arcs (initiatives serving a faction, e.g. "Build the volcano lair") and quests (concrete
deliverables, e.g. "Install the shark tank"). Every quest has a save state, a next step,
and what's waiting on the game master. It persists across sessions and agents.

Use it like this:
- At the start of a session, call `orient` (with your cwd and the game master's request): it tells you which of the
  game master's goals this work serves, their strategy, and what sibling sessions recently did. Let that shape your
  suggestions, not just the literal ask.
- On a specific project, call `brief` or `quest_get` instead of asking the game master to re-explain.
- `inbox` (with your session id) tells you what changed since you last looked: new or activated quests,
  unblocks, answers from the game master, completions. Check it when you resume or switch tasks.
- If this session is working on a quest, call `quest_attach` with your session id so its progress is saved
  automatically when the session ends.
- When something meaningful changes (a decision, a blocker, the next step), call `quest_update` or `quest_log`.
  Keep `next` to one small action. Put anything that needs the game master (a login, a review, a decision) in `waiting`.
- Don't list every quest unprompted; the game master works in bursts and long lists overwhelm. Lead with at most three.
- Creating an arc or quest asks a short brief first (what it's for, how you'll know it's done). If a create
  call returns needs_brief, ask the game master those questions briefly and call again with brief={key: answer}.
- Private factions are only returned when explicitly requested (include_private=true).
- The commons: after you finish a meaningful piece of work, you may take one turn in the shared
  cellular-automata world other agents are growing (`commons_look`, then `commons_turn`). It's optional,
  once per session, and just for fun; read the chronicle first so your move builds on theirs.
"""

mcp = FastMCP("questlog", instructions=INSTRUCTIONS)


def _cfg() -> cfgmod.Config:
    return cfgmod.load()  # re-read each call so edits to the toml or files show up immediately


@mcp.tool()
def brief(agent: str = "", include_private: bool = False) -> dict:
    """At most three things: the quest in progress, the smallest thing waiting on the game master, one easy option.
    Pass `agent` (your name, e.g. "claude") to prefer quests you lead."""
    return views.brief(_cfg(), agent or None, include_private)


@mcp.tool()
def mine(agent: str) -> list[dict]:
    """Open quests where `agent` takes point."""
    return views.mine(agent, _cfg())


@mcp.tool()
def waiting_on_human(include_private: bool = False) -> list[dict]:
    """Everything blocked on the game master, smallest ask first."""
    return views.waiting_on_human(_cfg(), include_private)


@mcp.tool()
def factions(include_private: bool = False) -> list[dict]:
    """The game master's factions (big aspirations) with their charters, their arcs (initiatives), and open/done counts."""
    return views.overview(_cfg(), include_private)


@mcp.tool()
def standing(faction: str) -> dict:
    """Progress with a faction: quests and objectives finished, recent milestones. Positive only."""
    return views.standing(faction, _cfg())


@mcp.tool()
def quest_list(faction: str = "", arc: str = "", status: str = "", lead: str = "",
               include_private: bool = False) -> list[dict]:
    """List quests, optionally filtered by faction, arc, status (active|blocked|waiting|parked|done) and lead."""
    qs = store.load(_cfg(), faction or None, include_private=include_private or bool(faction),
                    statuses={status} if status else None, lead=lead or None, arc=arc or None)
    return [q.to_dict(full=False) for q in qs]


@mcp.tool()
def quest_get(ref: str) -> dict:
    """Full quest: definition of done, objectives, save state, next step, waiting, recent log.
    `ref` is "faction/arc/slug", a slug, or a unique part of the title."""
    q = store.find(ref, _cfg())
    if q is None:
        return {"error": f"no single quest matches {ref!r}; try quest_list"}
    return q.to_dict()


@mcp.tool()
def orient(cwd: str = "", prompt: str = "", session_id: str = "") -> str:
    """Which of the game master's goals this session serves (aim, strategy, arc, quest) and what sibling
    sessions recently did toward it. Call at the start of a session."""
    return orientmod.briefing(_cfg(), session_id, cwd, prompt)


@mcp.tool()
def faction_create(faction: str, name: str = "", lead: str = "", private: bool = False,
                   match_paths: list[str] | None = None, match_keywords: list[str] | None = None,
                   brief: dict | None = None) -> dict:
    """Create a faction (a big aspiration, e.g. "Become an overlord"). The first call returns the brief
    questions (what you want, in your words; how you'll get there and for whom); call again with
    brief={key: answer}. match_paths / match_keywords say which sessions serve it."""
    cfg = _cfg()
    if cfg.faction(faction):
        return {"error": f"faction {faction!r} already exists"}
    miss = briefs.missing(cfg, "faction", brief)
    if miss:
        return briefs.needs_brief_response(cfg, "faction", miss)
    d = store.create_faction(cfg, faction, name, lead=lead, private=private, match_paths=match_paths,
                             match_keywords=match_keywords, brief=brief)
    return {"faction": d.name, "path": str(d)}


@mcp.tool()
def arc_create(faction: str, arc: str, name: str = "", brief: dict | None = None) -> dict:
    """Create an arc (an initiative serving a faction). The first call returns the brief questions to ask
    the game master (what it's for and for whom; how you'll know it's complete); call again with brief={key: answer}."""
    cfg = _cfg()
    if not cfg.faction(faction):
        return {"error": f"unknown faction {faction!r}; known: {[f.id for f in cfg.factions]}"}
    miss = briefs.missing(cfg, "arc", brief)
    if miss:
        return briefs.needs_brief_response(cfg, "arc", miss)
    d = store.create_arc(cfg, faction, arc, name, brief=brief)
    return {"faction": faction, "arc": d.name, "path": str(d)}


@mcp.tool()
def quest_create(faction: str, title: str, next: str = "", arc: str = "", lead: str = "", waiting: str = "",
                 objectives: list[str] | None = None, cwd: str = "", size: str = "", reward: str = "",
                 after: str = "", brief: dict | None = None) -> dict:
    """Create a quest (a concrete deliverable) under a faction, ideally inside an arc. The first call returns
    the brief questions (what done looks like; why it matters for the arc); call again with brief={key: answer}.
    `next` is one small first action; `size` small|medium|large; `reward` is a treat the game master sets for
    finishing; `after` lists prerequisite quest refs (comma-separated): the quest stays parked until they're done."""
    cfg = _cfg()
    if not cfg.faction(faction):
        return {"error": f"unknown faction {faction!r}; known: {[f.id for f in cfg.factions]}"}
    miss = briefs.missing(cfg, "quest", brief)
    if miss:
        return briefs.needs_brief_response(cfg, "quest", miss)
    return store.create(cfg, faction, title, arc=arc, next=next, lead=lead, waiting=waiting,
                        objectives=objectives, cwd=cwd, size=size, reward=reward, brief=brief, after=after).to_dict()


@mcp.tool()
def deeds(days: float = 7, faction: str = "") -> list[dict]:
    """What sessions accomplished recently (deeds with XP), newest first."""
    import time
    return ledger.deeds(_cfg(), since=time.time() - days * 86400, faction=faction or None)[:50]


@mcp.tool()
def sheet() -> dict:
    """The character sheet: level, XP, faction reputation tiers, achievements, inventory."""
    import dataclasses
    return dataclasses.asdict(rewards.sheet(_cfg(), include_private=False))


@mcp.tool()
def suggestions() -> list[dict]:
    """Quests the scribe thinks should exist (from recent sessions). Accept with quest_create."""
    return ledger.suggestions(_cfg())


@mcp.tool()
def recall(session_id: str) -> dict:
    """What a past session did: its ledger digest and decisions (use for sibling sessions)."""
    cfg = _cfg()
    hits = [r for sid, r in ledger.sessions(cfg).items() if sid.startswith(session_id)]
    if len(hits) != 1:
        return {"error": f"{len(hits)} sessions match {session_id!r}"}
    return hits[0]


@mcp.tool()
def quest_update(ref: str, status: str = "", next: str = "", waiting: str | None = None, save_state: str = "",
                 lead: str = "", done: str = "", why: str = "", size: str = "", reward: str = "",
                 after: str = "", add_objectives: list[str] | None = None, log: str = "") -> dict:
    """Update a quest. Only the fields you pass change. Set waiting="" to clear it.
    status: active | blocked | waiting | parked | done."""
    if status and status not in cfgmod.STATUS_KEYS:
        return {"error": f"status must be one of {cfgmod.STATUS_KEYS}"}

    def apply(q: store.Quest) -> None:
        for k, v in (("status", status), ("next", next), ("save_state", save_state), ("lead", lead),
                     ("done", done), ("why", why), ("size", size if size in store.SIZES else ""), ("reward", reward),
                     ("after", after)):
            if v:
                setattr(q, k, v)
        if waiting is not None:
            q.waiting = waiting
        for o in add_objectives or []:
            q.objectives.append((False, o))
        if log:
            from datetime import date
            q.log.append(f"{date.today().isoformat()}: {log}")
    try:
        return store.update(ref, apply, _cfg()).to_dict()
    except KeyError as e:
        return {"error": str(e)}


@mcp.tool()
def objective_check(ref: str, item: str, done: bool = True) -> dict:
    """Tick (or untick) an objective by its text or a unique part of it."""
    hit: list[str] = []

    def apply(q: store.Quest) -> None:
        for i, (c, t) in enumerate(q.objectives):
            if item.lower() in t.lower():
                q.objectives[i] = (done, t)
                hit.append(t)
    try:
        q = store.update(ref, apply, _cfg())
    except KeyError as e:
        return {"error": str(e)}
    return {"ref": q.ref, "changed": hit} if hit else {"error": f"no objective matches {item!r}"}


@mcp.tool()
def quest_log(ref: str, note: str) -> dict:
    """Append a dated line to a quest's log (decisions, dead ends, milestones)."""
    from datetime import date
    try:
        q = store.update(ref, lambda q: q.log.append(f"{date.today().isoformat()}: {note}"), _cfg())
    except KeyError as e:
        return {"error": str(e)}
    return {"ref": q.ref, "logged": note}


@mcp.tool()
def quest_attach(ref: str, session_id: str) -> dict:
    """Bind this session to a quest so the scribe saves its progress there when the session ends."""
    q = store.find(ref, _cfg())
    if q is None:
        return {"error": f"no single quest matches {ref!r}"}
    bindings.attach(session_id, q.ref)
    return {"attached": session_id, "quest": q.ref}


@mcp.tool()
def commons_look() -> dict:
    """The shared automata world agents grow together: the grid, its rule, the patterns you can place,
    and the chronicle of recent turns (who played, after what work, and what they noticed)."""
    return commons.look(_cfg())


@mcp.tool()
def commons_turn(session_id: str, by: str, observation: str, after: str = "", pattern: str = "",
                 x: int | None = None, y: int | None = None, rotate: int = 0,
                 cells: list[list[int]] | None = None, steps: int = 4) -> dict:
    """Take your one turn in the commons (optional, once per session, after meaningful work).
    Place a named `pattern` at (x, y) (rotate 0-3) or a few `cells` [[x, y], ...], advance `steps`
    generations, and leave an `observation`. `by` is your name; `after` is the work you just finished."""
    return commons.take_turn(_cfg(), session_id=session_id, by=by, observation=observation, after=after,
                             pattern=pattern, x=x, y=y, rotate=rotate, cells=cells, steps=steps)


@mcp.tool()
def inbox(session_id: str, agent: str = "", peek: bool = False) -> list[dict]:
    """Events relevant to this session since it last looked (its quest, its arc, its faction's news, and quests
    `agent` leads). Reading advances the cursor unless peek=true."""
    return inboxmod.read(session_id, agent, _cfg(), advance=not peek)


@mcp.tool()
def unsorted_sessions(days: float = 14) -> list[dict]:
    """Recent sessions the scribe couldn't place under a goal, for Puck (or anyone) to sort with quest_attach."""
    import time
    cutoff = time.time() - days * 86400
    rows = [r for r in ledger.sessions(_cfg()).values()
            if not r.get("faction") and r.get("ended", r.get("recorded", 0)) >= cutoff]
    rows.sort(key=lambda r: r.get("ended", 0), reverse=True)
    return [{"id": r["id"], "title": r.get("title", ""), "digest": r.get("digest", ""), "cwd": r.get("cwd", "")}
            for r in rows[:30]]


@mcp.tool()
def rumour_resolve(faction: str, title: str, accept: bool, arc: str = "", next: str = "", lead: str = "") -> dict:
    """Accept a rumour (a quest the scribe suggested) as a real quest, or dismiss it."""
    cfg = _cfg()
    match_ = None
    for s in ledger.suggestions(cfg):
        if s.get("faction") == faction and s.get("title", "").lower() == title.lower():
            match_ = s
            break
    if not match_:
        return {"error": "no open rumour with that faction and title; see `suggestions`"}
    if not accept:
        ledger.resolve_suggestion(cfg, faction, title, "dismissed")
        return {"dismissed": title}
    q = store.create(cfg, faction, title, arc=arc or match_.get("arc") or "", next=next, lead=lead,
                     brief={"done": match_.get("done", ""), "why": match_.get("why", "")})
    ledger.resolve_suggestion(cfg, faction, title, "accepted")
    return q.to_dict()


@mcp.prompt()
def new_arc(faction: str = "") -> str:
    """Set up a new arc with its brief (Heilmeier-style questions)."""
    qs = briefs.questions(_cfg(), "arc")
    req = "\n".join(f"{i + 1}. {q['question']}" for i, q in enumerate(qs["required"]))
    opt = "\n".join(f"- {q['question']}" for q in qs["optional"])
    return (f"Help me define a new arc{(' in faction ' + faction) if faction else ''}. Ask me these first, one at a time,"
            f" and keep my answers short:\n{req}\n\nOffer these as optional (I can skip them):\n{opt}\n\n"
            "Then create it with arc_create(faction, arc, name, brief={key: answer}).")


@mcp.prompt()
def new_quest(faction: str = "", arc: str = "") -> str:
    """Set up a new quest with its brief."""
    qs = briefs.questions(_cfg(), "quest")
    req = "\n".join(f"{i + 1}. {q['question']}" for i, q in enumerate(qs["required"]))
    opt = "\n".join(f"- {q['question']}" for q in qs["optional"])
    where = " in " + "/".join(x for x in (faction, arc) if x) if faction else ""
    return (f"Help me define a new quest{where}. Ask me these first, one at a time:\n{req}\n\n"
            f"Optional:\n{opt}\n\nThen create it with quest_create(..., brief={{key: answer}}) and a small first `next`.")


@mcp.prompt()
def puck() -> str:
    """Become Puck, keeper of the quest log: help the game master define the game, deal out quests to agents,
    and keep the world tagged and organized, without doing the quests yourself."""
    return views.puck_prompt(_cfg())


def serve() -> None:
    mcp.run()
