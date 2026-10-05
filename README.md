<h1 align="center">agent-quests</h1>

<p align="center"><b>Contextual goals and state for your agents.</b></p>

<p align="center">
  <img src="https://img.shields.io/badge/STATUS-ACTIVE_QUEST-E867EA?style=for-the-badge&logo=gnu-bash&logoColor=white" alt="Status">
  <img src="https://img.shields.io/badge/PROTOCOL-MCP-48F2FB?style=for-the-badge&logoColor=black" alt="MCP">
  <img src="https://img.shields.io/badge/ENGINE-PYTHON_3.11+-4EA3BA?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/WORKS_WITH-CLAUDE_CODE-c678dd?style=for-the-badge&logo=anthropic&logoColor=white" alt="Claude Code">
  <img src="https://img.shields.io/badge/STORAGE-PLAIN_MARKDOWN-56d6a8?style=for-the-badge&logo=markdown&logoColor=white" alt="Markdown">
</p>

<p align="center">
<code>[ LVL 6 ] [ XP 1305 ] [ FACTIONS: 5 ] [ ACTIVE QUEST: LOADED ] [ SCRIBE: ONLINE ]</code>
</p>

<p align="center">
  <code>⚡ ─── ❖ ─── ⚡ ─── ❖ ─── ⚡ ─── ❖ ─── ⚡</code>
</p>

Agents are good at the task in front of them and blind to why it matters. Every session starts cold: it doesn't know the goal behind the request, what "done" means, what was decided last time, or that three other sessions are working toward the same thing. So you re-explain, and each session optimizes for the literal ask.

questlog gives every agent session two things, automatically, from whatever context it's in:

- **Contextual goals:** which of your goals this work serves (matched from the folder it's working in, the files it touches and what you ask), your aim and strategy for that goal, and the definition of done. A session debugging your lair's trapdoor knows you're building toward a final showdown, so it flags that the trapdoor is the first thing the heroes will test, not just the wiring diagram you pasted.
- **State:** where the work stands (save state, the next step, what's waiting on you) and what recent **sibling sessions** on the same goal did and decided, so no session starts from zero and parallel sessions stop working in silos.

And it keeps that state current without anyone taking notes: a scribe reads each session afterwards and records what it accomplished against your goals.

For you, the same data becomes a quest journal with an RPG reward layer, so seeing your goals move is actually enjoyable.

### What an agent sees

On a session's first prompt (Claude Code hook, or the `orient` MCP tool for any agent):

```
## Orientation (questlog): this session likely serves **Become an overlord** › **Build the volcano lair**  (working in its folder)
- Sam's aim: Rule the world, eventually, with style
- Strategy: Start with one island; a lair before an army; never monologue before the trap is armed
- Arc goal: A lair worthy of a final showdown. Complete when: shark tank, self-destruct button, and a dramatic entrance
- Quest `overlord/lair/install-the-shark-tank`: Install the shark tank. Why: no lair is taken seriously without one.
  Done when: sharks in, glass holds, trapdoor drops on cue. Next: fix the trapdoor that opens on its own
Sibling sessions on the same goal (recent):
- Mar 12 `5f2c91ab` Trapdoor debugging: glass sealed; the trapdoor opens when the elevator passes, not yet fixed.
- Mar 11 `a07d3e44` Henchman onboarding: drafted the jumpsuit policy; two recruits asked about dental.
```

Contextual policies tell an agent what it may do here. Contextual goals tell it what it's here *for*.

### How it fits together

```
  +--------------------+   orient (hook / MCP)    +----------------------+
  |   Your agents      | <──────────────────────  |   questlog           |
  |  Claude Code,      |   goal + state brief     |  factions › arcs ›   |
  |  omnigent, Codex…  | ──────────────────────>  |  quests (markdown)   |
  +--------------------+   quest_update / log     +----------------------+
           │                                                 ▲
           │ session transcripts                             │ save state, deeds,
           ▼                                                 │ suggested quests
  +--------------------+                          +----------------------+
  |   scribe           | ───────────────────────> |   session ledger     |
  |  one cheap LLM     |        records           |  digests, decisions, |
  |  pass per session  |                          |  deeds + XP          |
  +--------------------+                          +----------------------+
                                                             │
                                                             ▼
                                                  +----------------------+
                                                  |  /quest · hub · sheet|
                                                  |  your quest journal  |
                                                  +----------------------+
```

<p align="center">
  <code>⚡ ─── ❖ ─── ⚡ ─── ❖ ─── ⚡ ─── ❖ ─── ⚡</code>
</p>

## Concepts

| | what it is | example |
|---|---|---|
| **faction** | a big aspiration or allegiance | Become an overlord |
| **arc** | an initiative that serves a faction | Build the volcano lair |
| **quest** | a concrete deliverable inside an arc | Install the shark tank |

- **Factions** carry your `intent` (what you want, in your words), a `strategy` (how, for whom), and what `success_looks_like`. They're often ongoing.
- **Arcs** carry a `goal`, a `strategy`, and a definition of complete (`complete_when`).
- **Quests** carry `done` (observable definition of done), `why` (how it serves its arc), `next` (one five-minute step), `waiting` (what's blocked on you), a `lead` (who takes point), `size`, an optional `reward` you set for yourself, objectives, a save state and a log.
- **match** rules on factions, arcs and quests (folders, keywords) are what make goals *contextual*: they decide which goal a session is oriented to.

## Example config

`~/.config/questlog/questlog.toml` (every key is optional; this is also `examples/questlog.toml`):

```toml
root = "~/quests"              # where factions, arcs and quests live (plain markdown)
human = "Sam"                  # who "waiting on you" means

[agents]                       # who can take point on a quest, and what they're good at
claude = "hands-on coding and writing"
orchestrator = "multi-agent coding that ends in PRs to review"
assistant = "personal life, routines, check-ins"

# A faction is a big aspiration. intent + strategy are what agents get oriented to;
# match decides which sessions it applies to (the folder they work in, the words they use).
[[factions]]
id = "overlord"
name = "Become an overlord"
intent = "Rule the world, eventually, with style"
strategy = "Start with one island; a lair before an army; never monologue before the trap is armed"
success_looks_like = 'Heroes start their sentences with "We have to stop..."'
lead = "claude"
match = { paths = ["~/lair"], keywords = ["lair", "henchmen", "doomsday", "monologue"] }

# Arcs are initiatives serving the faction, each with its own definition of complete.
arcs = [
  { id = "lair", name = "Build the volcano lair", goal = "A lair worthy of a final showdown", complete_when = "Shark tank, self-destruct button, and a dramatic entrance", match = { paths = ["~/lair/blueprints"] } },
  { id = "henchmen", name = "Recruit henchmen", goal = "A loyal crew that reads the onboarding doc", complete_when = "Twelve henchmen, matching jumpsuits, nobody quits", match = { keywords = ["henchmen", "recruit", "jumpsuit"] } },
]

[[factions]]
id = "self-care"
name = "Villain self-care"
intent = "Sleep, stretch, and stop answering the red phone after midnight"
lead = "assistant"
private = true                 # left out of orientation maps, briefs and the hub unless asked for

[briefs.quest]                 # the questions asked when a quest is created
required = ["What does done look like, observably?", "Why does this matter for its arc?"]

[rewards]                      # XP curve, reputation tiers, your own achievements
level_divisor = 50
tiers = [["Unknown", 0], ["Recognized", 100], ["Respected", 400], ["Renowned", 1200], ["Legend", 3000]]
achievements = [
  { name = "Evil Genius", description = "Five quests done for Become an overlord", faction = "overlord", quests_done = 5 },
]

[hub]
launch = "my-launcher {ref}"   # what Enter on a quest runs in the hub; empty shows the briefing to copy

[scribe]                       # the post-session pass that keeps state current
command = ["claude", "-p", "--model", "haiku", "--no-session-persistence"]
throttle_minutes = 20
every_session = true           # read every session, not only ones bound to a quest
```

Factions and arcs can also be defined (or extended) in `FACTION.md` / `ARC.md` frontmatter, which is what `/quest new faction` and `/quest new arc` write. A quest is one markdown file:

```markdown
---
title: Install the shark tank
status: active
lead: claude
done: Sharks in, glass holds, trapdoor drops on cue
why: No lair is taken seriously without one
next: Fix the trapdoor that opens on its own
waiting: Pick laser sharks or regular sharks
size: medium
reward: A new cape
---
## Objectives
- [x] Dig the pit
- [x] Install the glass
- [ ] Fix the trapdoor
- [ ] Sharks

## Save state
Pit dug, glass installed and sealed. The trapdoor opens whenever the elevator passes; vibration sensor suspected.
Laser shark vendor quoted twice the budget; regular sharks available Thursday.

## Log
- 2026-03-10: created
- 2026-03-12 `5f2c91ab`: glass sealed; found the trapdoor bug
```

## The loop

1. **Orient.** On a session's first prompt, the agent gets the goal its context matches, your aim and strategy, the definitions of done, the quest's state, and what recent sibling sessions on the same goal did. A session that matches nothing gets a compact map of your goals and can attach itself.
2. **Work** happens in whatever agent you use. Agents can read and update state mid-session over MCP (`quest_get`, `quest_update`, `quest_log`).
3. **Record.** The scribe reads the session afterwards (one cheap LLM pass) and writes a digest, the decisions made and **deeds** (accomplishments, with XP) to a session ledger; it updates the quest's save state when the session was working on one, suggests new quests when work fits an arc but no quest, and never marks a quest done unless its definition of done is visibly met. Headless helper runs are skipped.
4. **Review.** `/quest`, `questlog brief` or the hub show where everything stands.

## Briefs: a few questions when an arc or quest is born

Creating an arc or quest asks a short, Heilmeier-style brief. Only two questions are required, the ones that keep an agent on track:

- **arc:** What are you trying to do, in plain words, and for whom? How will you know this arc is complete?
- **quest:** What does done look like, observably? Why does this matter for its arc?

Optional ones (approach, who cares, risks, size, a midpoint check) can be answered later. Over MCP, a create call without answers returns `needs_brief` with the questions, so the agent asks you and calls again. All questions are configurable.

## Rewards (full RPG, no guilt)

- **XP** from deeds (small/medium/large), ticked objectives, finished quests and completed arcs.
- **Level** on a gentle curve.
- **Faction reputation** tiers (Unknown → Recognized → Respected → Renowned → Legend by default).
- **Achievements**, built in and your own.
- **Loot**: a quest's `reward` lands in your inventory when you finish it.

Everything is derived from the files and the ledger. Nothing decays: no streaks, no overdue lists, no penalties.

## Storage

Plain markdown you can read and edit anywhere (Obsidian works well), plus a hidden ledger:

```
<root>/<faction>/FACTION.md              intent, strategy (frontmatter optional)
<root>/<faction>/<arc>/ARC.md            goal, complete_when, brief
<root>/<faction>/<arc>/<quest>.md        one quest
<root>/.questlog/sessions.jsonl          what each session did
<root>/.questlog/deeds.jsonl             accomplishments with XP
<root>/.questlog/suggestions.jsonl       quests the scribe proposes
```

Writes are atomic and locked, so several agents can update at once.


<pre align="center"><code>┌─────────────────────────────────────────────────────────────┐
│ QUEST LOG: LOADED · SIBLINGS: SYNCED · READY FOR DEPLOYMENT │
└─────────────────────────────────────────────────────────────┘</code></pre>

## Setup

```sh
uv tool install -e "./questlog[hub]"     # or: pipx install "./questlog[hub]"
questlog init --root ~/quests --human "Your name"
$EDITOR ~/.config/questlog/questlog.toml  # factions, arcs, match rules (see examples/questlog.toml)
claude mcp add -s user questlog -- questlog serve
```

Claude Code hooks (`~/.claude/settings.json`):

```json
"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "questlog orient"}]}],
"Stop":             [{"hooks": [{"type": "command", "command": "questlog scribe --throttle", "async": true}]}],
"SessionEnd":       [{"hooks": [{"type": "command", "command": "questlog scribe", "async": true}]}]
```

Then seed the ledger from the past week: `questlog backfill --days 7`.

**The `/quest` skill** (Claude Code): link it into your skills folder and `/quest` works in every session:

```sh
ln -s "$PWD/skills/quest" ~/.claude/skills/quest
```

`/quest` gives the brief; `/quest new faction|arc <name>`, `/quest new <title>`, `/quest <ref>`, `/quest work <ref>`, `/quest done <ref>`, `/quest waiting`, `/quest sheet` cover the rest, and plain language works too. Creating anything asks its brief first.

## Using it

```sh
questlog hub                 # the quest journal (character, journal, deeds, party, suggestions)
questlog sheet               # character sheet in the terminal
questlog tree                # factions -> arcs -> quests
questlog brief               # at most three things
questlog orient --cwd . --prompt "what I'm about to do"
questlog deeds --days 7
questlog faction overlord --name "Become an overlord"            # asks the brief
questlog arc overlord lair --name "Build the volcano lair"        # asks the brief
questlog new overlord "Install the shark tank" --arc lair         # asks the brief
```

**MCP tools:** `orient`, `faction_create`, `brief`, `mine`, `waiting_on_human`, `factions`, `standing`, `sheet`, `deeds`, `suggestions`, `recall`, `quest_list`, `quest_get`, `arc_create`, `quest_create`, `quest_update`, `objective_check`, `quest_log`, `quest_attach`. **Prompts:** `steward` (a planning partner that organises factions, arcs and quests without doing the work), `new_arc`, `new_quest`.

## Plug it into your agents

questlog speaks MCP over stdio (`questlog serve`), so any MCP-capable agent can read and update goals and state. What differs per harness is how much is automatic:

| harness | goals + state over MCP | orientation on the first prompt | scribe after the session | `/quest` |
|---|---|---|---|---|
| **Claude Code** | ✅ | ✅ hook | ✅ hooks | ✅ skill |
| **Omnigent agents** (e.g. its polly orchestrator, custom YAML agents) | ✅ | via the `orient` tool | not yet (needs an omnigent transcript adapter) | `new_quest` / `new_arc` / `steward` prompts |
| **Other MCP clients** (Codex, Cursor, OpenCode, Claude Desktop…) | ✅ | via the `orient` tool | not yet | prompts, where the client supports them |
| **Your own code** | Python API | `orient.briefing()` | `scribe.core.run()` | n/a |

The server's built-in instructions tell every MCP agent to call `orient` at the start of work, attach itself to a quest it's working on, and record decisions with `quest_update` / `quest_log`, so harnesses without hooks still get oriented and still write state back. Only the automatic after-session scribe needs a transcript adapter; Claude Code's is in `questlog/scribe/claude_code.py`, and others can sit beside it.

### Claude Code

```sh
claude mcp add -s user questlog -- questlog serve
ln -s "$PWD/skills/quest" ~/.claude/skills/quest
```

plus the three hooks under [Setup](#setup) (`orient`, and the scribe on `Stop` / `SessionEnd`).

### Omnigent

Add questlog next to the agent's other tools in its `config.yaml`:

```yaml
tools:
  questlog:
    type: mcp
    command: questlog
    args: [serve]
```

For an orchestrator like polly, a few lines in its prompt turn quests into its work queue:

```yaml
prompt: |
  ...
  Quest log: if the human hands you a quest (a questlog ref like
  `overlord/lair/install-the-shark-tank`), read it first with `quest_get` and work
  toward its `next` step and definition of done. As work lands, record it with
  `quest_update` / `quest_log`: the new save state, the next step, and every PR
  that needs the human's review under `waiting`.
```

Omnigent policies (`tools`, `guardrails`) only gate shell and session tools, so questlog's tools aren't blocked by them. Contextual policies say what an agent *may* do; questlog adds what it's working *toward*.

### Other MCP clients

Point the client at `questlog serve` over stdio. For example:

```toml
# Codex: ~/.codex/config.toml
[mcp_servers.questlog]
command = "questlog"
args = ["serve"]
```

```json
// Cursor (.cursor/mcp.json) and Claude Desktop (claude_desktop_config.json)
{ "mcpServers": { "questlog": { "command": "questlog", "args": ["serve"] } } }
```

Use the full path to `questlog` if the client doesn't share your shell's `PATH`.

### Your own code

```python
from questlog import config, store, views, orient, rewards, ledger

cfg = config.load()
print(orient.briefing(cfg, cwd="~/lair", prompt="fix the trapdoor"))  # what an agent would see
q = store.find("install-the-shark-tank", cfg)
print(views.seed_prompt(q, cfg))   # opening message for a briefed work session
print(rewards.sheet(cfg).level)    # the character sheet
```

`[hub] launch` in the config sets what Enter on a quest runs, so a terminal launcher can open a briefed session in a new tab.
