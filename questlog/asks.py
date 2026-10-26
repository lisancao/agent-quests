"""Closed questions inside a quest's `waiting`, so the game master can answer in a word.

Puck writes them as "Question? A / B (Puck: A; why)" or "Topic: A, or B? (Puck: B; why)", several to a
waiting when a quest needs more than one call. A waiting with no question mark is open-ended; a sign-off or
a proposed status change is a yes / not yet.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

OPTS_AFTER = re.compile(r"^\s*((?:[^/()?.:]+?\s/\s)+[^/()?.:]+?)(?=\s*\(|\s*[.·](?:\s|$)|\s*$|\s+[A-Z])")
PUCK = re.compile(r"^\s*\(\s*puck:\s*", re.I)
LEAD = re.compile(r"^(?:then|and|also)\s+", re.I)
WHO = re.compile(r"^\w+:\s+(?=[a-z])")   # "Lisa: did the alerts..." -> "did the alerts..."


@dataclass
class Ask:
    text: str                    # the question, without its options or Puck's pick
    options: list[str] = field(default_factory=list)
    pick: str = ""               # Puck's pick, matched to an option where it can be
    why: str = ""
    span: tuple[int, int] = (0, 0)   # where it sits in the waiting text

    @property
    def closed(self) -> bool:
        return bool(self.options)


def _close_paren(s: str, i: int) -> int:
    """Index just past the parenthesis that opens at s[i]."""
    depth = 0
    for j in range(i, len(s)):
        depth += {"(": 1, ")": -1}.get(s[j], 0)
        if depth == 0:
            return j + 1
    return len(s)


def _inline_options(q: str) -> list[str]:
    """Options written into the question itself: "Topic: A, or B?" / "Topic: A / B?" / "Topic: A or B?"."""
    body = q.rstrip("?").rsplit(": ", 1)[-1] if ": " in q else q.rstrip("?")
    if ", or " in body:
        head, last = body.rsplit(", or ", 1)
        parts = [p for p in head.split(", ")] + [last]
    elif " / " in body:
        parts = body.split(" / ")
    elif " or " in body and ": " in q:
        parts = body.rsplit(" or ", 1)
    else:
        return []
    parts = [p.strip() for p in parts if p.strip()]
    return parts if len(parts) > 1 else []


def _match(pick: str, options: list[str]) -> str:
    p = pick.strip().lower()
    for o in options:
        if o.lower() == p or o.lower().startswith(p) or p.startswith(o.lower()):
            return o
    for o in options:
        if p and p in o.lower():
            return o
    first = p.split(" ", 1)[0]
    hits = [o for o in options if o.lower().split(" ", 1)[0] == first]
    return hits[0] if len(hits) == 1 else ""


def parse(waiting: str) -> list[Ask]:
    w = waiting or ""
    if w.lower().startswith(("sign-off", "proposed status")):
        return [Ask(w, ["yes", "not yet"], span=(0, len(w)))]
    out: list[Ask] = []
    i = 0
    while True:
        while i < len(w) and w[i] in " .·":
            i += 1
        # The next question mark outside parentheses.
        j, depth = i, 0
        while j < len(w) and not (w[j] == "?" and depth == 0):
            depth += {"(": 1, ")": -1}.get(w[j], 0)
            j += 1
        if j >= len(w):
            break
        start, q = i, LEAD.sub("", WHO.sub("", w[i:j + 1].strip()))
        k = j + 1
        opts: list[str] = []
        if m := OPTS_AFTER.match(w[k:]):
            opts = [o.strip() for o in m.group(1).split(" / ")]
            k += m.end()
        else:
            opts = _inline_options(q)
            if opts:
                q = q[: q.rfind(": ") + 1] if ": " in q else q
        pick = why = ""
        if PUCK.match(w[k:]):
            p0 = k + w[k:].index("(")
            end = _close_paren(w, p0)
            inner = PUCK.sub("", w[p0:end - 1], count=1)
            pick, _, why = inner.partition(";")
            pick, why = pick.strip(), why.strip()
            k = end
        if not opts and re.match(r"^(did|is|are|has|have|was|were|do|does|ok|okay|restarted|rebooted|revoked)\b", q, re.I):
            opts = ["yes", "not yet"]
        out.append(Ask(q.strip().rstrip(":"), opts, _match(pick, opts) if pick and opts else "", why, (start, k)))
        i = k
    return out


def rest(waiting: str, asks: list[Ask]) -> str:
    """What's left of the waiting once its questions are taken out (a trailing note, an open request)."""
    w, cut = waiting or "", 0
    out = []
    for a in asks:
        out.append(w[cut:a.span[0]])
        cut = a.span[1]
    out.append(w[cut:])
    return re.sub(r"^[\s.·]+|[\s·]+$", "", " ".join(x.strip(" .·") for x in out if x.strip(" .·")))


def without(waiting: str, ask: Ask) -> str:
    """The waiting with one answered question removed."""
    w = waiting or ""
    left = (w[: ask.span[0]] + " " + w[ask.span[1]:]).strip(" .·")
    return re.sub(r"\s{2,}", " ", left)


def answer(cfg, ref: str, n: int, choice: str, by: str = "") -> "object":
    """Record the game master's answer to the n-th question in a quest's waiting: a log line, the question
    taken out of `waiting`, and the quest back in play once nothing is left to ask. A yes to a sign-off
    closes the quest (or applies the proposed status)."""
    from datetime import date
    from . import audit, config as cfgmod, store

    def apply(q) -> None:
        qs = parse(q.waiting)
        if not 0 <= n < len(qs):
            raise KeyError(f"no question {n} on {q.ref}")
        a = qs[n]
        who = (cfg.human if cfg else "") or "game master"
        q.log.append(f"{date.today().isoformat()} ({who}) answered: {a.text} -> {choice}")
        yes = choice.strip().lower() in ("y", "yes", "ok", "approve", "approved")
        if q.waiting.lower().startswith("sign-off") and yes:
            q.status, q.waiting = "done", ""
            return
        if q.waiting.lower().startswith("proposed status") and yes:
            proposed = q.waiting.split("to ", 1)[-1].split(":", 1)[0].strip()
            if proposed in cfgmod.STATUS_KEYS:
                q.status = proposed
            q.waiting = ""
            return
        left = without(q.waiting, a)
        if not parse(left) and (not left or left.startswith(("If ", "(", "First ", "Then "))):
            if left:
                q.log.append(f"{date.today().isoformat()}: note that came with the question: {left}")
            left = ""
        q.waiting = left
        if not left and q.status == "waiting":
            q.status = "active"
    with audit.because(f"answered: {choice}", by):
        return store.update(ref, apply, cfg)
