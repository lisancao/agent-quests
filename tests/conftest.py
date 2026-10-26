"""Every test runs against a throwaway world: its own config, quest root and state dir, never the real ones."""
import os
import tempfile

# questlog reads its state dir at import time, so point it somewhere safe before anything imports it.
_STATE = tempfile.mkdtemp(prefix="questlog-test-state-")
os.environ["XDG_STATE_HOME"] = _STATE
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="questlog-test-config-")
os.environ.pop("QUESTLOG_QUEST", None)

import pytest  # noqa: E402

from questlog import bindings, config as cfgmod  # noqa: E402
from questlog.scribe import core  # noqa: E402

TOML = """root = "{root}"
human = "GM"

[[factions]]
id = "lab"
name = "Lab"
workflow = "polly"
review = "cross-vendor"
arcs = [
  {{ id = "relaxed", name = "Relaxed", workflow = "debby", review = "none" }},
  {{ id = "inherits", name = "Inherits" }},
]

[[factions]]
id = "plain"
name = "Plain"
arcs = [{{ id = "routed", name = "Routed", workflow = "claude", review = "cross-vendor" }}]
"""


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    root = tmp_path / "quests"
    root.mkdir()
    path = tmp_path / "questlog.toml"
    path.write_text(TOML.format(root=root))
    monkeypatch.setenv("QUESTLOG_CONFIG", str(path))
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(bindings, "FILE", state / "bindings.json")
    monkeypatch.setattr(core, "STATE", state / "scribe")
    monkeypatch.setattr(core, "LOG", state / "scribe.log")
    return cfgmod.load(path)

