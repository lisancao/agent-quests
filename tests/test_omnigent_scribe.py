"""The Omnigent scribe: parsing an export, condensing it, recording it, and the idle timer."""
import json
from pathlib import Path

from questlog import bindings, cli, ledger, store
from questlog.scribe import core, omnigent

FIXTURES = Path(__file__).parent / "fixtures"
CONV = "conv_0123456789abcdef"
LAST = 1792003600.0   # updated_at in the fixture


def _export(conv_id: str) -> str:
    assert conv_id == CONV
    return (FIXTURES / "omnigent_export.jsonl").read_text()


def test_parse_and_meta():
    recs = omnigent.load(CONV, _export)
    assert omnigent.activity(recs) == LAST
    m = omnigent.meta(recs)
    assert m["cwd"] == "/home/gm/lair" and m["started"] == 1792000000
    assert m["first_prompt"].startswith("Wire the shark tank sensors")
    assert m["title"] == "Add shark tank sensors"


def test_condense_same_shape_as_claude_code():
    text = omnigent.condense(omnigent.load(CONV, _export))
    head, _, body = text.partition("\n\n")
    assert head.startswith(f"session {CONV} · cwd /home/gm/lair · 3 turns · last active ")
    assert "files edited: /home/gm/lair/controller.py" in head
    assert body.split("\n\n") == [
        "USER: Wire the shark tank sensors to the trapdoor controller.",
        "AGENT: I'll start by reading the controller.",
        "AGENT: Sensors wired; the trapdoor now waits for two readings. PR opened as me/lair#12.",
    ]
    assert "hidden" not in text   # is_meta messages stay out


def _fake_scribe(monkeypatch, seen):
    def call(cfg, prompt):
        seen.append(prompt)
        return {"faction": "lab", "arc": "inherits", "quest": "", "confidence": 1, "title": "Sensors",
                "digest": "Wired the sensors.", "journal_entry": "wired the sensors", "deeds": [],
                "quest_update": {"save_state": "wired", "next": "await review", "waiting": "", "status": "done",
                                 "done_met": True}}
    monkeypatch.setattr(core, "_call", call)


def test_run_records_omnigent_harness_and_full_id(cfg, monkeypatch):
    q = store.create(cfg, "lab", "Sensors", arc="inherits")
    seen = []
    _fake_scribe(monkeypatch, seen)
    msg = core.run(CONV, q.ref, cfg=cfg, force=True, records=omnigent.load(CONV, _export))
    assert "updated" in msg
    assert "Wire the shark tank sensors" in seen[0]
    rec = ledger.sessions(cfg)[CONV]
    assert rec["harness"] == "omnigent" and rec["cwd"] == "/home/gm/lair"
    fresh = store.find(q.ref, cfg)
    assert fresh.sessions == [CONV]
    assert f"`{CONV}`: wired the sensors" in fresh.log[-1]
    # cross-vendor review applies on the scribe path too: done_met, but no review recorded
    assert fresh.status == "waiting" and "cross-vendor review required" in fresh.waiting
    assert omnigent.scribed_at(CONV) == LAST


def test_scribe_idle_picks_quiet_unscribed_bound_sessions(cfg):
    q = store.create(cfg, "lab", "Sensors", arc="inherits")
    bindings.attach(CONV, q.ref)
    bindings.attach("1a2b3c4d-claude-session", q.ref)   # not Omnigent: ignored
    calls = []

    def run(conv_id, ref, **kw):
        calls.append((conv_id, ref))
        core._save_state(core.STATE / f"{conv_id}.json", {"size": 1, "activity": LAST})
        return "scribed"

    core.STATE.mkdir(parents=True, exist_ok=True)
    out = omnigent.scribe_idle(15, export=_export, cfg=cfg, now=LAST + 5 * 60, run=run)
    assert calls == [] and "still active" in out[0]
    out = omnigent.scribe_idle(15, export=_export, cfg=cfg, now=LAST + 20 * 60, run=run)
    assert calls == [(CONV, q.ref)] and out == [f"{CONV} scribed"]
    out = omnigent.scribe_idle(15, export=_export, cfg=cfg, now=LAST + 60 * 60, run=run)
    assert calls == [(CONV, q.ref)] and "already scribed" in out[0]


def test_export_failure_is_reported_not_raised(cfg):
    bindings.attach(CONV, "lab/x")

    def broken(conv_id):
        raise RuntimeError("omnigent export failed: not logged in")
    assert omnigent.scribe_idle(0, export=broken, cfg=cfg) == [f"{CONV} omnigent export failed: not logged in"]


def test_cli_command_wired(cfg, monkeypatch, capsys):
    monkeypatch.setattr(omnigent, "cli_export", _export)
    bindings.attach(CONV, "lab/x")
    cli.main(["scribe-omnigent", "--idle-minutes", "15", "--dry-run"])
    assert f"{CONV} would scribe -> lab/x" in capsys.readouterr().out


def test_link():
    assert omnigent.link(CONV) == f"https://omnigent.systemsnull.net/c/{CONV}"
    assert json.loads((FIXTURES / "omnigent_export.jsonl").read_text().splitlines()[0])["record_type"] == "session_meta"


def test_id_dispatch():
    assert omnigent.is_omnigent(CONV)
    assert omnigent.is_omnigent("60e82a4e6da03bb3c8793b925c3e10ac")       # bare server id
    assert not omnigent.is_omnigent("d6f968a8-1296-4411-9498-c4968c665f09")  # Claude Code session
