"""A per-session provider pin must decide which account a launch runs on."""

from __future__ import annotations

from pathlib import Path

import pytest

import omnigent.codex_native_app_server as app_server
from omnigent.provider_override import validate_provider_override


@pytest.mark.parametrize("value", ["codex", "codex-work", "db.gateway", "a_b-1"])
def test_valid_provider_names_pass(value: str) -> None:
    assert validate_provider_override(f"  {value}  ") == value


@pytest.mark.parametrize(
    "value",
    ["", "   ", "--model", "-flag", "../etc/passwd", "a b", "codex;rm -rf /", "a" * 200],
)
def test_shell_and_path_shaped_names_are_rejected(value: str) -> None:
    # The pin is persisted and resolved at launch, so it must stay data-only.
    with pytest.raises(ValueError):
        validate_provider_override(value)


def _config(**providers: object) -> dict[str, object]:
    return {"providers": dict(providers)}


def test_a_pinned_subscription_launches_on_its_own_account(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work_home = tmp_path / "codex-work"
    work_home.mkdir()
    (work_home / "auth.json").write_text("{}")
    seen: list[Path] = []

    def _has_credential(path: Path) -> bool:
        seen.append(path)
        return True

    monkeypatch.setattr("omnigent.onboarding.ambient.codex_auth_has_credential", _has_credential)
    config = _config(
        codex={"kind": "subscription", "cli": "codex", "default": "openai"},
        **{"codex-work": {"kind": "subscription", "cli": "codex", "cli_home": str(work_home)}},
    )

    launch = app_server._pinned_codex_launch(config, "codex-work", None)

    assert launch is not None
    assert launch.cli_home == str(work_home)
    assert "codex-work" in launch.summary
    # Ambient detection also probes the default home; what matters is that the
    # launch decision was taken against the pinned account's own auth.json.
    assert seen[-1] == work_home / "auth.json"


def test_a_pinned_gateway_routes_through_its_own_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OMNIGENT_TEST_PIN_KEY", "sk-pinned")
    config = _config(
        work={
            "kind": "gateway",
            "openai": {
                "base_url": "https://gateway.example/v1",
                "api_key_ref": "env:OMNIGENT_TEST_PIN_KEY",
                "models": {"default": "pinned-model"},
            },
        }
    )

    launch = app_server._pinned_codex_launch(config, "work", None)

    assert launch is not None
    assert launch.model == "pinned-model"
    assert "pinned provider 'work'" in launch.summary


def test_an_unknown_pin_falls_back_instead_of_stranding_the_session(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The pin was shape-validated by a server that cannot see this host."""
    config = _config(codex={"kind": "subscription", "cli": "codex"})

    with caplog.at_level("WARNING"):
        assert app_server._pinned_codex_launch(config, "codex-ghost", None) is None

    assert "codex-ghost" in caplog.text


def test_a_pin_that_cannot_route_falls_back_and_says_so(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("OMNIGENT_TEST_MISSING_PIN_KEY", raising=False)
    config = _config(
        work={
            "kind": "gateway",
            "openai": {
                "base_url": "https://gateway.example/v1",
                "api_key_ref": "env:OMNIGENT_TEST_MISSING_PIN_KEY",
            },
        }
    )

    with caplog.at_level("WARNING"):
        assert app_server._pinned_codex_launch(config, "work", None) is None

    assert "cannot route" in caplog.text


def test_a_pinned_subscription_is_never_swapped_for_another_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The machine-default path substitutes on a logged-out subscription.

    A pin must not: the user named this account, so a silent switch to a
    different credential is worse than the sign-in screen.
    """
    work_home = tmp_path / "codex-work"
    work_home.mkdir()
    monkeypatch.setattr(
        "omnigent.onboarding.ambient.codex_auth_has_credential", lambda _path: False
    )
    monkeypatch.setenv("OMNIGENT_TEST_OTHER_KEY", "sk-other")
    config = _config(
        **{"codex-work": {"kind": "subscription", "cli": "codex", "cli_home": str(work_home)}},
        other={
            "kind": "gateway",
            "openai": {
                "base_url": "https://other.example/v1",
                "api_key_ref": "env:OMNIGENT_TEST_OTHER_KEY",
            },
        },
    )

    launch = app_server._pinned_codex_launch(config, "codex-work", None)

    assert launch is not None
    assert launch.cli_home == str(work_home)
    assert "not logged in" in launch.summary
    assert "other" not in launch.summary


def test_no_pin_leaves_resolution_exactly_as_before(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        app_server,
        "_pinned_codex_launch",
        lambda *a, **k: calls.append("called") or None,  # type: ignore[func-returns-value]
    )
    monkeypatch.setattr(app_server, "load_config", dict, raising=False)

    app_server.resolve_native_codex_launch(model=None)

    assert calls == []
