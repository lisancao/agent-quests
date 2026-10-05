# Claude Code

    claude mcp add -s user questlog -- questlog serve

Then add the scribe hooks from the README to ~/.claude/settings.json.
To brief a new session on a quest from a script:

    QUESTLOG_QUEST=indie-game/demo/finish-level-one \
      claude "$(python -c 'from questlog import store, views; print(views.seed_prompt(store.find("finish-level-one")))')"
