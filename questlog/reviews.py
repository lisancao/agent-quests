"""Reviews: who checked whose work, and whether it passed.

<root>/.questlog/reviews.jsonl   one line per review, e.g.
    {"ts": ..., "ref": "overlord/lair/shark-tank", "pr": "me/lair#12", "implementer": "claude",
     "implementer_vendor": "anthropic", "reviewer": "openai/codex", "reviewer_vendor": "openai",
     "verdict": "pass", "notes": "..."}

A quest whose review rule is "cross-vendor" (store.effective) can't be closed by an agent until at least one
`pass` comes from a reviewer whose vendor family differs from the implementer's; otherwise closing becomes a
sign-off request for the game master.
"""
from __future__ import annotations

import json
import re
import time

from . import config as cfgmod, store

VERDICTS = ("pass", "fail")
FILE = "reviews.jsonl"

# Model or product names that give away their vendor, checked in order against the lowercased name.
FAMILIES = (
    ("anthropic", r"anthropic|claude|opus|sonnet|haiku|fable"),
    ("openai", r"openai|codex|chatgpt|gpt|^o[1-9]\b|^o[1-9]-"),
    ("google", r"google|gemini|gemma|bard"),
    ("meta", r"meta-llama|llama|\bmeta\b"),
    ("mistral", r"mistral|mixtral|codestral|devstral"),
    ("alibaba", r"qwen|alibaba"),
    ("deepseek", r"deepseek"),
    ("xai", r"x-ai|xai|grok"),
    ("moonshot", r"moonshot|kimi"),
    ("zhipu", r"zhipu|z-ai|glm"),
)


def vendor(name: str) -> str:
    """The vendor family behind an agent or model name, e.g. "claude" -> anthropic, "openai/codex" -> openai,
    "openrouter:google/gemini-2.5-pro" -> google, "local:qwen3-coder" -> alibaba. Routers and hosts
    (openrouter:, local:) are looked through to the model they carry; an unknown name is its own family."""
    n = (name or "").strip().lower()
    for prefix in ("openrouter:", "local:", "ollama:", "bedrock:", "vertex:", "azure:"):
        if n.startswith(prefix):
            n = n[len(prefix):]
            break
    for family, pattern in FAMILIES:
        if re.search(pattern, n):
            return family
    return re.split(r"[/:@]", n, maxsplit=1)[0] or "unknown"


def record(cfg: cfgmod.Config, ref: str, *, pr: str, implementer: str, reviewer: str, verdict: str,
           notes: str = "") -> dict:
    """Store a review and log it on the quest. Raises KeyError (no such quest) or ValueError (bad verdict)."""
    verdict = verdict.strip().lower()
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {VERDICTS}")
    q = store.find(ref, cfg)
    if q is None:
        raise KeyError(f"no single quest matches {ref!r}")
    row = {"ts": time.time(), "ref": q.ref, "pr": pr.strip(), "implementer": implementer.strip(),
           "implementer_vendor": vendor(implementer), "reviewer": reviewer.strip(),
           "reviewer_vendor": vendor(reviewer), "verdict": verdict, "notes": " ".join(notes.split())}
    f = cfg.meta_dir / FILE
    cfg.meta_dir.mkdir(parents=True, exist_ok=True)
    with store.locked(f):
        with f.open("a") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    from datetime import date
    line = (f"{date.today().isoformat()}: review {verdict} · {row['pr'] or '-'} · {row['implementer']} "
            f"({row['implementer_vendor']}) reviewed by {row['reviewer']} ({row['reviewer_vendor']})"
            + (f" · {row['notes'][:160]}" if row["notes"] else ""))
    store.update(q.ref, lambda x: x.log.append(line), cfg)
    return row


def all_reviews(cfg: cfgmod.Config) -> list[dict]:
    f = cfg.meta_dir / FILE
    if not f.exists():
        return []
    out = []
    for line in f.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def for_quest(cfg: cfgmod.Config, ref: str) -> list[dict]:
    """Reviews of one quest, oldest first."""
    return [r for r in all_reviews(cfg) if r.get("ref") == ref]


def cross_vendor_pass(rows: list[dict]) -> dict | None:
    """The first passing review whose reviewer's vendor differs from the implementer's."""
    return next((r for r in rows if r.get("verdict") == "pass"
                 and vendor(r.get("reviewer", "")) != vendor(r.get("implementer", ""))), None)


def block_reason(rows: list[dict]) -> str:
    """"" when a cross-vendor pass exists, else why the quest can't close yet."""
    if cross_vendor_pass(rows):
        return ""
    if not rows:
        return "cross-vendor review required and no review is recorded yet (record one with quest_review)"
    passes = [r for r in rows if r.get("verdict") == "pass"]
    if passes:
        r = passes[-1]
        return (f"cross-vendor review required: the only passes are same-vendor "
                f"({r.get('reviewer')} reviewing {r.get('implementer')}, both {vendor(r.get('reviewer', ''))})")
    return "cross-vendor review required: no review has passed yet (latest verdict: fail)"
