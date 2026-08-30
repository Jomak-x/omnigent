"""Tests for the launch-time provider selection that applies the policy."""

from __future__ import annotations

import asyncio

import pytest

import omnigent.provider_selection as selection_mod
from omnigent.onboarding.provider_inventory import (
    CapabilitySupport,
    ConnectionState,
    ProviderCapabilities,
    ProviderInventoryEntry,
)
from omnigent.onboarding.provider_usage import ProviderUsageStatus, UsageState


def _capabilities(usage: CapabilitySupport) -> ProviderCapabilities:
    return ProviderCapabilities(
        model_discovery=CapabilitySupport.SUPPORTED,
        usage_status=usage,
        multiple_profiles=CapabilitySupport.SUPPORTED,
        interactive_cli=CapabilitySupport.SUPPORTED,
    )


def _row(
    provider_id: str,
    *,
    state: ConnectionState = ConnectionState.CONNECTED,
    usage: CapabilitySupport = CapabilitySupport.SUPPORTED,
    cli: str | None = "codex",
    cli_home: str | None = None,
) -> ProviderInventoryEntry:
    return ProviderInventoryEntry(
        provider_id=provider_id,
        display_name=provider_id,
        kind="subscription",
        origin="configured",
        source="config",
        configuration_state="valid",
        error=None,
        families=("openai",),
        surfaces=("openai",),
        default_for=(),
        default_models={},
        cli=cli,
        profile=None,
        model_provider=None,
        capabilities=_capabilities(usage),
        connection_state=state,
        connection_detail="",
        cli_home=cli_home,
    )


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    config: dict[str, object],
    rows: list[ProviderInventoryEntry],
    usage: dict[str, UsageState] | None = None,
) -> list[tuple[str, str | None]]:
    probes: list[tuple[str, str | None]] = []
    monkeypatch.setattr("omnigent.onboarding.provider_config.load_config", lambda: config)
    monkeypatch.setattr(selection_mod, "build_provider_inventory", lambda _config: rows)

    async def _usage_status(
        provider_id: str, *, refresh: bool = False, codex_home: str | None = None
    ) -> ProviderUsageStatus:
        probes.append((provider_id, codex_home))
        return ProviderUsageStatus(
            provider_id=provider_id,
            state=(usage or {}).get(provider_id, UsageState.AVAILABLE),
        )

    monkeypatch.setattr("omnigent.codex_usage.codex_usage_status", _usage_status)
    return probes


_POLICY: dict[str, object] = {
    "provider_routing": {"codex-native": {"order": ["codex", "codex-work"]}}
}


def test_no_policy_means_no_selection_and_no_probes(monkeypatch: pytest.MonkeyPatch) -> None:
    """A machine without failover configured must pay nothing for it."""
    probes = _install(monkeypatch, config={}, rows=[_row("codex")])

    assert asyncio.run(selection_mod.choose_provider_for_harness("codex-native")) is None
    assert probes == []


def test_a_pin_short_circuits_before_any_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    probes = _install(monkeypatch, config=_POLICY, rows=[_row("codex"), _row("codex-work")])

    result = asyncio.run(
        selection_mod.choose_provider_for_harness("codex-native", pinned="codex-work")
    )

    assert result is not None
    assert result.provider == "codex-work"
    assert probes == []


def test_an_exhausted_account_moves_the_session(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        config=_POLICY,
        rows=[_row("codex"), _row("codex-work", cli_home="/home/u/.codex-work")],
        usage={"codex": UsageState.EXHAUSTED},
    )

    result = asyncio.run(selection_mod.choose_provider_for_harness("codex-native"))

    assert result is not None
    assert result.provider == "codex-work"
    assert result.moved_from == "codex"
    assert "quota" in (result.reason or "")


def test_each_account_is_probed_against_its_own_home(monkeypatch: pytest.MonkeyPatch) -> None:
    probes = _install(
        monkeypatch,
        config=_POLICY,
        rows=[_row("codex"), _row("codex-work", cli_home="/home/u/.codex-work")],
        usage={"codex": UsageState.EXHAUSTED},
    )

    asyncio.run(selection_mod.choose_provider_for_harness("codex-native"))

    assert probes == [("codex", None), ("codex-work", "/home/u/.codex-work")]


def test_a_provider_that_reports_no_usage_is_never_probed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probes = _install(
        monkeypatch,
        config=_POLICY,
        rows=[
            _row("codex", usage=CapabilitySupport.UNSUPPORTED),
            _row("codex-work", cli=None, usage=CapabilitySupport.UNSUPPORTED),
        ],
    )

    result = asyncio.run(selection_mod.choose_provider_for_harness("codex-native"))

    assert probes == []
    assert result is not None
    assert result.provider == "codex"


def test_a_policy_naming_a_missing_provider_moves_past_it(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _install(monkeypatch, config=_POLICY, rows=[_row("codex-work")])

    with caplog.at_level("WARNING"):
        result = asyncio.run(selection_mod.choose_provider_for_harness("codex-native"))

    assert result is not None
    assert result.provider == "codex-work"
    assert "does not have" in caplog.text


def test_a_routing_failure_falls_back_to_the_default_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Routing must never be the reason a session cannot start."""

    def _explode() -> dict[str, object]:
        raise RuntimeError("config is on fire")

    monkeypatch.setattr("omnigent.onboarding.provider_config.load_config", _explode)

    assert asyncio.run(selection_mod.choose_provider_for_harness("codex-native")) is None
