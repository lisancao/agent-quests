"""The RPG layer: XP, levels, faction reputation, achievements and loot.

Everything is derived from the ledger and quest files, so nothing can go stale or be lost.
Nothing decays: no streaks, no overdue, no penalties. Progress only accumulates.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from . import config as cfgmod, ledger, store


@dataclass
class Rep:
    faction: str
    name: str
    xp: int
    tier: str
    next_tier: str
    into_tier: int      # xp earned within the current tier
    tier_span: int      # xp between this tier and the next (0 at max)


@dataclass
class Sheet:
    xp: int
    level: int
    into_level: int
    level_span: int
    reputation: list[Rep]
    achievements: list[dict]
    inventory: list[dict]
    deeds_total: int
    quests_done: int
    arcs_done: int
    sessions: int
    by_source: dict[str, int] = field(default_factory=dict)


def level_for(xp: int, divisor: int) -> tuple[int, int, int]:
    """(level, xp into level, xp span of level). Gentle curve: level n starts at divisor*(n-1)^2."""
    level = int(math.floor(math.sqrt(max(xp, 0) / divisor))) + 1
    start = divisor * (level - 1) ** 2
    nxt = divisor * level ** 2
    return level, xp - start, nxt - start


def _tier(xp: int, tiers: list[tuple[str, int]]) -> tuple[str, str, int, int]:
    tiers = sorted(tiers, key=lambda t: t[1])
    cur = tiers[0]
    nxt = None
    for i, t in enumerate(tiers):
        if xp >= t[1]:
            cur = t
            nxt = tiers[i + 1] if i + 1 < len(tiers) else None
    if nxt is None:
        return cur[0], "", 0, 0
    return cur[0], nxt[0], xp - cur[1], nxt[1] - cur[1]


def _arc_complete(cfg: cfgmod.Config, f: cfgmod.Faction, a: cfgmod.Arc, qs: list[store.Quest]) -> bool:
    aq = [q for q in qs if q.faction == f.id and q.arc == a.id]
    return bool(aq) and all(q.status == "done" for q in aq)


GENERIC_ACHIEVEMENTS = [
    # (id, name, description, test(stats) -> bool)
    ("first-deed", "First Steps", "Your first recorded deed.", lambda s: s["deeds"] >= 1),
    ("ten-deeds", "Making Moves", "Ten deeds recorded.", lambda s: s["deeds"] >= 10),
    ("fifty-deeds", "Prolific", "Fifty deeds recorded.", lambda s: s["deeds"] >= 50),
    ("first-quest", "Quest Complete", "Finished your first quest.", lambda s: s["quests_done"] >= 1),
    ("five-quests", "Adventurer", "Five quests finished.", lambda s: s["quests_done"] >= 5),
    ("first-arc", "Arc Closed", "Completed a whole arc.", lambda s: s["arcs_done"] >= 1),
    ("unblocked", "Through the Wall", "Got a blocked quest moving again.", lambda s: s["unblocked"] >= 1),
    ("synergy", "Synergy", "Sessions advanced two different factions in the same day.", lambda s: s["synergy"]),
    ("party", "Full Party", "Five sessions worked on the same arc.", lambda s: s["max_arc_sessions"] >= 5),
    ("polymath", "Polymath", "Earned reputation with three factions.", lambda s: s["factions_with_xp"] >= 3),
    ("respected", "Respected", "Reached Respected with a faction.", lambda s: s["max_tier_index"] >= 2),
    ("legend", "Legend", "Reached the top tier with a faction.", lambda s: s["max_tier_index"] >= 4),
]


def sheet(cfg: cfgmod.Config | None = None, include_private: bool = True) -> Sheet:
    cfg = cfg or cfgmod.load()
    qs = store.load(cfg, include_private=include_private)
    deeds = ledger.deeds(cfg)
    sessions = ledger.sessions(cfg)
    fac_xp: dict[str, int] = defaultdict(int)
    by_source: Counter[str] = Counter()

    for d in deeds:
        fac_xp[d.get("faction") or ""] += int(d.get("xp", 0))
        by_source["deeds"] += int(d.get("xp", 0))
    for q in qs:
        obj_xp = sum(c for c, _ in q.objectives) * cfg.xp["objective"]
        fac_xp[q.faction] += obj_xp
        by_source["objectives"] += obj_xp
        if q.status == "done":
            qxp = cfg.xp.get(f"quest_{q.size or 'medium'}", cfg.xp["quest_medium"])
            fac_xp[q.faction] += qxp
            by_source["quests"] += qxp
    arcs_done = 0
    for f in cfg.factions:
        for a in f.arcs:
            if _arc_complete(cfg, f, a, qs):
                arcs_done += 1
                fac_xp[f.id] += cfg.xp["arc"]
                by_source["arcs"] += cfg.xp["arc"]

    total = sum(fac_xp.values())
    level, into, span = level_for(total, cfg.level_divisor)
    tier_names = [t[0] for t in sorted(cfg.tiers, key=lambda t: t[1])]
    reps = []
    for f in cfg.factions:
        if f.private and not include_private:
            continue
        t, nt, into_t, span_t = _tier(fac_xp.get(f.id, 0), cfg.tiers)
        reps.append(Rep(f.id, f.name, fac_xp.get(f.id, 0), t, nt, into_t, span_t))

    # Stats for achievements.
    days_factions: dict[str, set] = defaultdict(set)
    for d in deeds:
        if d.get("faction"):
            from datetime import datetime
            days_factions[datetime.fromtimestamp(d.get("ts", 0)).date().isoformat()].add(d["faction"])
    arc_sessions = Counter(f"{r.get('faction')}/{r.get('arc')}" for r in sessions.values() if r.get("arc"))
    unblocked = sum(1 for q in qs for line in q.log if "unblock" in line.lower() or "cleared" in line.lower())
    stats = {
        "deeds": len(deeds), "quests_done": sum(q.status == "done" for q in qs), "arcs_done": arcs_done,
        "unblocked": unblocked, "synergy": any(len(v) >= 2 for v in days_factions.values()),
        "max_arc_sessions": max(arc_sessions.values(), default=0),
        "factions_with_xp": sum(1 for k, v in fac_xp.items() if k and v > 0),
        "max_tier_index": max((tier_names.index(r.tier) for r in reps), default=0),
    }
    earned = [{"id": i, "name": n, "description": d} for i, n, d, test in GENERIC_ACHIEVEMENTS if test(stats)]
    # User-defined achievements: {name, description, faction?, deeds?, quests_done?, xp?}
    for a in cfg.achievements:
        fid = a.get("faction")
        fx = fac_xp.get(fid, 0) if fid else total
        fdeeds = sum(1 for d in deeds if not fid or d.get("faction") == fid)
        fq = sum(1 for q in qs if q.status == "done" and (not fid or q.faction == fid))
        if fx >= int(a.get("xp", 0)) and fdeeds >= int(a.get("deeds", 0)) and fq >= int(a.get("quests_done", 0)):
            earned.append({"id": a["name"].lower().replace(" ", "-"), "name": a["name"],
                           "description": a.get("description", "")})
    inventory = [{"reward": q.reward, "quest": q.title, "ref": q.ref} for q in qs if q.status == "done" and q.reward]
    return Sheet(xp=total, level=level, into_level=into, level_span=span, reputation=reps, achievements=earned,
                 inventory=inventory, deeds_total=len(deeds), quests_done=stats["quests_done"], arcs_done=arcs_done,
                 sessions=len(sessions), by_source=dict(by_source))


def arc_progress(cfg: cfgmod.Config, faction: str, arc: str) -> tuple[int, int]:
    """(done, total) quests in an arc."""
    qs = [q for q in store.load(cfg, faction=faction, arc=arc)]
    return sum(q.status == "done" for q in qs), len(qs)
