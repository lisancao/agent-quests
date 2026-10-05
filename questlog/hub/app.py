"""questlog hub: the quest journal.

Tabs: Character (level, reputation, achievements, loot) · Journal (factions > arcs > quests) ·
Deeds (what every session accomplished) · Party (recent sessions by goal) · Suggestions.
Everything is read from the quest files and the ledger; refreshes every 10 seconds.
"""
from __future__ import annotations

import shlex
import subprocess
import time
from datetime import datetime

from rich.console import Group
from rich.table import Table
from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Markdown, Static, TabbedContent, TabPane, Tree

from .. import commons, config as cfgmod, ledger, rewards, store, views

DEFAULT_THEME = {
    "bg": "#0b0d12", "panel": "#12151c", "line": "#262b36", "text": "#cdd3de", "dim": "#7c8597",
    "bright": "#f2f4f8", "accent": "#c678dd", "accent2": "#56b6c2", "ok": "#98c379", "warn": "#e5c07b",
    "bad": "#e06c75", "gold": "#e5c07b", "select": "#2c3140",
}
STATUS = {"active": ("◆", "ok"), "blocked": ("✖", "bad"), "waiting": ("⏳", "warn"), "parked": ("◇", "dim"),
          "done": ("✔", "accent2")}

CSS = """
Screen { background: $q-bg; color: $q-text; }
TabbedContent, TabPane { background: $q-bg; }
Tabs { background: $q-panel; }
Tab { color: $q-dim; }
Tab.-active { color: $q-bright; text-style: bold; }
Underline > .underline--bar { color: $q-accent; background: $q-line; }
#character { padding: 1 2; }
#commons-pane { padding: 1 2; }
#journal-row { height: 1fr; }
#tree { width: 45%; background: $q-panel; border: round $q-line; padding: 0 1; }
#tree:focus { border: round $q-accent; }
#detail { width: 1fr; border: round $q-line; background: $q-bg; }
#detail-md { background: $q-bg; padding: 0 1; }
DataTable { background: $q-bg; height: 1fr; }
DataTable > .datatable--header { background: $q-panel; color: $q-accent; text-style: bold; }
DataTable > .datatable--cursor { background: $q-select; color: $q-bright; }
Tree > .tree--cursor { background: $q-select; color: $q-bright; }
Tree > .tree--guides { color: $q-line; }
MarkdownH1, MarkdownH2 { color: $q-accent; }
MarkdownH3 { color: $q-accent2; }
Footer { background: $q-panel; }
#seed { width: 90; height: auto; max-height: 80%; border: round $q-accent; background: $q-panel; padding: 1 2; }
SeedModal { align: center middle; }
"""


def _bar(into: int, span: int, width: int, color: str, empty: str) -> Text:
    t = Text()
    filled = width if span <= 0 else int(width * into / max(span, 1))
    t.append("█" * filled, style=color)
    t.append("░" * (width - filled), style=empty)
    return t


class SeedModal(ModalScreen[None]):
    BINDINGS = [Binding("escape,q,enter", "dismiss(None)", "close")]

    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="seed"):
            yield Static(Text("Opening message for a work session (copy it into your agent):\n", style="bold"))
            yield Static(self.text)


class Hub(App):
    TITLE = "questlog"
    CSS = CSS
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        Binding("1", "tab('character')", "character"),
        Binding("2", "tab('journal')", "journal"),
        Binding("3", "tab('deeds')", "deeds"),
        Binding("4", "tab('party')", "party"),
        Binding("5", "tab('suggestions')", "suggestions"),
        Binding("6", "tab('commons')", "commons"),
        Binding("p", "toggle_private", "private"),
        Binding("a", "accept", "accept", show=False),
        Binding("x", "dismiss_suggestion", "dismiss", show=False),
        Binding("r", "reload", "refresh"),
        Binding("q", "quit", "quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.cfg = cfgmod.load()
        self.theme_colors = {**DEFAULT_THEME, **self.cfg.hub_theme}
        self.show_private = False
        self._quests: dict[str, store.Quest] = {}
        self._suggestions: list[dict] = []

    def get_css_variables(self) -> dict[str, str]:
        base = super().get_css_variables()
        return {**base, **{f"q-{k}": v for k, v in getattr(self, "theme_colors", DEFAULT_THEME).items()}}

    def c(self, key: str) -> str:
        return self.theme_colors.get(key, DEFAULT_THEME[key])

    def compose(self) -> ComposeResult:
        with TabbedContent(initial="character", id="tabs"):
            with TabPane("Character", id="character"):
                yield VerticalScroll(Static(id="sheet"), id="character")
            with TabPane("Journal", id="journal"):
                with Horizontal(id="journal-row"):
                    yield Tree("quests", id="tree")
                    with VerticalScroll(id="detail"):
                        yield Markdown("", id="detail-md")
            with TabPane("Deeds", id="deeds"):
                yield DataTable(id="deeds-table", cursor_type="row")
            with TabPane("Party", id="party"):
                yield DataTable(id="party-table", cursor_type="row")
            with TabPane("Suggestions", id="suggestions"):
                yield DataTable(id="sugg-table", cursor_type="row")
            with TabPane("Commons", id="commons"):
                yield VerticalScroll(Static(id="commons-view"), id="commons-pane")
        yield Footer()

    def on_mount(self) -> None:
        self.reload()
        self.set_interval(10, self.reload)

    # --- data ---------------------------------------------------------------------

    def action_reload(self) -> None:
        self.reload()

    def reload(self) -> None:
        self.cfg = cfgmod.load()
        self.render_sheet()
        self.render_tree()
        self.render_deeds()
        self.render_party()
        self.render_suggestions()
        self.render_commons()

    def action_tab(self, tab: str) -> None:
        self.query_one("#tabs", TabbedContent).active = tab

    def action_toggle_private(self) -> None:
        self.show_private = not self.show_private
        self.reload()
        self.notify("showing private factions" if self.show_private else "private factions hidden", timeout=2)

    # --- character ------------------------------------------------------------------

    def render_sheet(self) -> None:
        sh = rewards.sheet(self.cfg, include_private=self.show_private)
        head = Text()
        head.append(f"{self.cfg.human}", style=f"bold {self.c('bright')}")
        head.append(f"   level {sh.level}\n", style=f"bold {self.c('gold')}")
        head.append_text(_bar(sh.into_level, sh.level_span, 40, self.c("gold"), self.c("line")))
        head.append(f"  {sh.into_level}/{sh.level_span} xp to level {sh.level + 1}   ", style=self.c("dim"))
        head.append(f"total {sh.xp} xp\n", style=self.c("text"))
        head.append(f"{sh.deeds_total} deeds · {sh.quests_done} quests done · {sh.arcs_done} arcs complete · "
                    f"{sh.sessions} sessions recorded\n", style=self.c("dim"))

        rep = Table.grid(padding=(0, 2))
        rep.add_column(); rep.add_column(); rep.add_column(); rep.add_column(justify="right"); rep.add_column()
        for r in sh.reputation:
            rep.add_row(Text(r.name, style=f"bold {self.c('accent')}"), Text(r.tier, style=self.c("gold")),
                        _bar(r.into_tier, r.tier_span, 24, self.c("accent2"), self.c("line")),
                        Text(f"{r.xp} xp", style=self.c("text")),
                        Text(f"→ {r.next_tier}" if r.next_tier else "max", style=self.c("dim")))
        ach = Text()
        if sh.achievements:
            for a in sh.achievements:
                ach.append("★ ", style=self.c("gold"))
                ach.append(a["name"], style=f"bold {self.c('bright')}")
                ach.append(f"  {a['description']}\n", style=self.c("dim"))
        else:
            ach.append("None yet. Your first deed unlocks one.\n", style=self.c("dim"))
        inv = Text()
        for i in sh.inventory:
            inv.append("◈ ", style=self.c("accent"))
            inv.append(f"{i['reward']}", style=self.c("bright"))
            inv.append(f"  from {i['quest']}\n", style=self.c("dim"))
        if not sh.inventory:
            inv.append("Set a `reward` on a quest and it lands here when you finish.\n", style=self.c("dim"))
        title = lambda s: Text(f"\n{s}\n", style=f"bold {self.c('accent2')}")  # noqa: E731
        self.query_one("#sheet", Static).update(Group(head, title("REPUTATION"), rep, title("ACHIEVEMENTS"), ach,
                                                      title("INVENTORY"), inv))

    # --- journal --------------------------------------------------------------------

    def render_tree(self) -> None:
        tree = self.query_one("#tree", Tree)
        expanded = {n.data.get("key") for n in tree.root.children if n.is_expanded and isinstance(n.data, dict)}
        first = not tree.root.children
        tree.clear()
        tree.root.expand()
        tree.show_root = False
        qs = store.load(self.cfg, include_private=self.show_private)
        self._quests = {q.ref: q for q in qs}
        for f in self.cfg.factions:
            if f.private and not self.show_private:
                continue
            fq = [q for q in qs if q.faction == f.id]
            done = sum(q.status == "done" for q in fq)
            label = Text()
            label.append(f.name, style=f"bold {self.c('accent')}")
            label.append(f"  {done}/{len(fq)}", style=self.c("dim"))
            fnode = tree.root.add(label, data={"key": f"f:{f.id}", "faction": f.id})
            for aid in [a.id for a in f.arcs] + [""]:
                aq = [q for q in fq if q.arc == aid]
                if not aid and not aq:
                    continue
                parent = fnode
                if aid:
                    a = f.arc(aid)
                    d, tot = sum(q.status == "done" for q in aq), len(aq)
                    al = Text()
                    al.append(a.name if a else aid, style=self.c("accent2"))
                    al.append("  ")
                    al.append_text(_bar(d, tot or 1, 8, self.c("ok"), self.c("line")) if tot else Text("·", style=self.c("dim")))
                    al.append(f" {d}/{tot}", style=self.c("dim"))
                    parent = fnode.add(al, data={"key": f"a:{f.id}/{aid}", "faction": f.id, "arc": aid})
                    parent.expand()
                for q in sorted(aq, key=lambda q: (q.status == "done", q.status == "parked")):
                    icon, color = STATUS.get(q.status, ("?", "dim"))
                    ql = Text()
                    ql.append(f"{icon} ", style=self.c(color))
                    ql.append(q.title, style=self.c("dim") if q.status in ("parked", "done") else self.c("bright"))
                    if q.reward and q.status != "done":
                        ql.append("  ◈", style=self.c("accent"))
                    parent.add_leaf(ql, data={"key": f"q:{q.ref}", "quest": q.ref})
            if first or f"f:{f.id}" in expanded:
                fnode.expand()

    @on(Tree.NodeHighlighted, "#tree")
    def _highlight(self, ev: Tree.NodeHighlighted) -> None:
        self.show_detail(ev.node.data or {})

    @on(Tree.NodeSelected, "#tree")
    def _select(self, ev: Tree.NodeSelected) -> None:
        data = ev.node.data or {}
        if data.get("quest"):
            self.launch(self._quests.get(data["quest"]))

    def show_detail(self, data: dict) -> None:
        md = self.query_one("#detail-md", Markdown)
        if data.get("quest"):
            q = self._quests.get(data["quest"])
            if not q:
                return
            sessions = [r for r in ledger.sessions(self.cfg).values() if q.ref in (r.get("quests") or [])]
            sessions.sort(key=lambda r: r.get("ended", 0), reverse=True)
            objs = "\n".join(f"- [{'x' if c else ' '}] {t}" for c, t in q.objectives)
            sess = "\n".join(f"- {datetime.fromtimestamp(r.get('ended', 0)):%b %d} {r.get('title', '')}: "
                             f"{r.get('digest', '')[:160]}" for r in sessions[:5])
            md.update(f"## {q.title}\n\n**{q.status}** · lead {q.lead or '-'}" + (f" · {q.size}" if q.size else "")
                      + (f" · reward ◈ {q.reward}" if q.reward else "")
                      + f"\n\n**Why** {q.why or '_(not set; optional)_'}\n\n**Done when** {q.done or '_(not set)_'}"
                      + f"\n\n**Next** {q.next or '-'}" + (f"\n\n**Waiting on you** {q.waiting}" if q.waiting else "")
                      + (f"\n\n### Objectives\n{objs}" if objs else "")
                      + f"\n\n### Save state\n{q.save_state or '-'}"
                      + (f"\n\n### Sessions that worked on it\n{sess}" if sess else "")
                      + "\n\n### Log\n" + "\n".join(f"- {line}" for line in q.log[-6:])
                      + f"\n\n`{q.ref}` · Enter starts a work session")
        elif data.get("arc"):
            f = self.cfg.faction(data["faction"])
            a = f.arc(data["arc"]) if f else None
            if not a:
                return
            d, tot = rewards.arc_progress(self.cfg, f.id, a.id)
            md.update(f"## {a.name}\n\n*{f.name}*\n\n**Goal** {a.goal or '-'}\n\n**Complete when** "
                      f"{a.complete_when or '_(not set)_'}" + (f"\n\n**Strategy** {a.strategy}" if a.strategy else "")
                      + f"\n\n**Progress** {d}/{tot} quests")
        elif data.get("faction"):
            f = self.cfg.faction(data["faction"])
            if not f:
                return
            st = views.standing(f.id, self.cfg)
            recent = "\n".join(f"- {m}" for m in st["recent"])
            md.update(f"## {f.name}\n\n**Aim** {f.intent or '-'}" + (f"\n\n**Strategy** {f.strategy}" if f.strategy else "")
                      + (f"\n\n**Success looks like** {f.success_looks_like}" if f.success_looks_like else "")
                      + f"\n\n### Recently\n{recent or '-'}")

    def launch(self, q: store.Quest | None) -> None:
        if not q:
            return
        if self.cfg.hub_launch:
            cmd = self.cfg.hub_launch.replace("{ref}", shlex.quote(q.ref))
            try:
                subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
                self.notify(f"starting: {q.title}", timeout=3)
            except OSError as e:
                self.notify(str(e), severity="error")
        else:
            self.push_screen(SeedModal(views.seed_prompt(q, self.cfg)))

    # --- deeds / party / suggestions -------------------------------------------------

    def render_deeds(self) -> None:
        t = self.query_one("#deeds-table", DataTable)
        t.clear(columns=True)
        t.add_columns("xp", "when", "goal", "deed")
        for d in ledger.deeds(self.cfg, since=time.time() - 30 * 86400)[:200]:
            f = self.cfg.faction(d.get("faction") or "")
            if f and f.private and not self.show_private:
                continue
            where = (f.name if f else "") + (f" › {f.arc(d['arc']).name}" if f and d.get("arc") and f.arc(d["arc"]) else "")
            t.add_row(Text(f"+{d.get('xp', 0)}", style=f"bold {self.c('gold')}"),
                      Text(datetime.fromtimestamp(d.get("ts", 0)).strftime("%a %d %H:%M"), style=self.c("dim")),
                      Text(where or "unsorted", style=self.c("accent2") if where else self.c("dim")), d.get("text", ""))

    def render_party(self) -> None:
        t = self.query_one("#party-table", DataTable)
        t.clear(columns=True)
        t.add_columns("when", "goal", "session", "what it did")
        for r in ledger.recent(self.cfg, days=14, limit=60):
            f = self.cfg.faction(r.get("faction") or "")
            if f and f.private and not self.show_private:
                continue
            where = (f.name if f else "") + (f" › {f.arc(r['arc']).name}" if f and r.get("arc") and f.arc(r["arc"]) else "")
            t.add_row(Text(datetime.fromtimestamp(r.get("ended", 0)).strftime("%a %d"), style=self.c("dim")),
                      Text(where or "unsorted", style=self.c("accent2") if where else self.c("dim")),
                      Text(r.get("title", "")[:40], style=self.c("bright")), (r.get("digest") or "")[:120])

    def render_suggestions(self) -> None:
        t = self.query_one("#sugg-table", DataTable)
        t.clear(columns=True)
        t.add_columns("goal", "suggested quest", "done when")
        self._suggestions = ledger.suggestions(self.cfg)
        for s in self._suggestions:
            t.add_row(Text(f"{s.get('faction')}/{s.get('arc') or '-'}", style=self.c("accent2")),
                      Text(s.get("title", ""), style=self.c("bright")), (s.get("done") or "")[:80])
        if not self._suggestions:
            t.add_row("", Text("nothing proposed yet", style=self.c("dim")), "")

    def render_commons(self) -> None:
        self.query_one("#commons-view", Static).update(_commons_text(self))

    def _current_suggestion(self) -> dict | None:
        if self.query_one("#tabs", TabbedContent).active != "suggestions" or not self._suggestions:
            return None
        row = self.query_one("#sugg-table", DataTable).cursor_row
        return self._suggestions[row] if 0 <= row < len(self._suggestions) else None

    def action_accept(self) -> None:
        s = self._current_suggestion()
        if not s:
            return
        q = store.create(self.cfg, s["faction"], s["title"], arc=s.get("arc") or "",
                         brief={"done": s.get("done", ""), "why": s.get("why", "")})
        ledger.resolve_suggestion(self.cfg, s["faction"], s["title"], "accepted")
        self.notify(f"quest added: {q.ref}", timeout=3)
        self.reload()

    def action_dismiss_suggestion(self) -> None:
        s = self._current_suggestion()
        if s:
            ledger.resolve_suggestion(self.cfg, s["faction"], s["title"], "dismissed")
            self.reload()


def _commons_text(app: "Hub") -> Group:
    info = commons.look(app.cfg)
    head = Text()
    head.append("THE COMMONS", style=f"bold {app.c('accent')}")
    head.append(f"   a world agents grow together · rule {info['rule']} · generation {info['generation']} · "
                f"{info['population']} alive\n", style=app.c("dim"))
    grid = Text()
    for line in info["world"].splitlines():
        for ch in line:
            grid.append("█" if ch == "█" else "·", style=app.c("accent2") if ch == "█" else app.c("line"))
        grid.append("\n")
    chron = Text("\nCHRONICLE\n", style=f"bold {app.c('accent2')}")
    if not info["chronicle"]:
        chron.append("No turns yet. After a meaningful piece of work, any agent may take one.\n", style=app.c("dim"))
    for c in info["chronicle"]:
        chron.append(f"{datetime.fromtimestamp(c['ts']):%b %d} ", style=app.c("dim"))
        chron.append(f"{c['by']}", style=f"bold {app.c('bright')}")
        chron.append(f" placed {c['pattern']}, ran to gen {c['generation'][1]}", style=app.c("text"))
        if c.get("after"):
            chron.append(f" (after: {c['after'][:60]})", style=app.c("dim"))
        chron.append(f"\n   “{c['observation'][:160]}”\n", style=app.c("gold"))
    return Group(head, grid, chron)


def run() -> None:
    Hub().run()
