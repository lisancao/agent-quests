"""questlog CLI. The same operations the MCP server exposes, for humans, scripts and hooks."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import bindings, briefs, config as cfgmod, ledger, store, views

BADGE = {"active": "ACT ", "blocked": "WALL", "waiting": "YOU ", "parked": "PARK", "done": "DONE"}


def _print_json(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def cmd_init(a) -> int:
    path = cfgmod.config_path()
    if path.exists():
        print(f"{path} already exists")
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    root = a.root or "~/quests"
    path.write_text(cfgmod.SAMPLE.replace("{root}", root).replace("{human}", a.human or "you"))
    Path(root).expanduser().mkdir(parents=True, exist_ok=True)
    print(f"wrote {path}; quests live in {root}")
    return 0


def cmd_ls(a) -> int:
    cfg = cfgmod.load()
    qs = store.load(cfg, a.faction, include_private=a.all or bool(a.faction), lead=a.lead)
    if not a.done:
        qs = [q for q in qs if q.status != "done"]
    for q in qs:
        wait = f"  ⏳ {q.waiting}" if q.waiting else ""
        print(f"[{BADGE.get(q.status, q.status)}] {q.ref:<44} {q.lead or '-':<7} next: {q.next[:60]}{wait[:50]}")
    return 0


def cmd_show(a) -> int:
    q = store.find(a.ref)
    if not q:
        print(f"no single quest matches {a.ref!r}", file=sys.stderr)
        return 1
    print(q.path.read_text())
    return 0


def _ask_brief(cfg: cfgmod.Config, level: str, given: dict) -> dict:
    """Ask the required brief questions that aren't answered yet (interactive terminals only)."""
    answers = {k: v for k, v in given.items() if v}
    miss = briefs.missing(cfg, level, answers)
    if miss and sys.stdin.isatty():
        print(f"A quick brief for this {level} (enter to skip):")
        for m in miss:
            ans = input(f"  {m['question']}\n  > ").strip()
            if ans:
                answers[m["key"]] = ans
    return answers


def cmd_new(a) -> int:
    cfg = cfgmod.load()
    if not cfg.faction(a.faction):
        print(f"unknown faction {a.faction!r}; known: {', '.join(f.id for f in cfg.factions)}", file=sys.stderr)
        return 1
    answers = _ask_brief(cfg, "quest", {"done": a.done or "", "why": a.why or ""})
    q = store.create(cfg, a.faction, a.title, arc=a.arc or "", next=a.next or "", lead=a.lead or "",
                     objectives=a.objective or [], size=a.size or "", reward=a.reward or "", brief=answers)
    print(q.ref)
    return 0


def cmd_faction(a) -> int:
    cfg = cfgmod.load()
    if cfg.faction(a.id):
        print(f"faction {a.id!r} already exists", file=sys.stderr)
        return 1
    answers = _ask_brief(cfg, "faction", {"intent": a.intent or "", "strategy": a.strategy or ""})
    print(store.create_faction(cfg, a.id, a.name or "", lead=a.lead or "", private=a.private,
                               match_paths=a.path or [], match_keywords=a.keyword or [], brief=answers))
    return 0


def cmd_arc(a) -> int:
    cfg = cfgmod.load()
    if not cfg.faction(a.faction):
        print(f"unknown faction {a.faction!r}", file=sys.stderr)
        return 1
    answers = _ask_brief(cfg, "arc", {"goal": a.goal or "", "complete_when": a.complete_when or ""})
    print(store.create_arc(cfg, a.faction, a.arc, a.name or "", brief=answers))
    return 0


def cmd_tree(a) -> int:
    cfg = cfgmod.load()
    qs = [q for q in store.load(cfg) if q.status != "done"]
    for f in cfg.factions:
        if f.private and not a.all:
            print(f"{f.name}  (private)")
            continue
        print(f"{f.name}" + (f"  ·  {f.charter}" if f.charter else ""))
        for aid in [x.id for x in f.arcs] + [""]:
            aq = [q for q in qs if q.faction == f.id and q.arc == aid]
            if aid:
                arc = f.arc(aid)
                print(f"  ├ {arc.name if arc else aid}" + (f"  ·  {arc.goal}" if arc and arc.goal else ""))
            elif not aq:
                continue
            for q in aq:
                print(f"  {'│' if aid else ' '}   [{BADGE.get(q.status, q.status)}] {q.title}  ({q.lead or '-'})")
    return 0


def cmd_orient(a) -> int:
    from . import orient
    if a.cwd is None and a.prompt is None and not sys.stdin.isatty():
        out = orient.hook(sys.stdin.read())   # hook mode
        if out:
            print(out)
        return 0
    print(orient.briefing(cfgmod.load(), a.session or "", a.cwd or os.getcwd(), a.prompt or ""))
    return 0


def cmd_backfill(a) -> int:
    from .scribe import core
    n = core.backfill(days=a.days, limit=a.limit)
    print(f"scribed {n} sessions")
    return 0


def _bar(into: int, span: int, width: int = 20) -> str:
    if span <= 0:
        return "█" * width
    filled = int(width * into / span)
    return "█" * filled + "░" * (width - filled)


def cmd_sheet(a) -> int:
    from . import rewards
    sh = rewards.sheet(include_private=a.all)
    cfg = cfgmod.load()
    print(f"{cfg.human}  ·  level {sh.level}  {_bar(sh.into_level, sh.level_span)}  {sh.into_level}/{sh.level_span} xp"
          f"  (total {sh.xp})")
    print(f"{sh.deeds_total} deeds · {sh.quests_done} quests · {sh.arcs_done} arcs · {sh.sessions} sessions recorded\n")
    for r in sh.reputation:
        nxt = f" → {r.next_tier}" if r.next_tier else ""
        print(f"  {r.name[:30]:<30} {r.tier:<11} {_bar(r.into_tier, r.tier_span, 14)} {r.xp:>5} xp{nxt}")
    if sh.achievements:
        print("\nachievements: " + ", ".join(x["name"] for x in sh.achievements))
    if sh.inventory:
        print("inventory: " + ", ".join(x["reward"] for x in sh.inventory))
    return 0


def cmd_deeds(a) -> int:
    import time
    from datetime import datetime
    cfg = cfgmod.load()
    for d in ledger.deeds(cfg, since=time.time() - a.days * 86400, faction=a.faction)[:40]:
        when = datetime.fromtimestamp(d["ts"]).strftime("%a %d %H:%M")
        where = "/".join(x for x in (d.get("faction"), d.get("arc")) if x) or "-"
        print(f"+{d['xp']:<3} {when}  {where:<28} {d['text'][:90]}")
    return 0


def cmd_recall(a) -> int:
    cfg = cfgmod.load()
    hits = [r for sid, r in ledger.sessions(cfg).items() if sid.startswith(a.session_id)]
    if len(hits) != 1:
        print(f"{len(hits)} sessions match {a.session_id!r}", file=sys.stderr)
        return 1
    _print_json(hits[0])
    return 0


def cmd_suggestions(a) -> int:
    for s in ledger.suggestions(cfgmod.load()):
        print(f"? {s.get('faction')}/{s.get('arc') or '-'}: {s.get('title')}  (done: {s.get('done', '')[:60]})")
    return 0


def cmd_commons(a) -> int:
    from datetime import datetime
    from . import commons
    cfg = cfgmod.load()
    if a.turn:
        r = commons.take_turn(cfg, session_id=a.session or f"cli-{int(__import__('time').time())}", by=a.by or cfg.human,
                              observation=a.turn, pattern=a.pattern or "", x=a.x, y=a.y, steps=a.steps)
        if r.get("error"):
            print(r["error"], file=sys.stderr)
            return 1
    info = commons.look(cfg)
    print(f"the commons · rule {info['rule']} · generation {info['generation']} · population {info['population']}")
    print(info["world"])
    for c in info["chronicle"]:
        when = datetime.fromtimestamp(c["ts"]).strftime("%b %d")
        print(f"  {when} {c['by']}: {c['pattern']} → gen {c['generation'][1]}. {c['observation'][:110]}")
    return 0


def cmd_hub(a) -> int:
    try:
        from .hub.app import run
    except ImportError as e:
        print(f"the hub needs textual: pip install 'questlog[hub]' ({e})", file=sys.stderr)
        return 1
    run()
    return 0


def cmd_set(a) -> int:
    def apply(q: store.Quest) -> None:
        for kv in a.pairs:
            k, _, v = kv.partition("=")
            if k == "log":
                from datetime import date
                q.log.append(f"{date.today().isoformat()}: {v}")
            elif k in store.FIELDS and k not in ("sessions", "updated"):
                setattr(q, k, v)
            else:
                raise SystemExit(f"unknown field {k!r}")
    try:
        q = store.update(a.ref, apply)
    except KeyError as e:
        print(e, file=sys.stderr)
        return 1
    print(f"{q.ref}: saved")
    return 0


def cmd_attach(a) -> int:
    q = store.find(a.ref)
    if not q:
        print(f"no single quest matches {a.ref!r}", file=sys.stderr)
        return 1
    bindings.attach(a.session_id, q.ref)
    print(f"{a.session_id[:8]} -> {q.ref}")
    return 0


def cmd_brief(a) -> int:
    b = views.brief(agent=a.agent, include_private=a.all)
    if a.json:
        _print_json(b)
        return 0
    if not b:
        print("nothing open. enjoy it.")
    for key, item in b.items():
        label = key.replace("_", " ")
        detail = item.get("waiting") or item.get("next") or ""
        print(f"{label:<18} {item['title']}  ·  {detail}")
    return 0


def cmd_waiting(a) -> int:
    for w in views.waiting_on_human(include_private=a.all):
        print(f"⏳ {w['waiting']}   ({w['ref']})")
    return 0


def cmd_standing(a) -> int:
    cfg = cfgmod.load()
    for f in ([cfg.faction(a.faction)] if a.faction else cfg.factions):
        if f is None:
            print(f"unknown faction {a.faction!r}", file=sys.stderr)
            return 1
        if f.private and not a.faction and not a.all:
            continue
        s = views.standing(f.id, cfg)
        print(f"{s['name']}: {s['quests_done']} quests done, {s['objectives_done']} objectives"
              + (f"; open {dict(s['open'])}" if s["open"] else ""))
        for m in s["recent"][:3]:
            print(f"   · {m[:110]}")
    return 0


def cmd_puck(a) -> int:
    """Talk to Puck: launches Claude Code with Puck's role and model (or prints the prompt for other agents)."""
    import shutil
    import tempfile
    cfg = cfgmod.load()
    prompt = views.puck_prompt(cfg)
    if a.print or not shutil.which("claude"):
        print(prompt)
        return 0
    pf = Path(tempfile.gettempdir()) / "questlog-puck-prompt.md"
    pf.write_text(prompt)
    env = {**os.environ, "QUESTLOG_AGENT": "puck"}
    cmd = ["claude", "--model", a.model or cfg.puck_model, "-n", "puck", "--append-system-prompt-file", str(pf)]
    if a.request:
        cmd.append(" ".join(a.request))
    os.chdir(cfg.root if cfg.root.exists() else Path.home())
    os.execvpe(cmd[0], cmd, env)


def cmd_inbox(a) -> int:
    from . import inbox
    evs = inbox.read(a.session_id, a.agent or "", advance=not a.peek)
    print(inbox.render(evs, limit=30) if evs else "nothing new")
    return 0


def cmd_nudge(a) -> int:
    from . import nudge
    out = nudge.hook(sys.stdin.read())   # Stop hook: prints a block decision at most once per session
    if out:
        print(out)
    return 0


def cmd_scribe(a) -> int:
    from .scribe import core
    if a.session_id:
        ref = a.quest or bindings.quest_for(a.session_id)
        if not ref:
            print("session isn't bound to a quest (use --quest)", file=sys.stderr)
            return 1
        print(core.run(a.session_id, ref, throttle=a.throttle))
        return 0
    core.hook(sys.stdin.read(), throttle=a.throttle)  # hook mode: JSON on stdin, silent
    return 0


def cmd_serve(a) -> int:
    from .server import serve
    serve()
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="questlog", description="A quest log for your agents.")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("init", help="write a starter questlog.toml")
    s.add_argument("--root"); s.add_argument("--human"); s.set_defaults(fn=cmd_init)
    s = sub.add_parser("ls", help="list open quests")
    s.add_argument("faction", nargs="?"); s.add_argument("--lead"); s.add_argument("--done", action="store_true")
    s.add_argument("--all", action="store_true", help="include private factions"); s.set_defaults(fn=cmd_ls)
    s = sub.add_parser("show", help="print a quest file"); s.add_argument("ref"); s.set_defaults(fn=cmd_show)
    s = sub.add_parser("new", help="create a quest")
    s.add_argument("faction"); s.add_argument("title"); s.add_argument("--done"); s.add_argument("--next")
    s.add_argument("--lead"); s.add_argument("--arc"); s.add_argument("--objective", action="append")
    s.add_argument("--why"); s.add_argument("--size", choices=store.SIZES); s.add_argument("--reward")
    s.set_defaults(fn=cmd_new)
    s = sub.add_parser("faction", help="create a faction: questlog faction <id> --name ... (asks the brief)")
    s.add_argument("id"); s.add_argument("--name"); s.add_argument("--intent"); s.add_argument("--strategy")
    s.add_argument("--lead"); s.add_argument("--private", action="store_true")
    s.add_argument("--path", action="append", help="folder whose sessions serve it (repeatable)")
    s.add_argument("--keyword", action="append", help="keyword that signals it (repeatable)")
    s.set_defaults(fn=cmd_faction)
    s = sub.add_parser("arc", help="create an arc: questlog arc <faction> <arc-id> --name ... --goal ...")
    s.add_argument("faction"); s.add_argument("arc"); s.add_argument("--name"); s.add_argument("--goal")
    s.add_argument("--complete-when", dest="complete_when"); s.set_defaults(fn=cmd_arc)
    s = sub.add_parser("orient", help="orientation for a session (hook mode reads JSON on stdin)")
    s.add_argument("--cwd"); s.add_argument("--prompt"); s.add_argument("--session"); s.set_defaults(fn=cmd_orient)
    s = sub.add_parser("backfill", help="run the scribe over recent past sessions")
    s.add_argument("--days", type=float, default=7); s.add_argument("--limit", type=int, default=200)
    s.set_defaults(fn=cmd_backfill)
    s = sub.add_parser("sheet", help="character sheet: level, reputation, achievements")
    s.add_argument("--all", action="store_true"); s.set_defaults(fn=cmd_sheet)
    s = sub.add_parser("deeds", help="recent deeds across sessions")
    s.add_argument("--days", type=float, default=7); s.add_argument("--faction"); s.set_defaults(fn=cmd_deeds)
    s = sub.add_parser("recall", help="what a past session did"); s.add_argument("session_id"); s.set_defaults(fn=cmd_recall)
    s = sub.add_parser("suggestions", help="quests the scribe proposes"); s.set_defaults(fn=cmd_suggestions)
    s = sub.add_parser("hub", help="the quest journal (TUI)"); s.set_defaults(fn=cmd_hub)
    s = sub.add_parser("commons", help="the shared automata world agents grow together")
    s.add_argument("--turn", metavar="OBSERVATION", help="take a turn and leave this observation")
    s.add_argument("--pattern"); s.add_argument("--x", type=int); s.add_argument("--y", type=int)
    s.add_argument("--steps", type=int, default=4); s.add_argument("--by"); s.add_argument("--session")
    s.set_defaults(fn=cmd_commons)
    s = sub.add_parser("tree", help="factions -> arcs -> quests"); s.add_argument("--all", action="store_true")
    s.set_defaults(fn=cmd_tree)
    s = sub.add_parser("set", help="set fields: questlog set <ref> status=parked next='...' log='...'")
    s.add_argument("ref"); s.add_argument("pairs", nargs="+"); s.set_defaults(fn=cmd_set)
    s = sub.add_parser("attach", help="bind a session to a quest")
    s.add_argument("ref"); s.add_argument("session_id"); s.set_defaults(fn=cmd_attach)
    s = sub.add_parser("brief", help="at most three things")
    s.add_argument("--agent"); s.add_argument("--json", action="store_true"); s.add_argument("--all", action="store_true")
    s.set_defaults(fn=cmd_brief)
    s = sub.add_parser("waiting", help="what's waiting on you"); s.add_argument("--all", action="store_true")
    s.set_defaults(fn=cmd_waiting)
    s = sub.add_parser("standing", help="progress per faction"); s.add_argument("faction", nargs="?")
    s.add_argument("--all", action="store_true"); s.set_defaults(fn=cmd_standing)
    s = sub.add_parser("puck", help="talk to Puck, keeper of the quest log (Claude Code), or --print its prompt")
    s.add_argument("request", nargs="*"); s.add_argument("--print", action="store_true"); s.add_argument("--model")
    s.set_defaults(fn=cmd_puck)
    s = sub.add_parser("inbox", help="events relevant to a session since it last looked")
    s.add_argument("session_id"); s.add_argument("--agent"); s.add_argument("--peek", action="store_true")
    s.set_defaults(fn=cmd_inbox)
    s = sub.add_parser("nudge", help="Stop hook: once per session, ask the agent to update its quest")
    s.set_defaults(fn=cmd_nudge)
    s = sub.add_parser("scribe", help="update a quest from a session (hook mode reads JSON on stdin)")
    s.add_argument("session_id", nargs="?"); s.add_argument("--quest"); s.add_argument("--throttle", action="store_true")
    s.set_defaults(fn=cmd_scribe)
    s = sub.add_parser("serve", help="run the MCP server (stdio)"); s.set_defaults(fn=cmd_serve)

    a = p.parse_args(argv)
    if not getattr(a, "fn", None):
        a = p.parse_args(["brief"])
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
