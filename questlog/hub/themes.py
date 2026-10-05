"""Journal themes: colors, glyphs and words. Pick one with [journal] theme = "codex" | "parchment";
override any color with [hub.theme] in questlog.toml."""
from __future__ import annotations

THEMES: dict[str, dict] = {
    # A ship's log / codex: dark panels, neon accents, crisp glyphs.
    "codex": {
        "colors": {
            "bg": "#05060a", "panel": "#0c0e14", "line": "#1f2430", "select": "#2a2540",
            "text": "#c7cbd8", "dim": "#7a849a", "bright": "#f2f3f8",
            "accent": "#e867ea", "accent2": "#48f2fb", "ok": "#56d6a8", "warn": "#f2c86b",
            "bad": "#f0577a", "gold": "#f2c86b",
        },
        "glyphs": {"main": "◆", "side": "◇", "done_section": "✓", "obj_done": "◆", "obj_open": "◇",
                   "current": "▸", "pip_on": "▰", "pip_off": "▱", "reward": "◈", "new": "◂ NEW",
                   "rule": "─", "bullet": "·", "star": "★"},
        "labels": {"title": "QUEST JOURNAL", "journal": "JOURNAL", "character": "CHARACTER", "codex": "CODEX",
                   "chronicle": "CHRONICLE", "party": "PARTY", "commons": "COMMONS", "rumours": "RUMOURS",
                   "main": "MAIN QUESTS", "side": "SIDE QUESTS", "completed": "COMPLETED", "allies": "ALLIES",
                   "objectives": "OBJECTIVES", "notes": "LOG NOTES", "entries": "JOURNAL ENTRIES",
                   "reward": "REWARD", "updated": "QUEST UPDATED", "complete": "QUEST COMPLETE",
                   "levelup": "LEVEL UP", "lore": "FACTIONS"},
        "upper": True,
        "border": "heavy",
    },
    # A field journal: parchment, ink, oxblood and verdigris.
    "parchment": {
        "colors": {
            "bg": "#efe3c8", "panel": "#e6d6b2", "line": "#b89f74", "select": "#d9c393",
            "text": "#3b2f22", "dim": "#7a6a52", "bright": "#1f170f",
            "accent": "#8b2e1f", "accent2": "#2f5d50", "ok": "#4f6b2f", "warn": "#a8741a",
            "bad": "#8b2e1f", "gold": "#9a6a12",
        },
        "glyphs": {"main": "❧", "side": "✦", "done_section": "⚜", "obj_done": "✔", "obj_open": "○",
                   "current": "➤", "pip_on": "●", "pip_off": "○", "reward": "⚜", "new": "· new ·",
                   "rule": "~", "bullet": "•", "star": "✶"},
        "labels": {"title": "Quest Journal", "journal": "Journal", "character": "Character", "codex": "Lore",
                   "chronicle": "Deeds", "party": "Companions", "commons": "The Commons", "rumours": "Rumours",
                   "main": "Main Quests", "side": "Side Quests", "completed": "Completed", "allies": "Allies",
                   "objectives": "Objectives", "notes": "Notes", "entries": "Journal Entries",
                   "reward": "Reward", "updated": "Quest Updated", "complete": "Quest Complete",
                   "levelup": "Level Up", "lore": "Factions"},
        "upper": False,
        "border": "double",
    },
}


def get(name: str, overrides: dict[str, str] | None = None) -> dict:
    base = THEMES.get(name) or THEMES["codex"]
    return {**base, "colors": {**base["colors"], **(overrides or {})}}
