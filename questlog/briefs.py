"""The creation brief: a few questions asked when an arc or quest is born (Heilmeier / mini-PRD style).

Only the required ones are asked up front (by default two per level), because they're what keeps an
agent on track: what it's for, and how you'll know it's done. The optional ones can be answered later.
"""
from __future__ import annotations

from . import config as cfgmod


def questions(cfg: cfgmod.Config, level: str) -> dict:
    b = cfg.briefs[level]
    return {"required": [{"key": k, "question": q} for k, q in b["required"]],
            "optional": [{"key": k, "question": q} for k, q in b["optional"]]}


def missing(cfg: cfgmod.Config, level: str, answers: dict | None, **given: str) -> list[dict]:
    """Required questions with no answer yet. `given` lets direct fields (done=, goal=...) count as answers."""
    answers = {**{k: v for k, v in given.items() if v}, **(answers or {})}
    return [{"key": k, "question": q} for k, q in cfg.briefs[level]["required"] if not str(answers.get(k, "")).strip()]


def needs_brief_response(cfg: cfgmod.Config, level: str, missing_qs: list[dict]) -> dict:
    """What creation returns instead of failing: ask these, then call again with brief={key: answer}."""
    return {
        "needs_brief": True,
        "level": level,
        "questions": missing_qs,
        "optional_questions": questions(cfg, level)["optional"],
        "how": (f"Ask {cfg.human} these (briefly; one or two sentences each is plenty), then call again with "
                "brief={key: answer}. Optional questions can be skipped now and answered later."),
    }
