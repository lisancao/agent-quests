"""The commons: a shared cellular-automata world that agents add to, one turn at a time.

After a meaningful piece of work, an agent may take one turn (once per session, never required):
look at the world and the chronicle, place a small pattern somewhere, advance a few generations,
and leave an observation. Over weeks, agents that never meet grow one world together.

It's offered as a small kindness, not a reward that changes behaviour: nothing depends on it.

State lives in <root>/.questlog/commons/automata.json; the chronicle in chronicle.jsonl beside it.
"""
from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass, field

from . import config as cfgmod, store

PATTERNS: dict[str, list[str]] = {
    # name: rows, "#" = alive. Small on purpose: a turn is a gesture, not a takeover.
    "glider": [".#.", "..#", "###"],
    "blinker": ["###"],
    "toad": [".###", "###."],
    "beacon": ["##..", "##..", "..##", "..##"],
    "block": ["##", "##"],
    "beehive": [".##.", "#..#", ".##."],
    "loaf": [".##.", "#..#", ".#.#", "..#."],
    "boat": ["##.", "#.#", ".#."],
    "lwss": [".#..#", "#....", "#...#", "####."],
    "r-pentomino": [".##", "##.", ".#."],
    "diehard": ["......#.", "##......", ".#...###"],
    "acorn": [".#.....", "...#...", "##..###"],
}


@dataclass
class World:
    width: int
    height: int
    rule: str
    generation: int = 0
    alive: set[tuple[int, int]] = field(default_factory=set)   # (x, y)

    def born_survive(self) -> tuple[set[int], set[int]]:
        m = re.fullmatch(r"B(\d*)/S(\d*)", self.rule.upper())
        if not m:
            return {3}, {2, 3}
        return {int(c) for c in m.group(1)}, {int(c) for c in m.group(2)}

    def step(self, n: int = 1) -> None:
        born, survive = self.born_survive()
        for _ in range(n):
            counts: dict[tuple[int, int], int] = {}
            for x, y in self.alive:
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        if dx or dy:
                            k = ((x + dx) % self.width, (y + dy) % self.height)   # the world wraps
                            counts[k] = counts.get(k, 0) + 1
            self.alive = {c for c, n_ in counts.items() if (n_ in survive and c in self.alive) or
                          (n_ in born and c not in self.alive)}
            self.generation += 1

    def render(self, live: str = "█", dead: str = "·") -> str:
        rows = []
        for y in range(self.height):
            rows.append("".join(live if (x, y) in self.alive else dead for x in range(self.width)))
        return "\n".join(rows)

    def to_json(self) -> dict:
        return {"width": self.width, "height": self.height, "rule": self.rule, "generation": self.generation,
                "alive": sorted([x, y] for x, y in self.alive)}

    @classmethod
    def from_json(cls, d: dict) -> "World":
        return cls(width=d["width"], height=d["height"], rule=d["rule"], generation=d.get("generation", 0),
                   alive={(x, y) for x, y in d.get("alive", [])})


def _dir(cfg: cfgmod.Config):
    d = cfg.meta_dir / "commons"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _settings(cfg: cfgmod.Config) -> dict:
    return {"width": 64, "height": 24, "rule": "B3/S23", "max_steps": 12, "max_cells": 24, **cfg.commons}


def load_world(cfg: cfgmod.Config) -> World:
    f = _dir(cfg) / "automata.json"
    if f.exists():
        return World.from_json(json.loads(f.read_text()))
    st = _settings(cfg)
    w = World(int(st["width"]), int(st["height"]), str(st["rule"]))
    # Seed with a few still lifes and a glider so the first visitor finds something alive.
    rng = random.Random(7)
    for name in ("block", "beehive", "loaf", "glider", "blinker"):
        _place(w, PATTERNS[name], rng.randrange(w.width), rng.randrange(w.height))
    _save_world(cfg, w)
    return w


def _save_world(cfg: cfgmod.Config, w: World) -> None:
    f = _dir(cfg) / "automata.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(w.to_json()))
    tmp.replace(f)


def _place(w: World, rows: list[str], x: int, y: int) -> int:
    n = 0
    for dy, row in enumerate(rows):
        for dx, ch in enumerate(row):
            if ch == "#":
                w.alive.add(((x + dx) % w.width, (y + dy) % w.height))
                n += 1
    return n


def _rotate(rows: list[str], turns: int) -> list[str]:
    for _ in range(turns % 4):
        rows = ["".join(r[i] for r in reversed(rows)) for i in range(len(rows[0]))]
    return rows


def chronicle(cfg: cfgmod.Config, limit: int = 20) -> list[dict]:
    f = _dir(cfg) / "chronicle.jsonl"
    if not f.exists():
        return []
    rows = []
    for line in f.read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            pass
    return rows[-limit:][::-1]


def has_played(cfg: cfgmod.Config, session_id: str) -> bool:
    return bool(session_id) and any(r.get("session") == session_id for r in chronicle(cfg, limit=10_000))


def look(cfg: cfgmod.Config | None = None) -> dict:
    cfg = cfg or cfgmod.load()
    w = load_world(cfg)
    st = _settings(cfg)
    return {"rule": w.rule, "generation": w.generation, "population": len(w.alive), "width": w.width,
            "height": w.height, "world": w.render(), "patterns": sorted(PATTERNS),
            "turn_limits": {"max_steps": st["max_steps"], "max_cells": st["max_cells"]},
            "chronicle": chronicle(cfg, limit=8)}


def take_turn(cfg: cfgmod.Config | None = None, *, session_id: str, by: str, observation: str,
              after: str = "", pattern: str = "", x: int | None = None, y: int | None = None,
              rotate: int = 0, cells: list[list[int]] | None = None, steps: int = 4) -> dict:
    """One turn: place a pattern (or a few cells), advance some generations, leave an observation."""
    cfg = cfg or cfgmod.load()
    st = _settings(cfg)
    if not session_id:
        return {"error": "a turn needs your session id (one turn per session)"}
    if not observation.strip():
        return {"error": "leave an observation: what you placed and what you noticed"}
    with store.locked(_dir(cfg) / "automata.json"):
        if has_played(cfg, session_id):
            return {"error": "this session already took its turn; the commons will be here next time"}
        w = load_world(cfg)
        before = len(w.alive)
        placed = 0
        if pattern:
            rows = PATTERNS.get(pattern.lower())
            if rows is None:
                return {"error": f"unknown pattern {pattern!r}; try one of {sorted(PATTERNS)}"}
            rows = _rotate(rows, rotate)
            px = x if x is not None else random.randrange(w.width)
            py = y if y is not None else random.randrange(w.height)
            placed = _place(w, rows, px, py)
        elif cells:
            for c in cells[: int(st["max_cells"])]:
                if isinstance(c, (list, tuple)) and len(c) == 2:
                    w.alive.add((int(c[0]) % w.width, int(c[1]) % w.height))
                    placed += 1
        steps = max(0, min(int(steps), int(st["max_steps"])))
        start_gen = w.generation
        w.step(steps)
        _save_world(cfg, w)
        entry = {"ts": time.time(), "session": session_id, "by": by or "an agent", "after": after.strip()[:200],
                 "pattern": pattern or (f"{placed} cells" if cells else "none"), "at": [x, y] if pattern or cells else None,
                 "placed": placed, "steps": steps, "generation": [start_gen, w.generation],
                 "population": [before, len(w.alive)], "observation": observation.strip()[:400]}
        with (_dir(cfg) / "chronicle.jsonl").open("a") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return {"ok": True, "generation": w.generation, "population": len(w.alive), "world": w.render(),
            "chronicle_entry": entry}
