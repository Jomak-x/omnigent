"""Tests for provider failover policy and selection."""

from __future__ import annotations

import pytest

from omnigent.errors import OmnigentError
from omnigent.onboarding.provider_inventory import ConnectionState
from omnigent.onboarding.provider_routing import (
    ProviderRoutingPolicy,
    ProviderSignals,
    RoutingTrigger,
    load_routing_policies,
    select_provider,
)
from omnigent.onboarding.provider_usage import UsageState


def _policy(*order: str, triggers: frozenset[RoutingTrigger] | None = None):
    kwargs = {"triggers": triggers} if triggers is not None else {}
    return ProviderRoutingPolicy(harness="codex-native", order=tuple(order), **kwargs)


def _ok() -> ProviderSignals:
    return ProviderSignals(ConnectionState.CONNECTED, UsageState.AVAILABLE)


def _exhausted() -> ProviderSignals:
    return ProviderSignals(ConnectionState.CONNECTED, UsageState.EXHAUSTED)


# --- rule 1: an explicit pin is never overridden -------------------------


def test_a_pin_wins_even_over_an_exhausted_account() -> None:
    """The user named this account; moving them off it silently is the bug."""
    selection = select_provider(
        _policy("codex", "codex-work"),
        {"codex": _exhausted(), "codex-work": _ok()},
        pinned="codex",
    )

    assert selection is not None
    assert selection.provider == "codex"
    assert selection.moved_from is None


def test_a_pin_applies_with_no_policy_at_all() -> None:
    selection = select_provider(None, {}, pinned="codex-work")

    assert selection is not None
    assert selection.provider == "codex-work"


# --- rule 3: no policy, no failover --------------------------------------


def test_without_a_policy_nothing_is_decided() -> None:
    assert select_provider(None, {"codex": _exhausted()}) is None
    assert select_provider(_policy(), {"codex": _exhausted()}) is None


# --- the move itself ------------------------------------------------------


def test_an_exhausted_first_choice_moves_to_the_next_account() -> None:
    selection = select_provider(
        _policy("codex", "codex-work"),
        {"codex": _exhausted(), "codex-work": _ok()},
    )

    assert selection is not None
    assert selection.provider == "codex-work"
    assert selection.moved_from == "codex"
    assert selection.reason == (
        "codex has used its whole quota; this session runs on codex-work instead."
    )


def test_a_healthy_first_choice_is_used_with_no_reason_to_report() -> None:
    selection = select_provider(
        _policy("codex", "codex-work"), {"codex": _ok(), "codex-work": _ok()}
    )

    assert selection is not None
    assert selection.provider == "codex"
    assert selection.moved_from is None
    assert selection.reason is None


def test_a_signed_out_account_is_moved_past() -> None:
    selection = select_provider(
        _policy("codex", "codex-work"),
        {
            "codex": ProviderSignals(ConnectionState.AUTHENTICATION_REQUIRED),
            "codex-work": _ok(),
        },
    )

    assert selection is not None
    assert selection.provider == "codex-work"
    assert "not signed in" in (selection.reason or "")


# --- rule 2: only a reported signal counts --------------------------------


def test_an_unknown_account_is_tried_not_skipped() -> None:
    """Silence is not exhaustion — a provider reporting nothing gets the work."""
    selection = select_provider(
        _policy("codex", "codex-work"),
        {"codex": ProviderSignals(ConnectionState.UNKNOWN, None), "codex-work": _ok()},
    )

    assert selection is not None
    assert selection.provider == "codex"


def test_a_candidate_with_no_signals_at_all_is_tried() -> None:
    selection = select_provider(_policy("codex", "codex-work"), {})

    assert selection is not None
    assert selection.provider == "codex"


def test_nearly_exhausted_only_moves_when_the_policy_asks_for_it() -> None:
    signals = {
        "codex": ProviderSignals(ConnectionState.CONNECTED, UsageState.NEARLY_EXHAUSTED),
        "codex-work": _ok(),
    }

    default_policy = select_provider(_policy("codex", "codex-work"), signals)
    assert default_policy is not None
    assert default_policy.provider == "codex"

    eager = select_provider(
        _policy(
            "codex",
            "codex-work",
            triggers=frozenset({RoutingTrigger.QUOTA_NEARLY_EXHAUSTED}),
        ),
        signals,
    )
    assert eager is not None
    assert eager.provider == "codex-work"


def test_every_candidate_spent_still_launches_on_the_first() -> None:
    # Refusing to launch would be worse: the account's own limit error is a
    # clearer outcome than Omnigent declining to start.
    selection = select_provider(
        _policy("codex", "codex-work"),
        {"codex": _exhausted(), "codex-work": _exhausted()},
    )

    assert selection is not None
    assert selection.provider == "codex"
    assert selection.moved_from is None


# --- policy parsing -------------------------------------------------------


def test_a_missing_block_means_no_failover() -> None:
    assert load_routing_policies({}) == {}


def test_a_policy_parses_its_order_and_triggers() -> None:
    policies = load_routing_policies(
        {
            "provider_routing": {
                "codex-native": {
                    "order": ["codex", "codex-work"],
                    "on": ["quota_exhausted", "authentication_required"],
                }
            }
        }
    )

    policy = policies["codex-native"]
    assert policy.order == ("codex", "codex-work")
    assert policy.triggers == frozenset(
        {RoutingTrigger.QUOTA_EXHAUSTED, RoutingTrigger.AUTHENTICATION_REQUIRED}
    )


def test_a_policy_without_triggers_uses_the_unambiguous_defaults() -> None:
    policies = load_routing_policies(
        {"provider_routing": {"codex-native": {"order": ["codex", "codex-work"]}}}
    )

    assert policies["codex-native"].triggers == frozenset(
        {
            RoutingTrigger.QUOTA_EXHAUSTED,
            RoutingTrigger.AUTHENTICATION_REQUIRED,
            RoutingTrigger.PROVIDER_UNAVAILABLE,
        }
    )


@pytest.mark.parametrize(
    "block",
    [
        {"provider_routing": []},
        {"provider_routing": {"codex-native": ["codex"]}},
        {"provider_routing": {"codex-native": {}}},
        {"provider_routing": {"codex-native": {"order": []}}},
        {"provider_routing": {"codex-native": {"order": [5]}}},
        {"provider_routing": {"codex-native": {"order": ["codex"], "on": ["nonsense"]}}},
        {"provider_routing": {"codex-native": {"order": ["codex"], "on": []}}},
    ],
)
def test_a_malformed_policy_fails_loud(block: dict[str, object]) -> None:
    # A silently ignored typo would leave the user believing failover is on.
    with pytest.raises(OmnigentError):
        load_routing_policies(block)
