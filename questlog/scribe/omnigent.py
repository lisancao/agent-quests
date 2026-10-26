"""Omnigent adapter: load a conversation through the `omnigent` CLI and condense it for the scribe.

`omnigent session export --id conv_...` writes JSONL: a `session_meta` line (title, workspace, created_at,
updated_at, ...) and then one `item` line per conversation item (messages, function calls, ...), in order.
It talks to the server with the host's existing login; questlog adds no secrets and reads no token files.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from .. import bindings, config as cfgmod
from .claude_code import _short

PREFIX = "conv_"
BARE_ID = re.compile(r"[0-9a-f]{32}")   # how this server's sessions look; Claude Code ids are dashed UUIDs
WEB = "https://omnigent.systemsnull.net/c/"
EDIT_TOOLS = ("edit", "write", "sys_os_edit", "sys_os_write", "notebookedit", "apply_patch")

Exporter = Callable[[str], str]   # conv id -> export JSONL text


def is_omnigent(session_id: str) -> bool:
    """`conv_...` ids, and the bare 32-hex ids an Omnigent server hands its agents (never a dashed UUID)."""
    return session_id.startswith(PREFIX) or bool(BARE_ID.fullmatch(session_id))


def link(conv_id: str) -> str:
    return WEB + conv_id


def cli_export(conv_id: str) -> str:
    """The export JSONL for a conversation, via the omnigent CLI (raises RuntimeError when it fails).
    A `conv_` id the server doesn't know is retried bare (servers differ in which form they accept)."""
    try:
        return _cli_export(conv_id)
    except RuntimeError:
        if not conv_id.startswith(PREFIX):
            raise
        return _cli_export(conv_id[len(PREFIX):])


def _cli_export(conv_id: str) -> str:
    with tempfile.TemporaryDirectory(prefix="questlog-omnigent-") as d:
        out = Path(d) / "export.jsonl"
        try:
            res = subprocess.run(["omnigent", "session", "export", "--id", conv_id, "--output", str(out)],
                                 capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise RuntimeError(f"omnigent export failed: {e}") from e
        if res.returncode != 0 or not out.exists():
            raise RuntimeError(f"omnigent export failed: {(res.stderr or res.stdout).strip()[:200]}")
        return out.read_text()


def parse(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def load(conv_id: str, export: Exporter | None = None) -> list[dict]:
    return parse((export or cli_export)(conv_id))


def _session(records: list[dict]) -> dict:
    return next((r for r in records if r.get("record_type") == "session_meta"), {})


def _items(records: list[dict]) -> list[dict]:
    return [r for r in records if r.get("record_type") == "item"]


def _text(content) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [c.get("text", "") for c in content
                 if isinstance(c, dict) and c.get("type") in ("input_text", "output_text", "text")
                 and isinstance(c.get("text"), str)]
        return "\n".join(p.strip() for p in parts if p.strip())
    return ""


def _ts(v) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0
    return 0.0


def activity(records: list[dict]) -> float:
    """When the conversation last moved: the session's updated_at, or its newest item."""
    times = [_ts(_session(records).get("updated_at"))] + [_ts(i.get("created_at")) for i in _items(records)]
    return max(times, default=0.0)


def size(records: list[dict]) -> int:
    """Bytes of conversation text: the scribe's measure of how much there is to read."""
    return sum(len(_text(i.get("content"))) + len(i.get("arguments") or "") for i in _items(records))


def _turns(records: list[dict]) -> tuple[list[tuple[str, str]], list[str]]:
    turns: list[tuple[str, str]] = []
    edited: list[str] = []
    for it in _items(records):
        kind = it.get("type")
        if kind == "message":
            if it.get("is_meta"):
                continue
            text = _text(it.get("content"))
            if not text:
                continue
            if it.get("role") == "user":
                if not text.startswith(("[Request interrupted", "<")):
                    turns.append(("USER", text))
            elif it.get("role") == "assistant":
                turns.append(("AGENT", text))
        elif kind == "function_call" and str(it.get("name", "")).split(".")[-1].lower() in EDIT_TOOLS:
            try:
                args = json.loads(it.get("arguments") or "{}")
            except ValueError:
                args = {}
            fp = args.get("file_path") or args.get("path") if isinstance(args, dict) else None
            if isinstance(fp, str) and fp and fp not in edited:
                edited.append(fp)
    return turns, edited


def meta(records: list[dict]) -> dict:
    """cwd, start time and opening prompt, in the shape claude_code.meta returns (plus title and updated)."""
    s = _session(records)
    turns, _ = _turns(records)
    first = next((t for who, t in turns if who == "USER"), "")
    return {"cwd": s.get("workspace") or "", "started": _ts(s.get("created_at")), "first_prompt": _short(first, 200),
            "entrypoint": "omnigent", "title": s.get("title") or "", "updated": activity(records)}


def condense(records: list[dict], budget: int = 14000) -> str:
    """Opening ask, files edited, and as much of the end as fits, like claude_code.condense."""
    s = _session(records)
    conv_id = s.get("id") or "?"
    turns, edited = _turns(records)
    home = str(Path.home())
    last = activity(records)
    head = [f"session {conv_id} · cwd {s.get('workspace') or '?'} · {len(turns)} turns · last active "
            f"{datetime.fromtimestamp(last):%Y-%m-%d %H:%M}" if last else
            f"session {conv_id} · cwd {s.get('workspace') or '?'} · {len(turns)} turns"]
    if s.get("title"):
        head.append(f"title: {s['title']}")
    if edited:
        head.append("files edited: " + ", ".join(p.replace(home, "~") for p in edited[:40]))
    first = [f"{who}: {_short(txt, 1200)}" for who, txt in turns[:2]]
    used = sum(map(len, first)) + sum(map(len, head))
    tail: list[str] = []
    for who, txt in reversed(turns[2:]):
        entry = f"{who}: {_short(txt, 900)}"
        if used + len(entry) > budget:
            break
        tail.append(entry)
        used += len(entry)
    tail.reverse()
    gap = len(turns) - 2 - len(tail)
    body = first + ([f"[… {gap} turns omitted …]"] if gap > 0 else []) + tail
    return "\n".join(head) + "\n\n" + "\n\n".join(body)


# --- the timer: scribe Omnigent sessions once they go quiet --------------------------

def _state_file(conv_id: str) -> Path:
    from . import core
    return core.STATE / f"{conv_id}.json"


def scribed_at(conv_id: str) -> float:
    """The activity time the scribe last recorded this conversation at (0 if never)."""
    try:
        return float(json.loads(_state_file(conv_id).read_text()).get("activity", 0))
    except (OSError, ValueError, TypeError):
        return 0.0


def scribe_idle(idle_minutes: float = 15, *, export: Exporter | None = None, cfg: cfgmod.Config | None = None,
                now: float | None = None, dry_run: bool = False, run=None) -> list[str]:
    """Scribe every bound Omnigent conversation that has been quiet `idle_minutes` and has moved since it
    was last scribed. Returns one line per conversation looked at."""
    from . import core
    run = run or core.run
    now = time.time() if now is None else now
    out = []
    for conv_id, rec in sorted(bindings._load().items()):
        if not is_omnigent(conv_id):
            continue
        try:
            records = load(conv_id, export)
        except RuntimeError as e:
            out.append(f"{conv_id} {e}")
            continue
        last = activity(records)
        if last and last <= scribed_at(conv_id):
            out.append(f"{conv_id} already scribed")
            continue
        if last and now - last < idle_minutes * 60:
            out.append(f"{conv_id} still active ({(now - last) / 60:.0f} min idle)")
            continue
        if dry_run:
            out.append(f"{conv_id} would scribe -> {rec.get('quest')}")
            continue
        out.append(f"{conv_id} {run(conv_id, rec.get('quest'), cfg=cfg, force=True, records=records)}")
    for line in out:
        core._log(f"omnigent {line}")
    return out
