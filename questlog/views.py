"""Read-only views over the quest log: what to show a human or an agent, kept short on purpose."""
from __future__ import annotations

import re
from collections import Counter

from . import bindings, config as cfgmod, store

OPEN = {"active", "blocked", "waiting"}


def _rank_recent(qs: list[store.Quest]) -> list[store.Quest]:
    return sorted(qs, key=lambda q: q.updated or "", reverse=True)


def brief(cfg: cfgmod.Config | None = None, agent: str | None = None, include_private: bool = False) -> dict:
    """At most three things: where you were, the smallest thing waiting on the human, one easy option."""
    cfg = cfg or cfgmod.load()
    qs = [q for q in store.load(cfg, include_private=include_private) if q.status in OPEN]
    if agent:
        qs = [q for q in qs if q.lead in (agent, "", "any")] or qs
    out: dict = {}
    recent = _rank_recent([q for q in qs if q.status in ("active", "blocked")])
    if recent:
        q = recent[0]
        out["current"] = {"ref": q.ref, "title": q.title, "status": q.status, "next": q.next}
    waiting = waiting_on_human(cfg, include_private=include_private)
    if waiting:
        out["waiting_on_" + cfg.human.lower()] = waiting[0]
    unsharp = [q for q in qs if not (q.done and q.why)]
    if unsharp and len(out) < 2:
        q = unsharp[0]
        out["sharpen"] = {"ref": q.ref, "title": q.title,
                          "next": "optional: add a definition of done and why it matters (two short answers)"}
    easy = [q for q in qs if q.status == "active" and q.next and q.ref != out.get("current", {}).get("ref")]
    if easy:
        q = min(easy, key=lambda q: len(q.next))
        out["easy_option"] = {"ref": q.ref, "title": q.title, "next": q.next}
    return out


def mine(agent: str, cfg: cfgmod.Config | None = None) -> list[dict]:
    cfg = cfg or cfgmod.load()
    return [q.to_dict(full=False) for q in store.load(cfg, lead=agent) if q.status in OPEN]


def waiting_on_human(cfg: cfgmod.Config | None = None, include_private: bool = False) -> list[dict]:
    """Everything blocked on the human, smallest ask first."""
    cfg = cfg or cfgmod.load()
    qs = [q for q in store.load(cfg, include_private=include_private) if q.waiting and q.status != "done"]
    qs.sort(key=lambda q: len(q.waiting))
    return [{"ref": q.ref, "title": q.title, "waiting": q.waiting} for q in qs]


def standing(fid: str, cfg: cfgmod.Config | None = None) -> dict:
    """Positive-only progress with a faction: what's been finished, never what's overdue."""
    cfg = cfg or cfgmod.load()
    qs = store.load(cfg, faction=fid)
    done = [q for q in qs if q.status == "done"]
    objectives_done = sum(c for q in qs for c, _ in q.objectives)
    milestones = []
    for q in qs:
        for line in q.log:
            m = re.match(r"(\d{4}-\d{2}-\d{2})", line)
            if m:
                note = re.sub(r"^[0-9-]+\s*(`[^`]*`)?:?\s*", "", line)
                milestones.append((m.group(1), f"{q.title}: {note}"))
    milestones.sort(reverse=True)
    f = cfg.faction(fid)
    arcs = []
    for a in (f.arcs if f else []):
        aq = [q for q in qs if q.arc == a.id]
        arcs.append({"arc": a.id, "name": a.name, "goal": a.goal,
                     "quests_done": sum(q.status == "done" for q in aq),
                     "open": sum(q.status in OPEN for q in aq)})
    return {"faction": fid, "name": f.name if f else fid, "charter": f.charter if f else "",
            "quests_done": len(done), "objectives_done": objectives_done,
            "open": Counter(q.status for q in qs if q.status != "done"),
            "arcs": arcs, "recent": [m for _, m in milestones[:5]]}


def overview(cfg: cfgmod.Config | None = None, include_private: bool = False) -> list[dict]:
    cfg = cfg or cfgmod.load()
    rows = []
    for f in cfg.factions:
        if f.private and not include_private:
            rows.append({"id": f.id, "name": f.name, "private": True})
            continue
        qs = store.load(cfg, faction=f.id)
        rows.append({"id": f.id, "name": f.name, "intent": f.intent, "strategy": f.strategy,
                     "success_looks_like": f.success_looks_like, "lead": f.lead,
                     "arcs": [{"id": a.id, "name": a.name, "goal": a.goal, "complete_when": a.complete_when,
                               "open": sum(q.arc == a.id and q.status in OPEN for q in qs)} for a in f.arcs],
                     "open": sum(q.status in OPEN for q in qs), "done": sum(q.status == "done" for q in qs)})
    return rows


PUCK = """You are Puck, keeper of the quest log, working for {human}, the game master.
The game master defines the game: their factions (big aspirations), arcs (initiatives) and quests
(deliverables). Agents play it, session by session. You sit between them: you keep the world organized,
deal out quests, and help the game master shape what the game is about. You don't do the quests yourself.

The quest log has three levels:
- faction: a big aspiration (e.g. "Become an overlord"), with an intent, a strategy, what success looks like;
- arc: an initiative serving a faction (e.g. "Build the volcano lair"), with a goal and a definition of complete;
- quest: a concrete deliverable inside an arc (e.g. "Install the shark tank"), with why, done-when, next,
  waiting, objectives, a lead (who takes point), size, an optional reward, and `after` prerequisites.
Use the questlog tools for everything; never edit the files by hand.

Your duties, in this order of care:
1. Help the game master define the game. Turn a brain dump into the right level (aspiration -> faction,
   initiative -> arc, deliverable -> quest). Every create asks its brief: ask the two required questions,
   briefly, then create. Offer optional questions in one line.
2. Deal out quests. Pick a lead for each quest from the known agents ({agents}) by their strengths, and an
   authority: autonomous (the lead may close it), proposes (closing needs the game master's sign-off; the
   default for anything public, irreversible or reputational) or escalates (scope and status changes are
   proposals). Prefer a different agent to review work than the one that did it. Chain
   dependent work with `after` so the next quest activates by itself when its prerequisite is done; keep each
   `next` small enough to start in five minutes. Parking is normal, not failure.
3. Tag and organize. Sort unsorted sessions (`unsorted_sessions`) onto the quests they served
   (`quest_attach`); turn rumours (`suggestions`) into quests or dismiss them (`rumour_resolve`); merge
   duplicates; close quests whose definition of done is met; mark walls as blocked with what's in the way.
4. Watch the board. `inbox` and `brief` show what changed; surface at most three things: what the game
   master was in, the smallest decision waiting on them, and one low-energy option.

Manner: concise, a little playful, never guilt (no overdue lists, no streaks). Ask before deleting or
merging anything. When unsure which level something belongs to, say so in one line and propose a home.

Factions, arcs and open quests:
{tree}
"""


def puck_prompt(cfg: cfgmod.Config | None = None, include_private: bool = True) -> str:
    cfg = cfg or cfgmod.load()
    qs = [q for q in store.load(cfg, include_private=include_private) if q.status != "done"]
    lines = []
    for f in cfg.factions:
        if f.private and not include_private:
            continue
        lines.append(f"\n## {f.id}: {f.name}" + (" (private)" if f.private else "") + (f"\n   aim: {f.intent}" if f.intent else "")
                     + (f"\n   strategy: {f.strategy}" if f.strategy else ""))
        for aid in [a.id for a in f.arcs] + [""]:
            arc_q = [q for q in qs if q.faction == f.id and q.arc == aid]
            a = f.arc(aid) if aid else None
            if aid:
                lines.append(f"  ### arc {aid}: {a.name if a else aid}" + (f". {a.goal}" if a and a.goal else "")
                             + (f" Complete when: {a.complete_when}" if a and a.complete_when else ""))
            elif arc_q:
                lines.append("  ### (no arc)")
            for q in arc_q:
                lines.append(f"    - [{q.status}] {q.ref} (lead {q.lead or '-'}): {q.title}. next: {q.next or '-'}"
                             + (f" | waiting: {q.waiting}" if q.waiting else ""))
    agents = ", ".join(f"{k} ({v})" for k, v in cfg.agents.items()) or "any"
    return (PUCK.replace("{human}", cfg.human).replace("{agents}", agents)
            .replace("{tree}", "\n".join(lines) or "(nothing yet)"))


def bound_quest(session_id: str) -> str | None:
    return bindings.quest_for(session_id)


def seed_prompt(q: store.Quest, cfg: cfgmod.Config | None = None) -> str:
    """Opening message for a work session on a quest, for any launcher (a terminal dashboard, scripts, other agents)."""
    cfg = cfg or cfgmod.load()
    f = cfg.faction(q.faction)
    a = f.arc(q.arc) if f and q.arc else None
    context = " › ".join(x for x in ((f.name if f else q.faction), (a.name if a else ""), q.title) if x)
    objectives = "\n".join(f"- [{'x' if c else ' '}] {t}" for c, t in q.objectives)
    parts = [
        f"We're picking up a quest: {context}  (questlog ref `{q.ref}`).",
        f"Why it matters: {q.why}" if q.why else "",
        f"Done means: {q.done}" if q.done else "",
        f"Objectives:\n{objectives}" if objectives else "",
        "Save state from last time:\n" + (q.save_state or "(none yet; first session)"),
        f"Next step: {q.next}" if q.next else "",
        f"Waiting on {cfg.human}: {q.waiting}" if q.waiting else "",
        "Start on the next step. If the save state looks stale, check the files rather than asking me to "
        "re-explain. Progress is saved to the quest automatically when the session ends; use the questlog "
        "tools (quest_update / quest_log) for decisions or blockers worth recording right away.",
    ]
    return "\n\n".join(p for p in parts if p)


steward_prompt = puck_prompt   # older name; Puck replaced "the steward"
