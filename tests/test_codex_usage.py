"""Tests for reading Codex's own quota status."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

import omnigent.codex_usage as codex_usage
from omnigent.codex_native_app_server import CodexAppServerResponseError
from omnigent.onboarding.provider_usage import UsageState

# The shape the Codex app-server actually answers ``account/rateLimits/read``
# with, captured from a live probe.
_LIVE_RATE_LIMITS: dict[str, Any] = {
    "limitId": "codex",
    "limitName": None,
    "primary": {"usedPercent": 100, "windowDurationMins": 300, "resetsAt": 1788122499},
    "secondary": {"usedPercent": 47, "windowDurationMins": 10080, "resetsAt": 1788644313},
    "credits": {"hasCredits": False, "unlimited": False, "balance": "0"},
    "individualLimit": None,
    "spendControlReached": False,
    "planType": "plus",
    "rateLimitReachedType": "rate_limit_reached",
}


def test_live_payload_maps_to_labelled_windows() -> None:
    status = codex_usage.codex_usage_from_rate_limits("codex", _LIVE_RATE_LIMITS)

    assert status.state is UsageState.EXHAUSTED
    assert status.plan == "plus"
    assert [(w.window_id, w.label, w.used_percent, w.resets_at) for w in status.windows] == [
        ("primary", "5-hour limit", 100.0, 1788122499),
        ("secondary", "Weekly limit", 47.0, 1788644313),
    ]
    assert status.checked_at > 0


def test_windows_without_a_percentage_are_dropped_not_defaulted() -> None:
    # A window Codex reports without a number must not become "0% used".
    payload = {"primary": {"windowDurationMins": 300}, "secondary": {"usedPercent": 10}}

    status = codex_usage.codex_usage_from_rate_limits("codex", payload)

    assert [w.window_id for w in status.windows] == ["secondary"]
    assert status.state is UsageState.AVAILABLE


def test_no_reported_limits_says_so_instead_of_showing_zero() -> None:
    status = codex_usage.codex_usage_from_rate_limits("codex", {})

    assert status.state is UsageState.UNKNOWN
    assert status.windows == ()
    assert status.message == "Codex did not report any limit for this account."


def test_exhausted_account_with_credits_says_work_can_continue() -> None:
    payload = dict(_LIVE_RATE_LIMITS, credits={"hasCredits": True, "unlimited": False})

    status = codex_usage.codex_usage_from_rate_limits("codex", payload)

    assert status.state is UsageState.EXHAUSTED
    assert status.message == "Credits are available to continue past the limit."


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    codex_usage._usage_cache.clear()


def _patch_readiness(monkeypatch: pytest.MonkeyPatch, reason: str | None) -> None:
    monkeypatch.setattr(
        "omnigent.codex_native._codex_auth_unavailable_reason",
        lambda: reason,
    )
    monkeypatch.setattr("omnigent.codex_native._find_codex_cli", lambda: "/usr/bin/codex")


def test_missing_cli_is_reported_without_starting_a_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_readiness(monkeypatch, "binary-missing")

    def _must_not_run(**_kwargs: object) -> dict[str, Any]:
        raise AssertionError("the probe must not start when the CLI is absent")

    monkeypatch.setattr(codex_usage, "read_codex_rate_limits", _must_not_run)

    status = asyncio.run(codex_usage.codex_usage_status("codex"))

    assert status.state is UsageState.PROVIDER_UNAVAILABLE


def test_unauthenticated_cli_is_reported_without_starting_a_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_readiness(monkeypatch, "needs-auth")

    def _must_not_run(**_kwargs: object) -> dict[str, Any]:
        raise AssertionError("the probe must not start without a credential")

    monkeypatch.setattr(codex_usage, "read_codex_rate_limits", _must_not_run)

    status = asyncio.run(codex_usage.codex_usage_status("codex"))

    assert status.state is UsageState.AUTHENTICATION_REQUIRED
    assert status.windows == ()


def test_a_second_read_is_served_from_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_readiness(monkeypatch, None)
    calls = 0

    async def _probe(**_kwargs: object) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return _LIVE_RATE_LIMITS

    monkeypatch.setattr(codex_usage, "read_codex_rate_limits", _probe)

    async def _read_twice() -> tuple[float, float]:
        first = await codex_usage.codex_usage_status("codex")
        second = await codex_usage.codex_usage_status("codex")
        return first.checked_at, second.checked_at

    first_checked, second_checked = asyncio.run(_read_twice())

    assert calls == 1
    # The cached reading keeps its original timestamp so staleness stays visible.
    assert first_checked == second_checked


def test_refresh_bypasses_the_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_readiness(monkeypatch, None)
    calls = 0

    async def _probe(**_kwargs: object) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return _LIVE_RATE_LIMITS

    monkeypatch.setattr(codex_usage, "read_codex_rate_limits", _probe)

    async def _read() -> None:
        await codex_usage.codex_usage_status("codex")
        await codex_usage.codex_usage_status("codex", refresh=True)

    asyncio.run(_read())

    assert calls == 2


def test_an_older_codex_without_the_method_reports_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_readiness(monkeypatch, None)

    async def _probe(**_kwargs: object) -> dict[str, Any]:
        raise CodexAppServerResponseError({"code": -32600, "message": "unknown variant"})

    monkeypatch.setattr(codex_usage, "read_codex_rate_limits", _probe)

    status = asyncio.run(codex_usage.codex_usage_status("codex"))

    assert status.state is UsageState.UNKNOWN
    assert status.message == "This version of the codex CLI does not report usage limits."


def test_a_crashing_probe_still_settles(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_readiness(monkeypatch, None)

    async def _probe(**_kwargs: object) -> dict[str, Any]:
        raise TimeoutError("probe hung")

    monkeypatch.setattr(codex_usage, "read_codex_rate_limits", _probe)

    status = asyncio.run(codex_usage.codex_usage_status("codex"))

    assert status.state is UsageState.UNKNOWN
    assert status.message == "The Codex usage probe failed on this host."


def test_cache_ttl_is_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OMNIGENT_PROVIDER_USAGE_TTL_S", "12.5")
    assert codex_usage._cache_ttl_seconds() == 12.5

    monkeypatch.setenv("OMNIGENT_PROVIDER_USAGE_TTL_S", "not-a-number")
    assert codex_usage._cache_ttl_seconds() == codex_usage._DEFAULT_CACHE_TTL_S

    monkeypatch.setenv("OMNIGENT_PROVIDER_USAGE_TTL_S", "0")
    assert codex_usage._cache_ttl_seconds() == codex_usage._DEFAULT_CACHE_TTL_S


def test_two_accounts_do_not_share_a_cached_reading(monkeypatch: pytest.MonkeyPatch) -> None:
    """A second profile must never be shown the first profile's quota."""
    _patch_readiness(monkeypatch, None)
    homes: list[str | None] = []

    async def _probe(*, codex_path: str, codex_home: str | None = None) -> dict[str, Any]:
        homes.append(codex_home)
        return dict(_LIVE_RATE_LIMITS, planType="plus" if codex_home else "free")

    monkeypatch.setattr(codex_usage, "read_codex_rate_limits", _probe)

    async def _read_both() -> tuple[str | None, str | None]:
        personal = await codex_usage.codex_usage_status("codex")
        work = await codex_usage.codex_usage_status("codex-work", codex_home="/home/u/.codex-work")
        return personal.plan, work.plan

    personal_plan, work_plan = asyncio.run(_read_both())

    assert homes == [None, "/home/u/.codex-work"]
    assert (personal_plan, work_plan) == ("free", "plus")
