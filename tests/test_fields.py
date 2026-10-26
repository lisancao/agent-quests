"""workflow / review fields: parsing, round-trips, and defaults resolved quest > arc > faction > empty."""
from questlog import config as cfgmod, store

LEGACY = """---
title: Install the shark tank
status: active
lead: claude
authority: proposes
done: Sharks in, glass holds
next: Fix the trapdoor
sessions: 1a2b3c4d,5e6f7a8b
cwd: ~/lair
updated: 2026-03-12
---
## Objectives
- [x] Dig the pit
- [ ] Fix the trapdoor

## Save state
Pit dug.

## Log
- 2026-03-12: created
"""


def _write(cfg, rel: str, text: str):
    p = cfg.root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def test_legacy_file_round_trips_byte_identically(cfg):
    p = _write(cfg, "lab/inherits/shark-tank.md", LEGACY)
    q = store.parse(p, "lab", "inherits")
    assert (q.workflow, q.review) == ("", "")
    assert store.render(q) == LEGACY


def test_legacy_file_keeps_no_routing_fields_after_a_write(cfg):
    p = _write(cfg, "lab/inherits/shark-tank.md", LEGACY)
    # load() resolves the faction defaults for reading; a write must not persist them.
    assert store.find("shark-tank", cfg).review == "cross-vendor"
    store.update("shark-tank", lambda q: q.log.append("2026-03-13: poked"), cfg)
    text = p.read_text()
    assert "workflow:" not in text and "review:" not in text
    assert text.replace("updated: " + store.parse(p, "lab", "inherits").updated, "updated: 2026-03-12") \
        .replace("- 2026-03-13: poked\n", "") == LEGACY


def test_fields_parse_render_and_to_dict(cfg):
    text = LEGACY.replace("authority: proposes\n", "authority: proposes\nworkflow: puck\nreview: none\n")
    p = _write(cfg, "plain/routed/x.md", text)
    q = store.parse(p, "plain", "routed")
    assert (q.workflow, q.review) == ("puck", "none")
    assert store.render(q) == text
    d = q.to_dict()
    assert d["workflow"] == "puck" and d["review"] == "none"


def test_create_validates_like_authorities(cfg):
    q = store.create(cfg, "plain", "Odd", workflow="hal9000", review="maybe")
    assert (q.workflow, q.review) == ("", "")
    q = store.create(cfg, "plain", "Even", workflow="debby", review="cross-vendor")
    assert "workflow: debby" in q.path.read_text() and "review: cross-vendor" in q.path.read_text()


def test_defaults_quest_over_arc_over_faction_over_empty(cfg):
    faction_only = store.create(cfg, "lab", "A", arc="inherits")
    arc_wins = store.create(cfg, "lab", "B", arc="relaxed")
    quest_wins = store.create(cfg, "lab", "C", arc="relaxed", workflow="puck", review="cross-vendor")
    no_arc = store.create(cfg, "lab", "D")
    empty = store.create(cfg, "plain", "E")
    plain_arc = store.create(cfg, "plain", "F", arc="routed")
    got = {q.title: (store.effective(cfg, q, "workflow"), store.effective(cfg, q, "review"))
           for q in (faction_only, arc_wins, quest_wins, no_arc, empty, plain_arc)}
    assert got == {"A": ("polly", "cross-vendor"), "B": ("debby", "none"), "C": ("puck", "cross-vendor"),
                   "D": ("polly", "cross-vendor"), "E": ("", ""), "F": ("claude", "cross-vendor")}
    # load() shows the resolved values; the file keeps only what the quest itself sets.
    assert store.find("a", cfg).to_dict()["workflow"] == "polly"
    assert "workflow" not in faction_only.path.read_text()


def test_defaults_from_faction_and_arc_notes(tmp_path):
    root = tmp_path / "q"
    (root / "side" / "arcy").mkdir(parents=True)
    (root / "side" / "FACTION.md").write_text("---\nname: Side\nworkflow: debby\nreview: cross-vendor\n---\n")
    (root / "side" / "arcy" / "ARC.md").write_text("---\nname: Arcy\nreview: none\nworkflow: bogus\n---\n")
    toml = tmp_path / "c.toml"
    toml.write_text(f'root = "{root}"\n')
    cfg = cfgmod.load(toml)
    f = cfg.faction("side")
    assert (f.workflow, f.review) == ("debby", "cross-vendor")
    assert (f.arc("arcy").workflow, f.arc("arcy").review) == ("", "none")
