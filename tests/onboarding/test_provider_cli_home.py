"""Tests for per-provider CLI credential homes — the multi-profile primitive."""

from __future__ import annotations

from pathlib import Path

import pytest

from omnigent.errors import OmnigentError
from omnigent.onboarding.provider_config import load_providers, provider_cli_home
from omnigent.onboarding.provider_inventory import (
    CapabilitySupport,
    ConnectionState,
    build_provider_inventory,
    provider_capabilities,
)


def _providers(raw: dict[str, object]) -> dict[str, object]:
    return {"providers": raw}


def test_two_subscriptions_of_one_cli_can_name_different_homes() -> None:
    """The whole point: two Codex accounts, two credential roots."""
    parsed = load_providers(
        _providers(
            {
                "codex-personal": {"kind": "subscription", "cli": "codex"},
                "codex-work": {
                    "kind": "subscription",
                    "cli": "codex",
                    "cli_home": "~/.codex-work",
                },
            }
        )
    )

    assert provider_cli_home(parsed["codex-personal"]) is None
    assert provider_cli_home(parsed["codex-work"]) == Path.home() / ".codex-work"


def test_a_cli_config_provider_can_name_its_own_home() -> None:
    parsed = load_providers(
        _providers(
            {
                "gateway": {
                    "kind": "cli-config",
                    "cli": "codex",
                    "model_provider": "Databricks",
                    "cli_home": "/opt/codex-home",
                }
            }
        )
    )

    assert provider_cli_home(parsed["gateway"]) == Path("/opt/codex-home")


def test_environment_variables_resolve_at_use_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OMNIGENT_TEST_CODEX_ROOT", "/srv/accounts")
    parsed = load_providers(
        _providers(
            {
                "codex-work": {
                    "kind": "subscription",
                    "cli": "codex",
                    "cli_home": "$OMNIGENT_TEST_CODEX_ROOT/work",
                }
            }
        )
    )

    # The raw value round-trips; only the resolved path is expanded.
    assert parsed["codex-work"].cli_home == "$OMNIGENT_TEST_CODEX_ROOT/work"
    assert provider_cli_home(parsed["codex-work"]) == Path("/srv/accounts/work")


def test_an_unset_variable_fails_loud_rather_than_using_the_wrong_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OMNIGENT_TEST_CODEX_ROOT", raising=False)
    parsed = load_providers(
        _providers(
            {
                "codex-work": {
                    "kind": "subscription",
                    "cli": "codex",
                    "cli_home": "$OMNIGENT_TEST_CODEX_ROOT/work",
                }
            }
        )
    )

    with pytest.raises(OmnigentError):
        provider_cli_home(parsed["codex-work"])


@pytest.mark.parametrize("value", ["", "   ", 5, []])
def test_a_malformed_home_is_rejected_at_parse(value: object) -> None:
    # Silently ignoring a typo here would authenticate as the wrong account.
    with pytest.raises(OmnigentError):
        load_providers(
            _providers({"codex-work": {"kind": "subscription", "cli": "codex", "cli_home": value}})
        )


def test_a_provider_without_a_home_is_unchanged() -> None:
    parsed = load_providers(_providers({"codex": {"kind": "subscription", "cli": "codex"}}))

    assert parsed["codex"].cli_home is None
    assert provider_cli_home(parsed["codex"]) is None


def test_codex_providers_now_advertise_multiple_profiles() -> None:
    parsed = load_providers(
        _providers(
            {
                "codex": {"kind": "subscription", "cli": "codex"},
                "claude": {"kind": "subscription", "cli": "claude"},
            }
        )
    )

    # Codex launches honour a per-provider home; claude's does not yet, and
    # claiming otherwise would promise an account switch that never happens.
    assert provider_capabilities(parsed["codex"]).multiple_profiles is CapabilitySupport.SUPPORTED
    assert (
        provider_capabilities(parsed["claude"]).multiple_profiles is CapabilitySupport.UNSUPPORTED
    )


def test_the_resolved_home_never_crosses_the_wire() -> None:
    config: dict[str, object] = _providers(
        {"codex-work": {"kind": "subscription", "cli": "codex", "cli_home": "~/.codex-work"}}
    )

    [row] = build_provider_inventory(config, detected=[], harness_readiness={"codex-native": True})

    assert row.cli_home == str(Path.home() / ".codex-work")
    assert "cli_home" not in row.as_dict()


def test_an_unresolvable_home_reads_as_misconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OMNIGENT_TEST_CODEX_ROOT", raising=False)
    config: dict[str, object] = _providers(
        {
            "codex-work": {
                "kind": "subscription",
                "cli": "codex",
                "cli_home": "$OMNIGENT_TEST_CODEX_ROOT/work",
            }
        }
    )

    [row] = build_provider_inventory(config, detected=[], harness_readiness={"codex-native": True})

    assert row.connection_state is ConnectionState.MISCONFIGURED
    assert row.cli_home is None
