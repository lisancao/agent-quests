"""questlog hub: the quest journal.

Pages: Journal (main quests, side quests, completed; a quest page with objectives and rewards) ·
Character · Codex (faction lore and allies) · Chronicle (deeds) · Party (recent sessions) ·
Commons · Rumours (quests the scribe proposed). Two looks: "codex" and "parchment" (t switches).
When the scribe changes something, a "quest updated" toast appears; a level-up gets its own screen.
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
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Static, TabbedContent, TabPane, Tree

from .. import commons, config as cfgmod, ledger, rewards, store, views
from . import themes

CSS = """
Screen { background: $q-bg; color: $q-text; }
TabbedContent, TabPane { background: $q-bg; }
Tabs { background: $q-panel; }
Tab { color: $q-dim; }
Tab.-active { color: $q-accent; text-style: bold; }
Underline > .underline--bar { color: $q-accent; background: $q-line; }
#title { height: 1; background: $q-panel; color: $q-accent; text-style: bold; content-align: center middle; }
#book { height: 1fr; padding: 0 1; }
#left-page { width: 42%; border: double $q-line; background: $q-panel; padding: 0 1; }
#right-page { width: 1fr; border: double $q-line; background: $q-bg; padding: 0 2; }
#left-page:focus-within { border: double $q-accent; }
#quests { background: $q-panel; }
#page { padding: 1 0; }
.pane { padding: 1 2; }
DataTable { background: $q-bg; height: 1fr; }
DataTable > .datatable--header { background: $q-panel; color: $q-accent; text-style: bold; }
DataTable > .datatable--cursor { background: $q-select; color: $q-bright; }
Tree > .tree--cursor { background: $q-select; color: $q-bright; }
Tree > .tree--guides { color: $q-line; }
Footer { background: $q-panel; }
FooterKey { background: $q-panel; color: $q-text; }
FooterKey .footer-key--key { color: $q-accent; background: $q-panel; text-style: bold; }
FooterKey .footer-key--description { color: $q-text; background: $q-panel; }
Tab.-active, Tabs:focus Tab.-active { background: $q-select; color: $q-accent; }
* { scrollbar-color: $q-line; scrollbar-color-hover: $q-dim; scrollbar-color-active: $q-accent; scrollbar-background: $q-panel; }
LevelUp, SeedModal { align: center middle; }
#levelup { width: 56; height: auto; border: double $q-gold; background: $q-panel; padding: 1 3; }
#seed { width: 90; height: auto; max-height: 80%; border: double $q-accent; background: $q-panel; padding: 1 2; }
"""


def _pips(done: int, total: int, on: str, off: str, width: int = 6) -> str:
    if total <= 0:
        return off * width
    n = round(width * done / total)
    return on * n + off * (width - n)


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


class LevelUp(ModalScreen[None]):
    BINDINGS = [Binding("escape,q,enter,space", "dismiss(None)", "continue")]

    def __init__(self, body: Text) -> None:
        super().__init__()
        self.body = body

    def compose(self) -> ComposeResult:
        yield Static(self.body, id="levelup")


class Hub(App):
    TITLE = "questlog"
    CSS = CSS
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        Binding("1", "tab('journal')", "journal"),
        Binding("2", "tab('character')", "character"),
        Binding("3", "tab('codex')", "codex"),
        Binding("4", "tab('chronicle')", "chronicle"),
        Binding("5", "tab('party')", "party"),
        Binding("6", "tab('commons')", "commons"),
        Binding("7", "tab('rumours')", "rumours"),
        Binding("t", "switch_theme", "theme"),
        Binding("p", "toggle_private", "private"),
        Binding("a", "accept", "accept", show=False),
        Binding("x", "dismiss_suggestion", "dismiss", show=False),
        Binding("r", "reload", "refresh"),
        Binding("q", "quit", "quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.cfg = cfgmod.load()
        self.theme_name = self.cfg.journal_theme if self.cfg.journal_theme in themes.THEMES else "codex"
        self.T = themes.get(self.theme_name, self.cfg.hub_theme)
        self.show_private = False
        self._quests: dict[str, store.Quest] = {}
        self._suggestions: list[dict] = []
        self._seen: dict | None = None      # baseline for "quest updated" toasts
        self._seen_level: int | None = None
        self._last_deed_ts = time.time()

    # --- theme helpers --------------------------------------------------------------

    def get_css_variables(self) -> dict[str, str]:
        base = super().get_css_variables()
        T = getattr(self, "T", themes.get("codex"))
        return {**base, **{f"q-{k}": v for k, v in T["colors"].items()}}

    def c(self, key: str) -> str:
        return self.T["colors"].get(key, "white")

    def g(self, key: str) -> str:
        return self.T["glyphs"][key]

    def L(self, key: str) -> str:
        return self.T["labels"][key]

    def _up(self, s: str) -> str:
        return s.upper() if self.T["upper"] else s

    def action_switch_theme(self) -> None:
        names = list(themes.THEMES)
        self.theme_name = names[(names.index(self.theme_name) + 1) % len(names)]
        own = self.cfg.hub_theme if self.theme_name == self.cfg.journal_theme else None
        self.T = themes.get(self.theme_name, own)
        self.refresh_css()
        self.query_one("#title", Static).update(self.L("title"))
        tabs = self.query_one("#tabs", TabbedContent)
        for pane in ("journal", "character", "codex", "chronicle", "party", "commons", "rumours"):
            try:
                tabs.get_tab(pane).label = self.L(pane)
            except Exception:  # noqa: BLE001 - cosmetic only
                pass
        self.reload(quiet=True)
        self.notify(f"theme: {self.theme_name} (set [journal] theme in questlog.toml to keep it)", timeout=3)

    # --- layout -------------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static(self.L("title"), id="title")
        with TabbedContent(initial="journal", id="tabs"):
            with TabPane(self.L("journal"), id="journal"):
                with Horizontal(id="book"):
                    with Vertical(id="left-page"):
                        yield Tree("quests", id="quests")
                    with VerticalScroll(id="right-page"):
                        yield Static(id="page")
            with TabPane(self.L("character"), id="character"):
                yield VerticalScroll(Static(id="sheet"), classes="pane")
            with TabPane(self.L("codex"), id="codex"):
                yield VerticalScroll(Static(id="codex-view"), classes="pane")
            with TabPane(self.L("chronicle"), id="chronicle"):
                yield DataTable(id="deeds-table", cursor_type="row")
            with TabPane(self.L("party"), id="party"):
                yield DataTable(id="party-table", cursor_type="row")
            with TabPane(self.L("commons"), id="commons"):
                yield VerticalScroll(Static(id="commons-view"), classes="pane")
            with TabPane(self.L("rumours"), id="rumours"):
                yield DataTable(id="sugg-table", cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        self.reload(quiet=True)
        self.set_interval(10, self.reload)

    def action_reload(self) -> None:
        self.reload()

    def reload(self, quiet: bool = False) -> None:
        self.cfg = cfgmod.load()
        self.render_journal()
        self.render_sheet()
        self.render_codex()
        self.render_deeds()
        self.render_party()
        self.render_commons()
        self.render_suggestions()
        self.announce(quiet)

    def action_tab(self, tab: str) -> None:
        self.query_one("#tabs", TabbedContent).active = tab

    def action_toggle_private(self) -> None:
        self.show_private = not self.show_private
        self.reload(quiet=True)
        self.notify("showing private factions" if self.show_private else "private factions hidden", timeout=2)

    # --- toasts and level-ups -------------------------------------------------------------

    def announce(self, quiet: bool) -> None:
        qs = store.load(self.cfg, include_private=self.show_private)
        snap = {q.ref: (q.status, len(q.log), sum(c for c, _ in q.objectives), q.title, q.reward) for q in qs}
        sheet = rewards.sheet(self.cfg, include_private=self.show_private)
        if self._seen is None or quiet:
            self._seen, self._seen_level = snap, sheet.level
            return
        for ref, (status, nlog, nobj, title, reward) in snap.items():
            old = self._seen.get(ref)
            if old is None:
                self.notify(f"{self.g('main')} NEW QUEST · {title}", timeout=6)
            elif status == "done" and old[0] != "done":
                self.notify(f"{self.g('star')} {self.L('complete')} · {title}"
                            + (f"\n{self.g('reward')} {reward}" if reward else ""), timeout=8)
            elif (nlog, nobj, status) != (old[1], old[2], old[0]):
                self.notify(f"{self.g('main')} {self.L('updated')} · {title}", timeout=6)
        new_deeds = ledger.deeds(self.cfg, since=self._last_deed_ts)
        if new_deeds:
            xp = sum(d.get("xp", 0) for d in new_deeds)
            self.notify(f"+{xp} XP · {len(new_deeds)} deed{'s' if len(new_deeds) != 1 else ''}", timeout=5)
            self._last_deed_ts = max(d.get("ts", 0) for d in new_deeds) + 0.001
        if sheet.level > (self._seen_level or 0):
            body = Text(justify="center")
            body.append(f"{self.g('star')}  {self.L('levelup')}  {self.g('star')}\n\n", style=f"bold {self.c('gold')}")
            body.append(f"{self.cfg.human} reached level {sheet.level}\n", style=f"bold {self.c('bright')}")
            body.append(f"{sheet.xp} XP · {sheet.deeds_total} deeds · {sheet.quests_done} quests\n\n", style=self.c("dim"))
            body.append("press enter", style=self.c("dim"))
            self.push_screen(LevelUp(body))
        self._seen, self._seen_level = snap, sheet.level

    # --- journal ------------------------------------------------------------------------

    def _qlabel(self, q: store.Quest, recent: set[str]) -> Text:
        g, c = self.g, self.c
        t = Text()
        mark = {"blocked": ("✖", "bad"), "waiting": ("⏳", "warn"), "parked": (g("side"), "dim")}.get(q.status)
        if q.status == "parked" and q.after:
            mark = ("🔒", "dim")
        t.append(f"{mark[0] if mark else g('obj_open')} ", style=c(mark[1] if mark else "accent2"))
        t.append(q.title, style=c("dim") if q.status in ("parked", "done") else c("bright"))
        if q.reward and q.status != "done":
            t.append(f" {g('reward')}", style=c("gold"))
        if q.ref in recent:
            t.append(f"  {g('new')}", style=c("accent"))
        return t

    def render_journal(self) -> None:
        tree = self.query_one("#quests", Tree)
        cursor = (tree.cursor_node.data or {}).get("key") if tree.cursor_node else None
        tree.clear()
        tree.show_root = False
        tree.root.expand()
        qs = store.load(self.cfg, include_private=self.show_private)
        self._quests = {q.ref: q for q in qs}
        recent = {q.ref for q in sorted(qs, key=lambda q: q.updated or "", reverse=True)[:2] if q.status != "done"}
        g, c = self.g, self.c
        nodes: list = []

        main = tree.root.add(Text(f"{g('main')} {self.L('main')}", style=f"bold {c('accent')}"), data={"key": "h:main"})
        main.expand()
        for f in self.cfg.factions:
            if f.private and not self.show_private:
                continue
            fnode = main.add(Text(f.name, style=f"bold {c('bright')}"), data={"key": f"f:{f.id}", "faction": f.id})
            fnode.expand()
            nodes.append(fnode)
            for a in f.arcs:
                aq = [q for q in qs if q.faction == f.id and q.arc == a.id]
                done = sum(q.status == "done" for q in aq)
                al = Text()
                al.append(f"{g('current')} {a.name} ", style=c("accent2"))
                al.append(_pips(done, len(aq), g("pip_on"), g("pip_off")), style=c("ok"))
                anode = fnode.add(al, data={"key": f"a:{f.id}/{a.id}", "faction": f.id, "arc": a.id})
                anode.expand()
                nodes.append(anode)
                for q in aq:
                    if q.status != "done":
                        nodes.append(anode.add_leaf(self._qlabel(q, recent), data={"key": f"q:{q.ref}", "quest": q.ref}))

        def visible(q: store.Quest) -> bool:
            f = self.cfg.faction(q.faction)
            return not (f and f.private and not self.show_private)

        side = [q for q in qs if not q.arc and q.status != "done" and visible(q)]
        if side:
            snode = tree.root.add(Text(f"{g('side')} {self.L('side')}", style=f"bold {c('accent')}"), data={"key": "h:side"})
            snode.expand()
            for q in side:
                nodes.append(snode.add_leaf(self._qlabel(q, recent), data={"key": f"q:{q.ref}", "quest": q.ref}))
        done = [q for q in qs if q.status == "done" and visible(q)]
        if done:
            dnode = tree.root.add(Text(f"{g('done_section')} {self.L('completed')} ({len(done)})", style=f"bold {c('dim')}"),
                                  data={"key": "h:done"})
            for q in done:
                nodes.append(dnode.add_leaf(Text(f"{g('obj_done')} {q.title}", style=c("dim")),
                                            data={"key": f"q:{q.ref}", "quest": q.ref}))
        target = next((n for n in nodes if cursor and (n.data or {}).get("key") == cursor), None)
        if target is None:
            target = next((n for n in nodes if (n.data or {}).get("quest")), None)
        if target is not None:
            def focus_target(node=target) -> None:
                tree.move_cursor(node)
                self.render_page(node.data or {})
            self.call_after_refresh(focus_target)

    @on(Tree.NodeHighlighted, "#quests")
    def _highlight(self, ev: Tree.NodeHighlighted) -> None:
        self.render_page(ev.node.data or {})

    @on(Tree.NodeSelected, "#quests")
    def _select(self, ev: Tree.NodeSelected) -> None:
        data = ev.node.data or {}
        if data.get("quest"):
            self.launch(self._quests.get(data["quest"]))

    def _heading(self, text: str) -> Text:
        return Text(f"\n{self._up(text)}\n", style=f"bold {self.c('accent2')}")

    def render_page(self, data: dict) -> None:
        page = self.query_one("#page", Static)
        g, c = self.g, self.c
        if data.get("quest"):
            q = self._quests.get(data["quest"])
            if not q:
                return
            f = self.cfg.faction(q.faction)
            a = f.arc(q.arc) if f and q.arc else None
            head = Text()
            head.append(f"{self._up(q.title)}\n", style=f"bold {c('accent')}")
            head.append(" › ".join(x for x in ((f.name if f else q.faction), (a.name if a else "")) if x), style=c("dim"))
            head.append(f"   {q.status}" + (f" · lead {q.lead}" if q.lead else "")
                        + (f" · {q.authority}" if q.authority and q.authority != "autonomous" else ""), style=c("dim"))
            parts: list = [head]
            if q.why:
                parts.append(Text(f"\n“{q.why}”\n", style=f"italic {c('gold')}"))
            if q.done:
                parts.append(Text(f"Done when: {q.done}", style=c("text")))
            if q.after:
                parts.append(Text(f"{'Unlocks after' if q.status == 'parked' else 'Followed'}: {q.after}", style=c("dim")))
            parts.append(self._heading(self.L("objectives")))
            obj = Text()
            first_open = next((t for done_, t in q.objectives if not done_), None)
            for done_, t in q.objectives:
                if done_:
                    obj.append(f"{g('obj_done')} {t}\n", style=c("dim"))
                else:
                    cur = t == first_open
                    obj.append(f"{g('current') if cur else g('obj_open')} {t}", style=c("bright") if cur else c("text"))
                    obj.append("  ← current\n" if cur else "\n", style=c("accent"))
            if q.next:
                obj.append(f"{g('current')} Next: {q.next}\n", style=f"bold {c('bright')}")
            if q.waiting:
                obj.append(f"⏳ Waiting on you: {q.waiting}\n", style=c("warn"))
            parts.append(obj)
            if q.save_state:
                parts += [self._heading(self.L("notes")), Text(q.save_state, style=c("text"))]
            if q.log:
                parts.append(self._heading(self.L("entries")))
                ent = Text()
                for line in reversed(q.log[-8:]):
                    day, _, rest = line.partition(" ")
                    ent.append(f"{day.rstrip(':')}  ", style=c("dim"))
                    ent.append(f"{rest.lstrip(':').strip()}\n", style=c("text"))
                parts.append(ent)
            rew = Text()
            xp = self.cfg.xp.get(f"quest_{q.size or 'medium'}", self.cfg.xp["quest_medium"])
            rew.append(f"\n{g('rule') * 40}\n", style=c("line"))
            rew.append(f"{self._up(self.L('reward'))}  ", style=f"bold {c('gold')}")
            rew.append(f"{g('reward')} {q.reward + ' · ' if q.reward else ''}{xp} XP", style=c("gold"))
            rew.append(f"\n\n{q.ref} · enter starts a work session", style=c("dim"))
            parts.append(rew)
            page.update(Group(*parts))
        elif data.get("arc"):
            f = self.cfg.faction(data["faction"])
            a = f.arc(data["arc"]) if f else None
            if not a:
                return
            d, tot = rewards.arc_progress(self.cfg, f.id, a.id)
            t = Text()
            t.append(f"{self._up(a.name)}\n", style=f"bold {c('accent')}")
            t.append(f"a questline of {f.name}\n\n", style=c("dim"))
            if a.goal:
                t.append(f"{a.goal}\n\n", style=c("text"))
            t.append(f"Complete when: {a.complete_when or '(not set)'}\n", style=c("text"))
            if a.strategy:
                t.append(f"Approach: {a.strategy}\n", style=c("text"))
            t.append(f"\n{_pips(d, tot, g('pip_on'), g('pip_off'), 12)}  {d}/{tot} quests\n", style=c("ok"))
            page.update(t)
        elif data.get("faction"):
            page.update(self._faction_lore(self.cfg.faction(data["faction"])))
        else:
            page.update(Text("Choose a quest from the journal.", style=c("dim")))

    def _faction_lore(self, f) -> Text:
        c = self.c
        t = Text()
        if not f:
            return t
        st = views.standing(f.id, self.cfg)
        rep = next((r for r in rewards.sheet(self.cfg).reputation if r.faction == f.id), None)
        t.append(f"{self._up(f.name)}\n", style=f"bold {c('accent')}")
        if rep:
            t.append(f"{rep.tier} · {rep.xp} XP\n\n", style=c("gold"))
        for label, val in (("Aim", f.intent), ("Strategy", f.strategy), ("Success looks like", f.success_looks_like),
                           ("Principles", f.principles)):
            if val:
                t.append(f"{label}: ", style=f"bold {c('bright')}")
                t.append(f"{val}\n", style=c("text"))
        if st["recent"]:
            t.append(f"\n{self._up('Recent deeds')}\n", style=f"bold {c('accent2')}")
            for m in st["recent"]:
                t.append(f"{self.g('bullet')} {m}\n", style=c("text"))
        return t

    def launch(self, q: store.Quest | None) -> None:
        if not q:
            return
        if self.cfg.hub_launch:
            cmd = self.cfg.hub_launch.replace("{ref}", shlex.quote(q.ref))
            try:
                subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
                self.notify(f"{self.g('current')} starting: {q.title}", timeout=3)
            except OSError as e:
                self.notify(str(e), severity="error")
        else:
            self.push_screen(SeedModal(views.seed_prompt(q, self.cfg)))

    # --- character ------------------------------------------------------------------------

    def render_sheet(self) -> None:
        sh = rewards.sheet(self.cfg, include_private=self.show_private)
        c, g = self.c, self.g
        head = Text()
        head.append(f"{self.cfg.human}", style=f"bold {c('bright')}")
        head.append(f"   level {sh.level}\n", style=f"bold {c('gold')}")
        head.append_text(_bar(sh.into_level, sh.level_span, 40, c("gold"), c("line")))
        head.append(f"  {sh.into_level}/{sh.level_span} XP to level {sh.level + 1}   ", style=c("dim"))
        head.append(f"total {sh.xp} XP\n", style=c("text"))
        head.append(f"{sh.deeds_total} deeds · {sh.quests_done} quests done · {sh.arcs_done} arcs complete · "
                    f"{sh.sessions} sessions recorded\n", style=c("dim"))
        rep = Table.grid(padding=(0, 2))
        for _ in range(5):
            rep.add_column()
        for r in sh.reputation:
            rep.add_row(Text(r.name, style=f"bold {c('accent')}"), Text(r.tier, style=c("gold")),
                        _bar(r.into_tier, r.tier_span, 24, c("accent2"), c("line")),
                        Text(f"{r.xp} XP", style=c("text")), Text(f"→ {r.next_tier}" if r.next_tier else "max", style=c("dim")))
        ach = Text()
        for a in sh.achievements:
            ach.append(f"{g('star')} ", style=c("gold"))
            ach.append(a["name"], style=f"bold {c('bright')}")
            ach.append(f"  {a['description']}\n", style=c("dim"))
        if not sh.achievements:
            ach.append("None yet. Your first deed unlocks one.\n", style=c("dim"))
        inv = Text()
        for i in sh.inventory:
            inv.append(f"{g('reward')} ", style=c("gold"))
            inv.append(i["reward"], style=c("bright"))
            inv.append(f"  from {i['quest']}\n", style=c("dim"))
        if not sh.inventory:
            inv.append("Set a reward on a quest and it lands here when you finish.\n", style=c("dim"))
        self.query_one("#sheet", Static).update(Group(head, self._heading("Reputation"), rep, self._heading("Achievements"),
                                                      ach, self._heading("Inventory"), inv))

    # --- codex ----------------------------------------------------------------------------

    def render_codex(self) -> None:
        c = self.c
        parts: list = [self._heading(self.L("lore"))]
        for f in self.cfg.factions:
            if f.private and not self.show_private:
                continue
            parts.append(self._faction_lore(f))
        parts.append(self._heading(self.L("allies")))
        qs = store.load(self.cfg, include_private=self.show_private)
        allies = Text()
        for name, desc in (self.cfg.agents or {}).items():
            led = [q for q in qs if q.lead == name]
            allies.append(name, style=f"bold {c('accent')}")
            allies.append(f"  {desc}\n", style=c("text"))
            allies.append(f"   leads {sum(q.status != 'done' for q in led)} open quests, "
                          f"finished {sum(q.status == 'done' for q in led)}\n", style=c("dim"))
        if not self.cfg.agents:
            allies.append("Name your agents under [agents] in questlog.toml.\n", style=c("dim"))
        parts.append(allies)
        self.query_one("#codex-view", Static).update(Group(*parts))

    # --- chronicle / party / commons / rumours ----------------------------------------------

    def _where(self, faction: str | None, arc: str | None) -> str:
        f = self.cfg.faction(faction or "")
        if not f:
            return ""
        a = f.arc(arc) if arc else None
        return f.name + (f" › {a.name}" if a else "")

    def render_deeds(self) -> None:
        t = self.query_one("#deeds-table", DataTable)
        t.clear(columns=True)
        t.add_columns("XP", "when", "for", "deed")
        for d in ledger.deeds(self.cfg, since=time.time() - 30 * 86400)[:200]:
            f = self.cfg.faction(d.get("faction") or "")
            if f and f.private and not self.show_private:
                continue
            where = self._where(d.get("faction"), d.get("arc"))
            t.add_row(Text(f"+{d.get('xp', 0)}", style=f"bold {self.c('gold')}"),
                      Text(datetime.fromtimestamp(d.get("ts", 0)).strftime("%a %d %H:%M"), style=self.c("dim")),
                      Text(where or "unsorted", style=self.c("accent2") if where else self.c("dim")), d.get("text", ""))

    def render_party(self) -> None:
        t = self.query_one("#party-table", DataTable)
        t.clear(columns=True)
        t.add_columns("when", "for", "session", "what it did")
        for r in ledger.recent(self.cfg, days=14, limit=60):
            f = self.cfg.faction(r.get("faction") or "")
            if f and f.private and not self.show_private:
                continue
            where = self._where(r.get("faction"), r.get("arc"))
            t.add_row(Text(datetime.fromtimestamp(r.get("ended", 0)).strftime("%a %d"), style=self.c("dim")),
                      Text(where or "unsorted", style=self.c("accent2") if where else self.c("dim")),
                      Text(r.get("title", "")[:40], style=self.c("bright")), (r.get("digest") or "")[:120])

    def render_commons(self) -> None:
        info = commons.look(self.cfg)
        c = self.c
        head = Text()
        head.append(self._up(self.L("commons")), style=f"bold {c('accent')}")
        head.append(f"   a world agents grow together · rule {info['rule']} · generation {info['generation']} · "
                    f"{info['population']} alive\n", style=c("dim"))
        grid = Text()
        for line in info["world"].splitlines():
            for ch in line:
                grid.append("█" if ch == "█" else "·", style=c("accent2") if ch == "█" else c("line"))
            grid.append("\n")
        chron = self._heading("Chronicle")
        if not info["chronicle"]:
            chron.append("No turns yet. After a meaningful piece of work, any agent may take one.\n", style=c("dim"))
        for e in info["chronicle"]:
            chron.append(f"{datetime.fromtimestamp(e['ts']):%b %d} ", style=c("dim"))
            chron.append(e["by"], style=f"bold {c('bright')}")
            chron.append(f" placed {e['pattern']}, ran to gen {e['generation'][1]}", style=c("text"))
            if e.get("after"):
                chron.append(f" (after: {e['after'][:60]})", style=c("dim"))
            chron.append(f"\n   “{e['observation'][:160]}”\n", style=c("gold"))
        self.query_one("#commons-view", Static).update(Group(head, grid, chron))

    def render_suggestions(self) -> None:
        t = self.query_one("#sugg-table", DataTable)
        t.clear(columns=True)
        t.add_columns("heard for", "a quest that might exist", "done when")
        self._suggestions = ledger.suggestions(self.cfg)
        for s in self._suggestions:
            t.add_row(Text(self._where(s.get("faction"), s.get("arc")) or s.get("faction", ""), style=self.c("accent2")),
                      Text(s.get("title", ""), style=self.c("bright")), (s.get("done") or "")[:80])
        if not self._suggestions:
            t.add_row("", Text("no rumours yet", style=self.c("dim")), "")

    def _current_suggestion(self) -> dict | None:
        if self.query_one("#tabs", TabbedContent).active != "rumours" or not self._suggestions:
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
        self.notify(f"{self.g('main')} NEW QUEST · {q.title}", timeout=4)
        self.reload(quiet=True)

    def action_dismiss_suggestion(self) -> None:
        s = self._current_suggestion()
        if s:
            ledger.resolve_suggestion(self.cfg, s["faction"], s["title"], "dismissed")
            self.reload(quiet=True)


def run() -> None:
    Hub().run()
