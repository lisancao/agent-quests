"""The audit trail: every write to a quest, arc or faction file, with who made it, why, and what was there
before, so any edit (Puck's reorganizing, the scribe's save states, an agent's update) can be undone.

Entries go to <root>/.questlog/audit.jsonl. A reason comes from the caller: wrap a write in
`with audit.because("merged duplicate of X"):`, or it falls back to the log line written with it.
`undo(cfg, id)` restores the prior text (or removes a file the edit created), and is itself audited.
"""
from __future__ import annotations

import contextvars
import json
import os
import secrets
import time
from contextlib import contextmanager
from pathlib import Path

from . import config as cfgmod

_REASON: contextvars.ContextVar[str] = contextvars.ContextVar("questlog_audit_reason", default="")
_BY: contextvars.ContextVar[str] = contextvars.ContextVar("questlog_audit_by", default="")


@contextmanager
def because(reason: str, by: str = ""):
    """Attach a reason (and the acting agent, when the process doesn't know it) to writes in this block."""
    t1, t2 = _REASON.set(reason or ""), _BY.set(by or "")
    try:
        yield
    finally:
        _REASON.reset(t1)
        _BY.reset(t2)


def _who() -> str:
    return _BY.get() or os.environ.get("QUESTLOG_AGENT", "")


def _file(cfg: cfgmod.Config) -> Path:
    cfg.meta_dir.mkdir(parents=True, exist_ok=True)
    return cfg.meta_dir / "audit.jsonl"


def _fields(text: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if not text or not text.startswith("---\n"):
        return out
    for line in text[4:].split("\n---", 1)[0].splitlines():
        k, sep, v = line.partition(":")
        if sep:
            out[k.strip()] = v.strip()
    return out


def changed(prior: str | None, new: str) -> list[str]:
    """Frontmatter keys that differ, plus 'body' if the rest changed."""
    a, b = _fields(prior), _fields(new)
    keys = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k) and k != "updated")
    body = lambda t: (t or "").split("\n---\n", 1)[-1]
    if prior is not None and body(prior) != body(new):
        keys.append("body")
    return keys


def record(cfg: cfgmod.Config, path: Path, prior: str | None, new: str, *, ref: str = "", reason: str = "",
           kind: str = "") -> dict | None:
    if prior == new:
        return None
    entry = {"id": secrets.token_hex(4), "ts": time.time(), "by": _who(),
             "kind": kind or ("create" if prior is None else "edit"), "ref": ref,
             "path": str(path.relative_to(cfg.root)) if path.is_relative_to(cfg.root) else str(path),
             "reason": (_REASON.get() or reason)[:240], "changed": changed(prior, new),
             "prior": prior, "new": new}
    with _file(cfg).open("a") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def entries(cfg: cfgmod.Config) -> list[dict]:
    f = cfg.meta_dir / "audit.jsonl"
    if not f.exists():
        return []
    out = []
    for line in f.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def recent(cfg: cfgmod.Config, limit: int = 20, by: str = "", ref: str = "") -> list[dict]:
    """Newest first, without the file bodies; undone entries are marked."""
    rows = entries(cfg)
    undone = {e["undoes"] for e in rows if e.get("undoes")}
    out = []
    for e in reversed(rows):
        if by and e.get("by") != by or ref and ref not in (e.get("ref") or e.get("path", "")):
            continue
        out.append({k: v for k, v in e.items() if k not in ("prior", "new")} | {"undone": e["id"] in undone})
        if len(out) >= limit:
            break
    return out


def undo(cfg: cfgmod.Config, entry_id: str = "", *, by: str = "", force: bool = False) -> dict:
    """Revert one audited write: the given id, or the latest not-yet-undone one (by `by` if given).
    Refuses if the file changed since that write (an undo would silently drop later edits) unless force."""
    from . import store
    rows = entries(cfg)
    undone = {e["undoes"] for e in rows if e.get("undoes")}
    cands = [e for e in rows if not e.get("undoes") and e["id"] not in undone and (not by or e.get("by") == by)]
    if entry_id:
        cands = [e for e in cands if e["id"].startswith(entry_id)]
    if not cands:
        return {"error": "nothing to undo" + (f" matching {entry_id!r}" if entry_id else "")}
    e = cands[-1]
    path = Path(e["path"]) if os.path.isabs(e["path"]) else cfg.root / e["path"]
    with store.locked(path):
        current = path.read_text() if path.exists() else None
        if current != e["new"] and not force:
            later = [x["id"] for x in rows if x["path"] == e["path"] and x["ts"] > e["ts"] and x["id"] not in undone]
            return {"error": f"{e['path']} changed after {e['id']}; undo the later edits first ({', '.join(later)}) "
                             "or pass force"}
        if e["prior"] is None:
            path.unlink(missing_ok=True)
            if path.name in ("ARC.md", "FACTION.md") and path.parent.is_dir() and not any(path.parent.iterdir()):
                path.parent.rmdir()   # the folder came with the arc / faction
        else:
            store._atomic_write(path, e["prior"])
    rec = {"id": secrets.token_hex(4), "ts": time.time(), "by": _who(),
           "kind": "undo", "ref": e.get("ref", ""), "path": e["path"], "reason": (f"undo {e['id']}" + (f": {e['reason']}" if e.get("reason") else ""))[:240],
           "changed": e.get("changed", []), "prior": current, "new": e["prior"], "undoes": e["id"]}
    with _file(cfg).open("a") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if e.get("ref"):
        from . import events
        events.emit(cfg, "reverted", ref=e["ref"], summary=f"Reverted {e['kind']} by {e.get('by') or 'someone'}"
                    + (f" ({e['reason'][:100]})" if e.get("reason") else ""))
    return {"undone": e["id"], "path": e["path"], "ref": e.get("ref", ""), "kind": e["kind"],
            "restored": "removed (it was created by that edit)" if e["prior"] is None else "prior version"}
