"""questlog.toml: the world the user defines. Everything has a default, so no config is required.

Three levels:
  faction  a big aspiration or allegiance      "Become an overlord"
  arc      an initiative that serves a faction  "Build the volcano lair"
  quest    a concrete deliverable inside an arc "Install the shark tank"

Factions and arcs carry intent and strategy so agents can orient to them, plus `match`
rules (folders, keywords) that tell questlog which sessions serve them.

    root = "~/quests"                # markdown directory (one folder per faction)
    human = "Sam"                    # who "waiting on" means

    [agents]                         # who can take point on a quest, and what they're good at
    claude = "hands-on coding and writing"

    [[factions]]
    id = "overlord"
    name = "Become an overlord"
    intent = "Rule the world, eventually, with style"
    strategy = "Start with one island; never monologue early"
    success_looks_like = "Heroes take me seriously"
    lead = "claude"
    private = false
    match = { paths = ["~/lair"], keywords = ["lair", "doomsday"] }
    arcs = [
      { id = "lair", name = "Build the volcano lair", goal = "A lair worthy of a showdown", complete_when = "Shark tank and a self-destruct button", match = { paths = ["~/lair/blueprints"] } },
    ]
    # quests (concrete deliverables) live in <root>/<faction>/<arc>/<quest>.md

    [briefs.quest]                   # questions asked when a quest is created (see briefs.py)
    required = ["What does done look like, observably?", "Why does this matter for its arc?"]

    [rewards]                        # see rewards.py
    level_divisor = 50
    tiers = [["Unknown", 0], ["Recognized", 100], ["Respected", 400], ["Renowned", 1200], ["Legend", 3000]]

    [hub]
    launch = "my-launcher start {ref}"   # what Enter on a quest runs

    [scribe]
    command = ["claude", "-p", "--model", "haiku", "--no-session-persistence"]
    throttle_minutes = 20
    every_session = true             # read every session, not only quest-bound ones
"""
from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

STATUS_KEYS = ("active", "blocked", "waiting", "parked", "done")
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "questlog"


def config_path() -> Path:
    if os.environ.get("QUESTLOG_CONFIG"):
        return Path(os.path.expanduser(os.environ["QUESTLOG_CONFIG"]))
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "questlog" / "questlog.toml"


@dataclass
class Match:
    """Signals that a session serves this faction/arc: folders it works in, words in what it says."""
    paths: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)

    @classmethod
    def from_raw(cls, raw) -> "Match":
        if not isinstance(raw, dict):
            return cls()
        paths = [str(Path(os.path.expanduser(p)).resolve()) for p in raw.get("paths") or [] if isinstance(p, str)]
        kws = [k.strip().lower() for k in raw.get("keywords") or [] if isinstance(k, str) and k.strip()]
        return cls(paths=paths, keywords=kws)

    def merge(self, other: "Match") -> None:
        self.paths += [p for p in other.paths if p not in self.paths]
        self.keywords += [k for k in other.keywords if k not in self.keywords]

    def __bool__(self) -> bool:
        return bool(self.paths or self.keywords)


@dataclass
class Arc:
    id: str
    name: str = ""
    goal: str = ""            # what this initiative achieves for its faction
    strategy: str = ""
    complete_when: str = ""   # the arc's definition of done
    match: Match = field(default_factory=Match)


@dataclass
class Faction:
    id: str
    name: str = ""
    intent: str = ""              # the big aspiration, in the user's words
    strategy: str = ""            # how / for whom
    principles: str = ""
    success_looks_like: str = ""  # direction more than finish line; factions are often ongoing
    lead: str = ""
    authority: str = ""           # default for its quests: autonomous | proposes | escalates
    private: bool = False
    arcs: list[Arc] = field(default_factory=list)
    match: Match = field(default_factory=Match)

    @property
    def charter(self) -> str:  # v1 name, kept for callers
        return self.intent

    def arc(self, aid: str) -> Arc | None:
        return next((a for a in self.arcs if a.id == aid), None)


DEFAULT_BRIEFS = {
    "faction": {
        "required": [
            ("intent", "What do you want, in your own words?"),
            ("strategy", "How will you get there, and for whom?"),
        ],
        "optional": [
            ("success_looks_like", "What would success look like, even if it's never finished?"),
            ("principles", "Anything you won't compromise on along the way?"),
        ],
    },
    "arc": {
        "required": [
            ("goal", "What are you trying to do, in plain words, and for whom?"),
            ("complete_when", "How will you know this arc is complete?"),
        ],
        "optional": [
            ("strategy", "How will you go about it? What's new or different about your approach?"),
            ("impact", "Who cares, and what changes for them if it succeeds?"),
            ("risks", "What could stop it, or make it not worth doing?"),
            ("midpoint", "What would tell you, halfway, that it's on track?"),
        ],
    },
    "quest": {
        "required": [
            ("done", "What does done look like, observably?"),
            ("why", "Why does this matter for its arc?"),
        ],
        "optional": [
            ("approach", "How will you do it, and what's the first step?"),
            ("risks", "What might block it?"),
            ("size", "Is it small, medium or large?"),
        ],
    },
}

DEFAULT_TIERS = [("Unknown", 0), ("Recognized", 100), ("Respected", 400), ("Renowned", 1200), ("Legend", 3000)]
DEFAULT_XP = {"deed_small": 10, "deed_medium": 25, "deed_large": 50, "objective": 20,
              "quest_small": 100, "quest_medium": 200, "quest_large": 400, "arc": 500}


@dataclass
class Config:
    root: Path
    human: str = "you"
    statuses: dict[str, str] = field(default_factory=lambda: {k: k for k in STATUS_KEYS})
    agents: dict[str, str] = field(default_factory=dict)
    factions: list[Faction] = field(default_factory=list)
    briefs: dict = field(default_factory=lambda: {k: dict(v) for k, v in DEFAULT_BRIEFS.items()})
    xp: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_XP))
    level_divisor: int = 50
    tiers: list[tuple[str, int]] = field(default_factory=lambda: list(DEFAULT_TIERS))
    achievements: list[dict] = field(default_factory=list)
    hub_launch: str = ""
    hub_theme: dict[str, str] = field(default_factory=dict)
    commons: dict = field(default_factory=dict)
    journal_theme: str = "codex"   # [journal] theme: codex | parchment
    journal_voice: bool = False    # [journal] voice: scribe writes log entries and deeds as in-world prose
    nudge: bool = True             # [nudge] enabled: end-of-session prompt to update the quest log
    puck_model: str = "sonnet"     # [puck] model: the model Puck runs on   # [commons]: width, height, rule, max_steps, max_cells, enabled
    scribe_command: list[str] = field(default_factory=lambda: [
        "claude", "-p", "--model", "haiku", "--no-session-persistence"])
    scribe_throttle_minutes: int = 20
    scribe_every_session: bool = True
    path: Path | None = None

    def faction(self, fid: str) -> Faction | None:
        return next((f for f in self.factions if f.id == fid), None)

    def label(self, status_key: str) -> str:
        return self.statuses.get(status_key, status_key)

    @property
    def meta_dir(self) -> Path:
        """Ledger, suggestions: inside the data root, hidden (dot-folder)."""
        return self.root / ".questlog"


# --- FACTION.md / ARC.md frontmatter ----------------------------------------------

def read_note(path: Path) -> tuple[dict, str]:
    """(frontmatter, body) of a FACTION.md / ARC.md. Frontmatter is optional."""
    if not path.exists():
        return {}, ""
    text = path.read_text()
    m = re.match(r"---\n(.*?)\n---\n?(.*)", text, re.S)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = (x.strip() for x in line.split(":", 1))
            meta[k] = v
    return meta, m.group(2)


def _split_list(v: str) -> list[str]:
    return [x.strip() for x in v.split(",") if x.strip()]


def _apply_note(obj, meta: dict, body: str) -> None:
    """Fill empty fields of a Faction/Arc from its note (toml wins when both set)."""
    for k in ("name", "intent", "strategy", "principles", "success_looks_like", "goal", "complete_when", "lead", "authority"):
        if k in meta and hasattr(obj, k) and (not getattr(obj, k) or (k == "name" and getattr(obj, k) == obj.id)):
            setattr(obj, k, meta[k])
    if "private" in meta and hasattr(obj, "private") and not obj.private:
        obj.private = meta["private"].lower() in ("true", "yes", "1")
    obj.match.merge(Match.from_raw({"paths": _split_list(meta.get("match_paths", "")),
                                    "keywords": _split_list(meta.get("match_keywords", ""))}))
    # Plain notes: a "# Name" heading and a first paragraph as the goal/intent.
    lines = [ln.strip() for ln in body.splitlines()]
    heads = [ln[2:].strip() for ln in lines if ln.startswith("# ")]
    paras = [ln for ln in lines if ln and not ln.startswith("#") and not ln.startswith("- ")]
    if heads and (not obj.name or obj.name in (obj.id, obj.id.replace("-", " "))):
        obj.name = heads[0]
    if isinstance(obj, Arc) and not obj.goal and paras:
        obj.goal = paras[0]
    if isinstance(obj, Faction) and not obj.intent and paras:
        obj.intent = paras[0]


def load(path: Path | None = None) -> Config:
    path = path or config_path()
    raw: dict = {}
    if path.exists():
        with path.open("rb") as f:
            raw = tomllib.load(f)
    root = Path(os.path.expanduser(raw.get("root", "~/quests"))).resolve()
    cfg = Config(root=root, path=path if path.exists() else None)
    cfg.human = raw.get("human", cfg.human)
    for k, v in (raw.get("statuses") or {}).items():
        if k in STATUS_KEYS and isinstance(v, str):
            cfg.statuses[k] = v
    cfg.agents = {str(k): str(v) for k, v in (raw.get("agents") or {}).items()}

    for f in raw.get("factions") or []:
        if not (isinstance(f, dict) and f.get("id")):
            continue
        fac = Faction(id=str(f["id"]), name=f.get("name", f["id"]),
                      intent=f.get("intent") or f.get("charter", ""), strategy=f.get("strategy", ""),
                      principles=f.get("principles", ""), success_looks_like=f.get("success_looks_like", ""),
                      lead=f.get("lead", ""), authority=f.get("authority", ""), private=bool(f.get("private", False)),
                      match=Match.from_raw(f.get("match")))
        for a in f.get("arcs") or []:
            if isinstance(a, dict) and a.get("id"):
                fac.arcs.append(Arc(id=str(a["id"]), name=a.get("name", a["id"]), goal=a.get("goal", ""),
                                    strategy=a.get("strategy", ""), complete_when=a.get("complete_when", ""),
                                    match=Match.from_raw(a.get("match"))))
        cfg.factions.append(fac)

    # Folders on disk count as factions / arcs even if the config doesn't list them; notes fill gaps.
    if root.is_dir():
        for d in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
            fac = cfg.faction(d.name)
            if not fac:
                fac = Faction(id=d.name, name=d.name)
                cfg.factions.append(fac)
            _apply_note(fac, *read_note(d / "FACTION.md"))
            for ad in sorted(p for p in d.iterdir() if p.is_dir() and not p.name.startswith(".")):
                arc = fac.arc(ad.name)
                if not arc:
                    arc = Arc(id=ad.name, name=ad.name.replace("-", " "))
                    fac.arcs.append(arc)
                _apply_note(arc, *read_note(ad / "ARC.md"))
    if not cfg.factions:
        cfg.factions.append(Faction(id="general", name="General", intent="Everything, until you define factions"))

    for level in ("faction", "arc", "quest"):
        b = (raw.get("briefs") or {}).get(level) or {}
        for kind in ("required", "optional"):
            if isinstance(b.get(kind), list):
                defaults = DEFAULT_BRIEFS[level][kind]
                cfg.briefs[level][kind] = [
                    (defaults[i][0] if i < len(defaults) else f"{kind}{i + 1}", q)
                    for i, q in enumerate(b[kind]) if isinstance(q, str)]

    rw = raw.get("rewards") or {}
    cfg.xp.update({k: int(v) for k, v in (rw.get("xp") or {}).items() if k in DEFAULT_XP})
    cfg.level_divisor = int(rw.get("level_divisor", cfg.level_divisor))
    if isinstance(rw.get("tiers"), list):
        cfg.tiers = [(str(t[0]), int(t[1])) for t in rw["tiers"] if isinstance(t, list) and len(t) == 2]
    cfg.achievements = [a for a in rw.get("achievements") or [] if isinstance(a, dict) and a.get("name")]

    hub = raw.get("hub") or {}
    cfg.hub_launch = hub.get("launch", "")
    cfg.hub_theme = {k: str(v) for k, v in (hub.get("theme") or {}).items()}

    cfg.commons = {k: v for k, v in (raw.get("commons") or {}).items()
                   if k in ("width", "height", "rule", "max_steps", "max_cells", "enabled")}

    cfg.nudge = bool((raw.get("nudge") or {}).get("enabled", cfg.nudge))
    cfg.puck_model = str((raw.get("puck") or {}).get("model", cfg.puck_model))
    jr = raw.get("journal") or {}
    cfg.journal_theme = str(jr.get("theme", cfg.journal_theme))
    cfg.journal_voice = bool(jr.get("voice", cfg.journal_voice))

    sc = raw.get("scribe") or {}
    if isinstance(sc.get("command"), list):
        cfg.scribe_command = [str(x) for x in sc["command"]]
    cfg.scribe_throttle_minutes = int(sc.get("throttle_minutes", cfg.scribe_throttle_minutes))
    cfg.scribe_every_session = bool(sc.get("every_session", cfg.scribe_every_session))
    return cfg


SAMPLE = '''# questlog.toml: define your world. Every key is optional.
# faction = a big aspiration; arc = an initiative serving it; quest = a concrete deliverable
root = "{root}"
human = "{human}"

[agents]
claude = "hands-on coding and writing"

[[factions]]
id = "general"
name = "General"
intent = "What I'm working toward"
strategy = "How I'll get there, and for whom"
arcs = [{ id = "first-arc", name = "First arc", goal = "What this initiative achieves", complete_when = "How I'll know it's done" }]
'''
