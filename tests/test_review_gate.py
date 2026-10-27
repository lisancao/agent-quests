"""quest_review records, vendor families, and the cross-vendor done gate on every path that closes a quest
except a fired trigger."""
import pytest

from questlog import cli, reviews, server, store, triggers, views


@pytest.mark.parametrize("name,family", [
    ("claude", "anthropic"), ("Claude", "anthropic"), ("anthropic/claude-opus-5", "anthropic"),
    ("openai/codex", "openai"), ("codex", "openai"), ("gpt-5", "openai"), ("o3", "openai"),
    ("google/gemini", "google"), ("gemini-2.5-pro", "google"),
    ("openrouter:anthropic/claude-sonnet-4", "anthropic"), ("openrouter:qwen/qwen3-coder", "alibaba"),
    ("openrouter:someco/new-model", "someco"), ("local:llama3.1", "meta"), ("local:gemma3", "google"),
])
def test_vendor_family(name, family):
    assert reviews.vendor(name) == family


def _quest(cfg, title="Ship it", **kw):
    return store.create(cfg, kw.pop("faction", "lab"), title, **kw)


def _done(ref):
    return server.quest_update(ref, status="done")


def test_no_review_blocks_done(cfg):
    q = _quest(cfg, arc="inherits")
    out = _done(q.ref)
    assert out["status"] == "waiting"
    assert out["waiting"].startswith("Sign-off: proposed done, but cross-vendor review required")
    assert any("no review is recorded" in n for n in out["notes"])


def test_same_vendor_pass_blocked(cfg):
    q = _quest(cfg, arc="inherits")
    server.quest_review(q.ref, "me/lab#1", "claude", "anthropic/opus", "pass")
    out = _done(q.ref)
    assert out["status"] == "waiting"
    assert "same-vendor" in out["waiting"]


def test_cross_vendor_fail_blocked(cfg):
    q = _quest(cfg, arc="inherits")
    server.quest_review(q.ref, "me/lab#1", "claude", "openai/codex", "fail", notes="tests missing")
    out = _done(q.ref)
    assert out["status"] == "waiting" and "no review has passed" in out["waiting"]


def test_cross_vendor_pass_allows_done(cfg):
    q = _quest(cfg, arc="inherits")
    res = server.quest_review(q.ref, "me/lab#1", "claude", "openai/codex", "fail")
    assert res["can_close"] is False
    res = server.quest_review(q.ref, "me/lab#1", "claude", "openrouter:google/gemini-2.5-pro", "pass")
    assert res["can_close"] is True and res["recorded"]["reviewer_vendor"] == "google"
    out = _done(q.ref)
    assert out["status"] == "done" and not out.get("notes")


def test_review_none_and_empty_unaffected(cfg):
    for q in (_quest(cfg, "Relaxed one", arc="relaxed"), _quest(cfg, "Plain one", faction="plain"),
              _quest(cfg, "Opted out", arc="inherits", review="none")):
        assert _done(q.ref)["status"] == "done"


def test_review_is_logged_and_queryable(cfg):
    q = _quest(cfg, arc="inherits")
    server.quest_review(q.ref, "me/lab#7", "claude", "openai/codex", "pass", notes="looks right")
    rows = reviews.for_quest(cfg, q.ref)
    assert [(r["implementer_vendor"], r["reviewer_vendor"], r["verdict"], r["pr"]) for r in rows] == \
        [("anthropic", "openai", "pass", "me/lab#7")]
    got = server.quest_get(q.ref)
    assert got["reviews"][0]["notes"] == "looks right"
    assert "review pass · me/lab#7 · claude (anthropic) reviewed by openai/codex (openai)" in got["log"][-1]
    assert server.quest_review(q.ref, "x", "a", "b", "maybe")["error"].startswith("verdict must be")


def test_parent_auto_close_gated(cfg):
    parent = _quest(cfg, "Parent", arc="inherits")
    kid = _quest(cfg, "Kid", arc="relaxed", parent=parent.ref)
    _done(kid.ref)
    p = store.find(parent.ref, cfg)
    assert p.status == "waiting" and "cross-vendor review required" in p.waiting
    # with a cross-vendor pass on the parent, the next sub-quest completion closes it
    server.quest_update(p.ref, waiting="")
    server.quest_review(p.ref, "me/lab#2", "claude", "codex", "pass")
    kid2 = _quest(cfg, "Kid two", arc="relaxed", parent=parent.ref)
    _done(kid2.ref)
    assert store.find(parent.ref, cfg).status == "done"


def test_trigger_fire_not_gated(cfg):
    q = _quest(cfg, arc="inherits")
    server.quest_update(q.ref, status="sent", trigger="pr:me/lab#3 merged")
    triggers.fire(cfg, store.find(q.ref, cfg), triggers.Result(q.ref, "pr:me/lab#3 merged", True, "PR merged"))
    q = store.find(q.ref, cfg)
    assert q.status == "done" and q.waiting == ""
    assert reviews.for_quest(cfg, q.ref) == []


def test_cli_set_gated_unless_signoff(cfg, capsys):
    q = _quest(cfg, arc="inherits")
    cli.main(["set", q.ref, "status=done"])
    assert store.find(q.ref, cfg).status == "waiting"
    assert "not marked done" in capsys.readouterr().err
    cli.main(["set", q.ref, "status=done", "waiting=", "--signoff"])
    assert store.find(q.ref, cfg).status == "done"


def test_create_and_update_params(cfg):
    out = server.quest_create("plain", "Routed", brief={"done": "d", "why": "w"}, workflow="polly",
                              review="cross-vendor")
    assert (out["workflow"], out["review"]) == ("polly", "cross-vendor")
    out = server.quest_update(out["ref"], review="none", status="done")
    assert out["status"] == "done" and out["review"] == "none"
    assert "error" in server.quest_update(out["ref"], workflow="hal")


def test_seed_prompt_surfaces_routing(cfg):
    q = store.find(_quest(cfg, arc="inherits").ref, cfg)
    text = views.seed_prompt(q, cfg)
    assert "Workflow: polly" in text and f"`quest_attach` with ref `{q.ref}`" in text
    assert "quest_review" in text and "Review: cross-vendor" in text
    plain = views.seed_prompt(store.find(_quest(cfg, "Bare", faction="plain").ref, cfg), cfg)
    assert "Workflow" not in plain and "Review" not in plain
    claude = views.seed_prompt(store.find(_quest(cfg, "Claudey", faction="plain", arc="routed").ref, cfg), cfg)
    assert "Workflow: claude." in claude and "quest_attach" not in claude
    assert "workflow polly, review cross-vendor" in views.puck_prompt(cfg)
