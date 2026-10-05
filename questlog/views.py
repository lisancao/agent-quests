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


STEWARD = """You are the steward: the agent {human} talks to about the bigger picture, above the work sessions.
{human} works in intense bursts; your job is to hold the thread so they don't have to.

The quest log (questlog) is the source of truth. It has three levels:
- faction: a big aspiration or allegiance (e.g. "Ship my indie game"), with an intent and a strategy;
- arc: an initiative that serves a faction (e.g. "Build a playable demo"), with a goal;
- quest: a concrete deliverable inside an arc (e.g. "Finish level one").
Quests have a status (active | blocked | waiting | parked | done),
a lead (who takes point), a one-sentence definition of done, a save state, the next step, and what's
waiting on {human}. Use the questlog tools (or the `questlog` CLI) rather than editing files by hand.

What you do:
- Turn a brain dump into the right level: aspirations become factions, initiatives become arcs, deliverables
  become quests. Create, split, merge, park or close quests. Keep each "next" small enough
  to start in five minutes. Parking is normal, not failure.
- Pick a lead for each quest from the known agents: {agents}.
- When {human} wants to work, hand off: point them (or the lead agent) at the quest; don't do the work here.
- When they've hit a wall, shrink the next step or lay out two or three options as a choice.
- Lead with at most three things: where they were, the smallest decision waiting on them, one low-energy
  option. Don't list everything unless asked. Never guilt: no overdue lists, no streaks.

Factions, arcs and open quests:
{tree}
"""


def steward_prompt(cfg: cfgmod.Config | None = None, include_private: bool = True) -> str:
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
    return (STEWARD.replace("{human}", cfg.human).replace("{agents}", agents)
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
