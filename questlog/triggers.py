"""Triggers: the world event a sent-forth quest awaits, checked by machine (no LLM).

A quest whose part is done but which waits on someone other than the game master (a reviewer, CI, a merge,
a date) is "sent forth": status `sent`, with a `trigger` and what happens `then` (done, the default, or active).

    pr:OWNER/REPO#N merged     the pull request merged
    pr:OWNER/REPO#N closed     merged or closed without merging
    pr:OWNER/REPO#N reviewed   someone other than the author reviewed or commented since it was sent
    file:PATH                  the file exists (a post moved to its public folder, a build artifact)
    url:URL                    the page answers 200
    date:YYYY-MM-DD            the day has come
    quest:REF                  another quest is done

Anything else is plain words ("Peter's read of the draft"): shown, never checked.
`questlog check` (run on a timer) fires what's ready.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from . import config as cfgmod, events, store

PR = re.compile(r"^pr:\s*([\w.-]+/[\w.-]+)#(\d+)\s+(merged|closed|reviewed)\s*$", re.I)


@dataclass
class Result:
    ref: str
    trigger: str
    fired: bool
    detail: str          # what happened, or why it couldn't be checked
    checkable: bool = True


def checkable(trigger: str) -> bool:
    t = trigger.strip().lower()
    return bool(PR.match(trigger.strip())) or t.startswith(("file:", "url:", "date:", "quest:"))


def _sent_at(cfg: cfgmod.Config, ref: str) -> float:
    """When the quest was last sent forth (from the event journal); 0 if unknown."""
    ts = [e["ts"] for e in events.read(cfg) if e.get("ref") == ref and e.get("kind") == "sent"]
    return max(ts) if ts else 0.0


def _gh_pr(repo: str, n: str) -> dict:
    res = subprocess.run(["gh", "pr", "view", n, "--repo", repo, "--json",
                          "state,mergedAt,closedAt,author,reviews,comments"],
                         capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        raise RuntimeError((res.stderr or res.stdout).strip()[:160] or "gh failed")
    return json.loads(res.stdout)


def _ts(iso: str) -> float:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() if iso else 0.0


def evaluate(cfg: cfgmod.Config, q: store.Quest) -> Result:
    trig = q.trigger.strip()
    if not checkable(trig):
        return Result(q.ref, trig, False, "plain words; nothing to check", checkable=False)
    try:
        if m := PR.match(trig):
            repo, n, want = m.group(1), m.group(2), m.group(3).lower()
            pr = _gh_pr(repo, n)
            if want == "merged":
                return Result(q.ref, trig, bool(pr.get("mergedAt")), f"{repo}#{n} merged" if pr.get("mergedAt")
                              else f"{repo}#{n} is {pr.get('state', '?').lower()}")
            if want == "closed":
                return Result(q.ref, trig, pr.get("state") in ("MERGED", "CLOSED"), f"{repo}#{n} {pr.get('state', '?').lower()}")
            author = (pr.get("author") or {}).get("login", "")
            since = _sent_at(cfg, q.ref)
            fresh = [x for x in (pr.get("reviews") or []) + (pr.get("comments") or [])
                     if (x.get("author") or {}).get("login") not in (author, "")
                     and _ts(x.get("submittedAt") or x.get("createdAt") or "") > since]
            who = sorted({x["author"]["login"] for x in fresh})
            return Result(q.ref, trig, bool(fresh), f"{repo}#{n}: new review from {', '.join(who)}" if fresh
                          else f"{repo}#{n}: no new reviews")
        kind, _, arg = trig.partition(":")
        kind, arg = kind.lower(), arg.strip()
        if kind == "file":
            p = Path(os.path.expanduser(arg))
            return Result(q.ref, trig, p.exists(), f"{arg} exists" if p.exists() else f"{arg} not there yet")
        if kind == "url":
            try:
                with urllib.request.urlopen(urllib.request.Request(arg, method="GET"), timeout=20) as r:
                    ok = r.status == 200
            except OSError:
                ok = False
            return Result(q.ref, trig, ok, f"{arg} is live" if ok else f"{arg} not live yet")
        if kind == "date":
            day = date.fromisoformat(arg)
            return Result(q.ref, trig, date.today() >= day, f"{arg} has come" if date.today() >= day else f"until {arg}")
        if kind == "quest":
            other = store.find(arg, cfg)
            if other is None:
                return Result(q.ref, trig, False, f"no quest matches {arg!r}")
            return Result(q.ref, trig, other.status == "done", f"{other.title} is {other.status}")
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as e:
        return Result(q.ref, trig, False, f"couldn't check: {e}")
    return Result(q.ref, trig, False, "unknown trigger", checkable=False)


def fire(cfg: cfgmod.Config, q: store.Quest, r: Result) -> None:
    """The event happened: the quest is done, or back in play with the news as its next step.
    A trigger is a fact checked by machine, not an agent's judgment, so `then: done` closes the quest
    whatever its authority or review rule."""
    then = (q.then or "done").strip().lower()

    def apply(x: store.Quest) -> None:
        today = date.today().isoformat()
        x.log.append(f"{today}: the world moved: {r.detail}")
        if then == "active":
            x.status = "active"
            x.next = f"Word came back ({r.detail}); pick it up" if not x.next else f"{r.detail}: {x.next}"
        else:
            x.status = "done"
        x.waiting = ""
    store.update(q.ref, apply, cfg)


def check(cfg: cfgmod.Config | None = None, *, dry_run: bool = False) -> list[Result]:
    cfg = cfg or cfgmod.load()
    out = []
    for q in store.load(cfg, include_private=True, statuses={"sent"}):
        if not q.trigger:
            continue
        r = evaluate(cfg, q)
        if r.fired and not dry_run:
            os.environ.setdefault("QUESTLOG_AGENT", "watcher")
            fire(cfg, q, r)
        out.append(r)
    return out
