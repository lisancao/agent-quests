"""Which faction / arc / quest a session serves, from cheap deterministic signals.

Folder evidence (cwd, files touched) outweighs words. Keywords use whole-word matching.
The scribe's LLM pass refines this after the session; orientation only needs a good first guess.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from . import config as cfgmod, store

PATH_WEIGHT = 3.0
KEYWORD_WEIGHT = 1.5
STRONG = 2.5   # a folder hit, or two keywords, counts as a confident match


@dataclass
class Hit:
    faction: str
    arc: str = ""
    quest: str = ""     # ref
    score: float = 0.0
    why: str = ""


def _under(path: str, roots: list[str]) -> bool:
    return any(path == r or path.startswith(r.rstrip("/") + "/") for r in roots)


def _kw_hits(text: str, kws: list[str]) -> list[str]:
    low = text.lower()
    return [k for k in kws if re.search(rf"(?<![\w-]){re.escape(k)}(?![\w-])", low)]


def _score(match: cfgmod.Match, cwd: str, paths: list[str], text: str) -> tuple[float, str]:
    score, why = 0.0, []
    if match.paths:
        if cwd and _under(cwd, match.paths):
            score += PATH_WEIGHT
            why.append("working in its folder")
        touched = sum(_under(p, match.paths) for p in paths)
        if touched:
            score += min(PATH_WEIGHT, touched * 0.75)
            why.append(f"touched {touched} of its files")
    kws = _kw_hits(text, match.keywords) if text and match.keywords else []
    if kws:
        score += KEYWORD_WEIGHT * min(len(kws), 3)
        why.append("mentions " + ", ".join(kws[:3]))
    return score, "; ".join(why)


def best(cfg: cfgmod.Config, cwd: str = "", paths: list[str] | None = None, text: str = "",
         include_private: bool = True) -> Hit | None:
    """The single best faction (+arc, +quest) for these signals, or None."""
    paths = [str(Path(os.path.expanduser(p)).resolve()) for p in (paths or [])]
    cwd = str(Path(os.path.expanduser(cwd)).resolve()) if cwd else ""
    candidates: list[Hit] = []
    for f in cfg.factions:
        if f.private and not include_private:
            continue
        fs, fwhy = _score(f.match, cwd, paths, text)
        arc_hits = []
        for a in f.arcs:
            s, w = _score(a.match, cwd, paths, text)
            if s:
                arc_hits.append(Hit(f.id, a.id, "", fs + s, w or fwhy))
        if arc_hits:
            candidates.extend(arc_hits)
        elif fs:
            candidates.append(Hit(f.id, "", "", fs, fwhy))
    # Quest-level match rules refine further.
    for q in store.load(cfg, include_private=include_private):
        if q.status == "done" or not (q.match_paths or q.match_keywords):
            continue
        m = cfgmod.Match.from_raw({"paths": cfgmod._split_list(q.match_paths),
                                   "keywords": cfgmod._split_list(q.match_keywords)})
        s, w = _score(m, cwd, paths, text)
        if s:
            candidates.append(Hit(q.faction, q.arc, q.ref, s + 1.0, w))
    if not candidates:
        return None
    return max(candidates, key=lambda h: h.score)
