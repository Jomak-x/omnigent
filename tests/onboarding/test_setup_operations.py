from pathlib import Path

import pytest

from omnigent import cli_config
from omnigent.config import load_global_config, save_global_config
from omnigent.onboarding import interactive
from omnigent.onboarding.acp_auth import acp_agents
from omnigent.onboarding.setup_operations import acp_entries_settings


@pytest.mark.parametrize("command", ["fixture --acp", "another-fixture --acp"])
def test_cli_adds_same_name_acp_occurrences(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    monkeypatch.setenv("OMNIGENT_CONFIG_HOME", str(tmp_path))
    existing = {
        "name": "Fixture",
        "command": "fixture --acp",
        "future": {"retained": True},
    }
    save_global_config({"acp": {"future": True, "agents": [existing]}})
    answers = iter(["Fixture", command, "fixture-model"])
    monkeypatch.setattr(interactive, "prompt_text", lambda *a, **kw: next(answers))
    monkeypatch.setattr(cli_config, "_print_acp_examples", lambda: None)

    cli_config._add_acp_agent()

    config = load_global_config()
    assert config["acp"] == {
        "future": True,
        "agents": [
            existing,
            {"name": "Fixture", "command": command, "model": "fixture-model"},
        ],
    }
    entries = acp_agents(config)
    assert [entry.slug for entry in entries] == ["fixture", "fixture-2"]
    save_global_config(acp_entries_settings(config, entries[:1]))
    assert load_global_config()["acp"] == {"future": True, "agents": [existing]}
