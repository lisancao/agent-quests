"""Claude Code adapter: find a session's transcript and condense it for the scribe."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

PROJECTS = Path.home() / ".claude" / "projects"


def transcript_path(session_id: str) -> Path | None:
    hits = [p for p in PROJECTS.glob(f"*/{session_id}*.jsonl") if "subagents" not in p.parts]
    return hits[0] if len(hits) == 1 else None


def _text(content) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text" and isinstance(c.get("text"), str):
                return c["text"].strip()
    return ""


def _short(s: str, n: int) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def condense(path: Path, budget: int = 14000) -> str:
    """Opening ask, files edited, and as much of the end as fits: the end is where decisions land."""
    turns: list[tuple[str, str]] = []
    edited: list[str] = []
    cwd = ""
    with path.open("rb") as f:
        for raw in f:
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            cwd = cwd or (msg.get("cwd") if isinstance(msg.get("cwd"), str) else "")
            t = msg.get("type")
            content = (msg.get("message") or {}).get("content")
            if t == "user":
                if msg.get("isMeta") or msg.get("isCompactSummary"):
                    continue
                text = _text(content)
                if text and not text.startswith(("[Request interrupted", "<")):
                    turns.append(("USER", text))
            elif t == "assistant" and isinstance(content, list):
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text" and b.get("text", "").strip():
                        turns.append(("AGENT", b["text"].strip()))
                    elif b.get("type") == "tool_use" and b.get("name") in ("Edit", "Write", "NotebookEdit"):
                        fp = (b.get("input") or {}).get("file_path")
                        if fp and fp not in edited:
                            edited.append(fp)
    home = str(Path.home())
    head = [f"session {path.stem} · cwd {cwd or '?'} · {len(turns)} turns · last active "
            f"{datetime.fromtimestamp(path.stat().st_mtime):%Y-%m-%d %H:%M}"]
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


def meta(path: Path) -> dict:
    """cwd, start time and opening prompt of a session (reads only the head of the file)."""
    out = {"cwd": "", "started": 0.0, "first_prompt": "", "entrypoint": ""}
    with path.open("rb") as f:
        for i, raw in enumerate(f):
            if i > 400 or (out["cwd"] and out["started"] and out["first_prompt"] and out["entrypoint"]):
                break
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if not out["cwd"] and isinstance(msg.get("cwd"), str):
                out["cwd"] = msg["cwd"]
            if not out["entrypoint"] and isinstance(msg.get("entrypoint"), str):
                out["entrypoint"] = msg["entrypoint"]
            ts = msg.get("timestamp")
            if not out["started"] and isinstance(ts, str):
                try:
                    out["started"] = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                except ValueError:
                    pass
            if not out["first_prompt"] and msg.get("type") == "user" and not msg.get("isMeta"):
                t = _text((msg.get("message") or {}).get("content"))
                if t and not t.startswith(("<", "[Request interrupted")):
                    out["first_prompt"] = _short(t, 200)
    return out
