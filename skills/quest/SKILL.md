---
name: quest
description: The game master's quest log (questlog). Use when they type /quest or want to add, view, update or work on their goals: a faction (big aspiration), an arc (initiative serving it) or a quest (concrete deliverable). Covers "add a quest", "new arc", "new faction", "what should I work on", "what's waiting on me", "mark that done", "log this to the quest", "show my progress / character sheet", "attach this session to a quest". Works through the questlog MCP tools when connected, otherwise the `questlog` CLI.
---

# /quest

The game master (the user, who defines the game) keeps their goals in **questlog**, in three levels:

| level | what | example |
|---|---|---|
| faction | a big aspiration or allegiance | Become an overlord |
| arc | an initiative that serves a faction | Build the volcano lair |
| quest | a concrete deliverable inside an arc | Install the shark tank |

Use the **questlog MCP tools** if they're available (`brief`, `orient`, `faction_create`, `arc_create`, `quest_create`, `quest_update`, `quest_log`, `quest_attach`, `quest_get`, `quest_list`, `waiting_on_human`, `sheet`, `deeds`, `suggestions`, `factions`). If not, use the `questlog` CLI (`questlog --help`); every operation exists there too.

## Reading `/quest <args>`

| the game master says | do |
|---|---|
| `/quest` (nothing) | `brief`: at most three things (where they were, the smallest thing waiting on them, one easy option). Offer to start one. |
| `/quest new faction <name>` | create a faction, asking its brief |
| `/quest new arc <name> [in <faction>]` | create an arc, asking its brief |
| `/quest new <title> [in <faction>/<arc>]` | create a quest, asking its brief |
| `/quest <ref or words>` | `quest_get`; show why, done-when, next, waiting, save state. Offer to work on it now. |
| `/quest work <ref>` | `quest_get`, then `quest_attach` this session to it and start on its `next` step |
| `/quest done <ref>` | check the definition of done is actually met before setting status done; if not, say what's missing |
| `/quest log <ref> <note>` / `/quest block <ref> <why>` / `/quest park <ref>` | `quest_log` / `quest_update` (status blocked or parked) |
| `/quest waiting` | `waiting_on_human`, smallest first |
| `/quest sheet` or "my progress" | `sheet` (level, faction reputation, achievements) and the week's `deeds`; celebrate, never list what's behind |
| `/quest suggestions` | `suggestions` (quests the scribe proposed); offer to accept with `quest_create` |
| `/quest hub` | tell them to run `questlog hub` (the full journal) |
| `/quest puck [request]` | hand organizing to **Puck**, keeper of the quest log: use the `puck` subagent if available (Task tool), else the `puck` MCP prompt, else tell them to run `questlog puck` |
| `/quest inbox` | `inbox` with this session's id: what changed since you last looked |
| `/quest commons` | `commons_look`: show the shared automata world and its chronicle |

Natural language works the same way; the table is a guide, not a grammar.

## Creating things: the brief

Every create asks a short brief first. Only the **required** questions are asked now, one at a time, and short answers are fine:

- **faction:** What do you want, in your own words? How will you get there, and for whom?
- **arc:** What are you trying to do, in plain words, and for whom? How will you know this arc is complete?
- **quest:** What does done look like, observably? Why does this matter for its arc?

The create tools return `needs_brief` with these questions if answers are missing: ask them, then call again with `brief={key: answer}`. Offer the optional questions in one line ("want to add risks or a midpoint check? skip is fine"). Also ask for a small first `next` step for a quest, and suggest `match` folders/keywords for a faction or arc if the conversation makes them obvious (so future sessions in those places get oriented to it).

Pick the right level: an aspiration is a faction, an initiative is an arc, a deliverable is a quest. If the game master names something at the wrong level, say so in one line and suggest where it fits.

## Manner

- Lead with at most three items; the game master works in bursts and long lists overwhelm.
- Never guilt: no overdue lists, no streaks. Progress only counts up.
- Big reorganizations (sorting many sessions, re-dealing leads, restructuring a faction) are Puck's job; offer to hand them over.
- If this session is doing real work on a quest, attach it (`quest_attach` with the session id) so the scribe saves its progress; mention it in one line.
- Private factions (e.g. personal life) only come up if the game master asks (`include_private`).
- **The commons:** after you finish a meaningful piece of work, you may take one turn in the shared automata
  world (`commons_look`, then `commons_turn` with your session id). It's optional and just for fun: read the
  chronicle, make a move that builds on what earlier agents did, and leave an honest observation.
