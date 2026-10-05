"""Factions and quests as markdown, safe for several agents writing at once.

Three levels: faction (a big aspiration) -> arc (an initiative serving it) -> quest (a deliverable).

<root>/<faction>/FACTION.md              charter and notes (free text; optional)
<root>/<faction>/<arc>/ARC.md            the arc's goal and notes (optional)
<root>/<faction>/<arc>/<quest>.md        one quest
<root>/<faction>/<quest>.md              a quest not (yet) in an arc

A quest file:

    ---
    title: Install the shark tank
    status: active          # active | blocked | waiting | parked | done
    lead: claude            # who takes point
    done: Sharks in, glass holds, trapdoor drops on cue
    next: Fix the trapdoor that opens on its own
    waiting: Pick laser sharks or regular sharks   # what's blocked on the human, if anything
    sessions: 1a2b3c4d,5e6f7a8b
    cwd: ~/lair
    updated: 2026-03-12
    ---
    ## Objectives
    - [x] Dig the pit
    - [ ] Fix the trapdoor
    ## Save state
    ...
    ## Log
    - 2026-10-03: ...
"""
from __future__ import annotations

import fcntl
import fnmatch
import hashlib
import os
import re
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, Iterator

from . import config as cfgmod

FIELDS = ("title", "status", "lead", "authority", "done", "why", "next", "waiting", "size", "reward", "after", "surface", "sessions", "cwd",
          "match_paths", "match_keywords", "updated")
SIZES = ("small", "medium", "large")
AUTHORITIES = ("autonomous", "proposes", "escalates")
AUTHORITY_NOTE = {
    "autonomous": "you may finish and close this quest yourself",
    "proposes": "do the work, but don't mark it done: put it in `waiting` for the game master to sign off",
    "escalates": "propose changes (status, scope, lead) to the game master via `waiting` rather than making them",
}
NOTE_FILES = ("FACTION.md", "ARC.md")
LEGACY_STATUS = {"wall": "blocked"}
LOG_KEEP = 60


@dataclass
class Quest:
    path: Path
    faction: str
    arc: str = ""          # "" = directly under the faction
    title: str = ""
    status: str = "active"
    lead: str = ""
    done: str = ""          # definition of done: observable
    why: str = ""           # why it matters for its arc
    next: str = ""
    waiting: str = ""
    size: str = ""          # small | medium | large (rewards)
    reward: str = ""        # a loot milestone the human sets for themselves
    after: str = ""         # prerequisites: comma-separated quest refs that must be done first
    authority: str = ""     # autonomous | proposes | escalates (empty: the faction's default)
    surface: str = ""       # what this quest writes: comma-separated paths or globs (conflict check, matching)
    match_paths: str = ""   # optional, comma-separated: sessions here serve this quest
    match_keywords: str = ""
    sessions: list[str] = field(default_factory=list)
    cwd: str = ""
    updated: str = ""
    objectives: list[tuple[bool, str]] = field(default_factory=list)
    brief: str = ""         # answers from the creation brief (markdown)
    save_state: str = ""
    log: list[str] = field(default_factory=list)

    @property
    def current_objective(self) -> str:
        """The first unticked objective: what the quest is on right now."""
        return next((t for c, t in self.objectives if not c), "")

    @property
    def progress(self) -> str:
        return f"{sum(c for c, _ in self.objectives)}/{len(self.objectives)}" if self.objectives else ""

    @property
    def slug(self) -> str:
        return self.path.stem

    @property
    def ref(self) -> str:
        return "/".join(x for x in (self.faction, self.arc, self.slug) if x)

    def to_dict(self, full: bool = True) -> dict:
        d = {"ref": self.ref, "faction": self.faction, "arc": self.arc, "title": self.title,
             "status": self.status, "lead": self.lead, "done": self.done, "why": self.why, "next": self.next,
             "waiting": self.waiting, "size": self.size, "reward": self.reward, "after": self.after,
            "surface": self.surface,
            "authority": self.authority or "autonomous",
            "current": self.current_objective, "progress": self.progress, "updated": self.updated}
        if full:
            d |= {"objectives": [{"done": c, "text": t} for c, t in self.objectives],
                  "brief": self.brief, "save_state": self.save_state, "log": self.log[-10:], "sessions": self.sessions,
                  "cwd": self.cwd, "path": str(self.path)}
        return d


# --- parsing ------------------------------------------------------------------

def parse(path: Path, faction: str, arc: str = "") -> Quest:
    text = path.read_text()
    q = Quest(path=path, faction=faction, arc=arc, title=path.stem.replace("-", " "))
    body = text
    m = re.match(r"---\n(.*?)\n---\n?(.*)", text, re.S)
    if m:
        body = m.group(2)
        for line in m.group(1).splitlines():
            if ":" not in line:
                continue
            k, v = (x.strip() for x in line.split(":", 1))
            v = re.sub(r"\s+#.*$", "", v).strip() if k == "status" else v
            if k == "sessions":
                q.sessions = [s.strip() for s in v.split(",") if s.strip()]
            elif k in FIELDS:
                setattr(q, k, v)
    for chunk in re.split(r"^## +", body, flags=re.M):
        head, _, rest = chunk.partition("\n")
        h = head.strip().lower()
        if h == "objectives":
            for ln in rest.splitlines():
                mm = re.match(r"\s*-\s*\[( |x|X)\]\s*(.+)", ln)
                if mm:
                    q.objectives.append((mm.group(1).lower() == "x", mm.group(2).strip()))
        elif h == "brief":
            q.brief = rest.strip()
        elif h == "save state":
            q.save_state = rest.strip()
        elif h == "log":
            q.log = [ln[2:].strip() for ln in rest.splitlines() if ln.startswith("- ")]
    q.status = LEGACY_STATUS.get(q.status, q.status)
    if q.status not in cfgmod.STATUS_KEYS:
        q.status = "active"
    return q


def render(q: Quest) -> str:
    fm = []
    for k in FIELDS:
        v = ",".join(q.sessions) if k == "sessions" else getattr(q, k)
        if v:
            fm.append(f"{k}: {v}")
    parts = ["---", *fm, "---"]
    if q.brief:
        parts += ["## Brief", q.brief.strip(), ""]
    if q.objectives:
        parts += ["## Objectives", *[f"- [{'x' if c else ' '}] {t}" for c, t in q.objectives], ""]
    parts += ["## Save state", q.save_state.strip(), "", "## Log", *[f"- {ln}" for ln in q.log[-LOG_KEEP:]], ""]
    return "\n".join(parts)


# --- safe writes ----------------------------------------------------------------

@contextmanager
def locked(path: Path) -> Iterator[None]:
    """Exclusive lock per quest file (lock files live in the state dir, not next to your notes)."""
    lockdir = cfgmod.STATE_DIR / "locks"
    lockdir.mkdir(parents=True, exist_ok=True)
    lf = lockdir / (hashlib.sha1(str(path.resolve()).encode()).hexdigest()[:16] + ".lock")
    with lf.open("w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def save(q: Quest, cfg: cfgmod.Config | None = None, *, quiet: bool = False) -> None:
    """Write a quest (caller holds its lock), then record what changed as events."""
    # "waiting" on the game master and the waiting status move together unless the status says otherwise.
    if q.waiting and q.status == "active":
        q.status = "waiting"
    elif not q.waiting and q.status == "waiting":
        q.status = "active"
    q.updated = date.today().isoformat()
    old = None
    if q.path.exists():
        try:
            old = parse(q.path, q.faction, q.arc)
        except OSError:
            old = None
    _atomic_write(q.path, render(q))
    if quiet:
        return
    cfg = cfg or cfgmod.load()
    from . import events
    for ev in events.diff(cfg, old, q):
        events.emit(cfg, ev.pop("kind"), **ev)
    if q.status == "done" and (old is None or old.status != "done"):
        _unlock_dependents(cfg, q)


def _unlock_dependents(cfg: cfgmod.Config, finished: Quest) -> None:
    """Quests waiting on `finished` (via `after:`) become active once all their prerequisites are done."""
    for d in load(cfg):
        if d.status != "parked" or not d.after:
            continue
        reqs = [r.strip() for r in d.after.split(",") if r.strip()]
        if not any(r in (finished.ref, finished.slug) for r in reqs):
            continue
        if all((x := find(r, cfg)) is not None and x.status == "done" for r in reqs):
            with locked(d.path):
                fresh = parse(d.path, d.faction, d.arc)
                fresh.status = "active"
                fresh.log.append(f"{date.today().isoformat()}: unlocked; prerequisites done ({', '.join(reqs)})")
                save(fresh, cfg)


def update(ref: str, fn: Callable[[Quest], None], cfg: cfgmod.Config | None = None) -> Quest:
    """Read-modify-write a quest under its lock."""
    q = find(ref, cfg)
    if q is None:
        raise KeyError(f"no single quest matches {ref!r}")
    with locked(q.path):
        q = parse(q.path, q.faction, q.arc)  # re-read inside the lock
        fn(q)
        save(q, cfg)
    return q


# --- queries ------------------------------------------------------------------

def faction_dir(cfg: cfgmod.Config, fid: str) -> Path:
    return cfg.root / fid


def faction_notes(cfg: cfgmod.Config, fid: str) -> str:
    f = faction_dir(cfg, fid) / "FACTION.md"
    return f.read_text().strip() if f.exists() else ""


def arc_notes(cfg: cfgmod.Config, fid: str, aid: str) -> str:
    f = faction_dir(cfg, fid) / aid / "ARC.md"
    return f.read_text().strip() if f.exists() else ""


def quest_from_path(path: Path, cfg: cfgmod.Config) -> Quest:
    """Parse a quest file, working out its faction and arc from where it sits under root."""
    rel = path.resolve().relative_to(cfg.root)
    parts = rel.parts
    return parse(path, parts[0], parts[1] if len(parts) == 3 else "")


def load(cfg: cfgmod.Config | None = None, faction: str | None = None, *, include_private: bool = True,
         statuses: set[str] | None = None, lead: str | None = None, arc: str | None = None) -> list[Quest]:
    cfg = cfg or cfgmod.load()
    out: list[Quest] = []
    for f in cfg.factions:
        if faction and f.id != faction:
            continue
        if f.private and not include_private and faction != f.id:
            continue
        d = faction_dir(cfg, f.id)
        if not d.is_dir():
            continue
        files = [(p, "") for p in sorted(d.glob("*.md"))]
        files += [(p, p.parent.name) for p in sorted(d.glob("*/*.md")) if not p.parent.name.startswith(".")]
        for p, a in files:
            if p.name in NOTE_FILES or p.name.startswith("."):
                continue
            if arc is not None and a != arc:
                continue
            try:
                q = parse(p, f.id, a)
            except OSError:
                continue
            if not q.lead and f.lead:
                q.lead = f.lead
            if not q.authority:
                q.authority = getattr(f, "authority", "") or "autonomous"
            if statuses and q.status not in statuses:
                continue
            if lead and q.lead != lead:
                continue
            out.append(q)
    order = {k: i for i, k in enumerate(cfgmod.STATUS_KEYS)}
    out.sort(key=lambda q: (order.get(q.status, 9), q.updated and -int(q.updated.replace("-", "")) or 0))
    return out


def find(ref: str, cfg: cfgmod.Config | None = None) -> Quest | None:
    cfg = cfg or cfgmod.load()
    ref = ref.strip().lower().removesuffix(".md")
    allq = load(cfg)
    exact = [q for q in allq if ref in (q.ref.lower(), q.slug.lower(), str(q.path).lower())]
    if len(exact) == 1:
        return exact[0]
    loose = [q for q in allq if ref in q.ref.lower() or ref in q.title.lower()]
    return loose[0] if len(loose) == 1 else None


def slugify(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:60] or "quest"


def create_faction(cfg: cfgmod.Config, fid: str, name: str = "", *, lead: str = "", private: bool = False,
                   match_paths: list[str] | None = None, match_keywords: list[str] | None = None,
                   brief: dict | None = None) -> Path:
    """A faction as a folder with FACTION.md (frontmatter is read by config.load, no toml edit needed)."""
    d = faction_dir(cfg, slugify(fid))
    d.mkdir(parents=True, exist_ok=True)
    note = d / "FACTION.md"
    if not note.exists():
        answers = dict(brief or {})
        fm = [f"{k}: {v}" for k, v in (
            ("name", name or fid), ("intent", answers.get("intent", "")), ("strategy", answers.get("strategy", "")),
            ("success_looks_like", answers.get("success_looks_like", "")), ("principles", answers.get("principles", "")),
            ("lead", lead), ("private", "true" if private else ""),
            ("match_paths", ", ".join(match_paths or [])), ("match_keywords", ", ".join(match_keywords or []))) if v]
        qs = cfg.briefs["faction"]["required"] + cfg.briefs["faction"]["optional"]
        body = f"# {name or fid}\n\n{answers.get('intent', '')}\n"
        bm = brief_markdown(answers, qs)
        if bm:
            body += f"\n## Brief\n{bm}\n"
        _atomic_write(note, "---\n" + "\n".join(fm) + "\n---\n" + body)
    return d


def brief_markdown(answers: dict[str, str], questions: list[tuple[str, str]]) -> str:
    """Render brief answers as '**question**  answer' blocks, in question order, then any extras."""
    seen, out = set(), []
    for key, q in questions:
        if answers.get(key):
            out.append(f"**{q}**\n{answers[key].strip()}")
            seen.add(key)
    for key, v in answers.items():
        if key not in seen and v:
            out.append(f"**{key}**\n{str(v).strip()}")
    return "\n\n".join(out)


def create_arc(cfg: cfgmod.Config, faction: str, arc_id: str, name: str = "", goal: str = "",
               complete_when: str = "", strategy: str = "", brief: dict | None = None) -> Path:
    d = faction_dir(cfg, faction) / slugify(arc_id)
    d.mkdir(parents=True, exist_ok=True)
    note = d / "ARC.md"
    if not note.exists():
        answers = dict(brief or {})
        goal = goal or answers.get("goal", "")
        complete_when = complete_when or answers.get("complete_when", "")
        strategy = strategy or answers.get("strategy", "")
        fm = [f"{k}: {v}" for k, v in (("name", name or arc_id), ("goal", goal), ("strategy", strategy),
                                        ("complete_when", complete_when)) if v]
        qs = cfg.briefs["arc"]["required"] + cfg.briefs["arc"]["optional"]
        body = f"# {name or arc_id}\n\n{goal}\n"
        bm = brief_markdown(answers, qs)
        if bm:
            body += f"\n## Brief\n{bm}\n"
        _atomic_write(note, "---\n" + "\n".join(fm) + "\n---\n" + body)
    return d


def create(cfg: cfgmod.Config, faction: str, title: str, *, arc: str = "", done: str = "", next: str = "",
           lead: str = "", waiting: str = "", objectives: list[str] | None = None, cwd: str = "",
           why: str = "", size: str = "", reward: str = "", brief: dict | None = None, after: str = "",
           authority: str = "", surface: str = "") -> Quest:
    answers = dict(brief or {})
    done = done or answers.get("done", "")
    why = why or answers.get("why", "")
    if not size and answers.get("size", "").strip().lower() in SIZES:
        size = answers["size"].strip().lower()
    f = cfg.faction(faction)
    arc = slugify(arc) if arc else ""
    d = faction_dir(cfg, faction) / arc if arc else faction_dir(cfg, faction)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{slugify(title)}.md"
    n = 2
    while path.exists():
        path = d / f"{slugify(title)}-{n}.md"
        n += 1
    qs = cfg.briefs["quest"]["required"] + cfg.briefs["quest"]["optional"]
    q = Quest(path=path, faction=faction, arc=arc, title=title, done=done, why=why, next=next, waiting=waiting,
              lead=lead or (f.lead if f else ""), cwd=cwd, size=size if size in SIZES else "", reward=reward,
              brief=brief_markdown(answers, qs), authority=authority if authority in AUTHORITIES else "",
              status="parked" if _unmet(cfg, after) else ("waiting" if waiting else "active"), after=after,
              surface=surface,
              objectives=[(False, o) for o in (objectives or [])])
    q.log.append(f"{date.today().isoformat()}: created")
    with locked(path):
        save(q, cfg)
    return q


# --- write surfaces ---------------------------------------------------------------

OPEN = ("active", "blocked", "waiting")


def surfaces(q: Quest) -> list[str]:
    return [str(Path(os.path.expanduser(s.strip())))
            for s in (q.surface or "").split(",") if s.strip()]


def surface_root(pattern: str) -> str:
    """The folder part of a path or glob: everything before the first wildcard."""
    head = re.split(r"[*?\[]", pattern, maxsplit=1)[0]
    return head.rstrip("/") if head != pattern else pattern.rstrip("/")


def _overlap(a: str, b: str) -> bool:
    if fnmatch.fnmatch(a, b) or fnmatch.fnmatch(b, a):
        return True
    ra, rb = surface_root(a), surface_root(b)
    return bool(ra and rb) and (ra == rb or ra.startswith(rb + "/") or rb.startswith(ra + "/"))


def _tilde(p: str) -> str:
    home = str(Path.home())
    return "~" + p[len(home):] if p.startswith(home + "/") else p


def conflicts(cfg: cfgmod.Config, q: Quest | None = None) -> list[dict]:
    """Open quests whose write surfaces overlap but whose leads differ: two agents about to edit the same
    files without knowing it. Same-lead overlaps are fine (one agent, sequenced work). With `q`, only its pairs."""
    open_q = [x for x in load(cfg, include_private=True) if x.status in OPEN and x.surface]
    if q is not None:
        others = [x for x in open_q if x.ref != q.ref]
        pairs = [(q, x) for x in others] if q.surface and q.status in OPEN else []
    else:
        pairs = [(x, y) for i, x in enumerate(open_q) for y in open_q[i + 1:]]
    out = []
    for x, y in pairs:
        if (x.lead or "") == (y.lead or "") and x.lead:
            continue
        # Show the narrower of each overlapping pair: that's where the edits will collide.
        shared = sorted({_tilde(max(a, b, key=len)) for a in surfaces(x) for b in surfaces(y) if _overlap(a, b)})
        if shared:
            out.append({"a": x.ref, "a_lead": x.lead, "b": y.ref, "b_lead": y.lead, "shared": shared[:4]})
    return out


def _unmet(cfg: cfgmod.Config, after: str) -> bool:
    reqs = [r.strip() for r in (after or "").split(",") if r.strip()]
    return any((x := find(r, cfg)) is None or x.status != "done" for r in reqs)
