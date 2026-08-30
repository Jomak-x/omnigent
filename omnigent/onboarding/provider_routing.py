"""Provider failover policy: which account runs the work when one is spent.

Three rules govern everything here, and each exists because the opposite would
be worse than no failover at all:

1. **An explicit pin is never overridden.** A user who named an account gets
   that account, exhausted or not. Automatic routing is for the unpinned case.
2. **A move needs a reason the provider actually reported.** A candidate is
   skipped only on a signal Omnigent has — a connection state, or a usage
   reading the vendor itself produced. "Unknown" never counts as "spent", so a
   provider that reports nothing is tried rather than skipped.
3. **Order is configured, never guessed.** Without a policy there is no
   failover; with one, candidates are tried in the order the user wrote.

Cross-provider failover is not a special case here: the policy names providers,
so moving between two Codex accounts and moving from Codex to a gateway are the
same mechanism. What the policy cannot do is change the *model*, which is why
the selection returns a provider name only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from omnigent.errors import ErrorCode, OmnigentError
from omnigent.onboarding.provider_inventory import ConnectionState
from omnigent.onboarding.provider_usage import UsageState

_logger = logging.getLogger(__name__)

ROUTING_CONFIG_KEY = "provider_routing"


class RoutingTrigger(str, Enum):
    """A condition that makes the policy skip a candidate."""

    QUOTA_EXHAUSTED = "quota_exhausted"
    QUOTA_NEARLY_EXHAUSTED = "quota_nearly_exhausted"
    AUTHENTICATION_REQUIRED = "authentication_required"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    MISCONFIGURED = "misconfigured"


# What a policy skips on when it names no triggers of its own: the two states
# that mean "this account cannot do the work right now" without ambiguity.
_DEFAULT_TRIGGERS: frozenset[RoutingTrigger] = frozenset(
    {
        RoutingTrigger.QUOTA_EXHAUSTED,
        RoutingTrigger.AUTHENTICATION_REQUIRED,
        RoutingTrigger.PROVIDER_UNAVAILABLE,
    }
)


@dataclass(frozen=True)
class ProviderRoutingPolicy:
    """One harness's ordered candidates and the reasons to move past them.

    :param harness: The harness this policy routes, e.g. ``"codex-native"``.
    :param order: Provider names to try, in order.
    :param triggers: Conditions that skip a candidate.
    """

    harness: str
    order: tuple[str, ...]
    triggers: frozenset[RoutingTrigger] = _DEFAULT_TRIGGERS


@dataclass(frozen=True)
class ProviderSignals:
    """What is locally known about one candidate at selection time.

    :param connection_state: The provider's settled connection state.
    :param usage_state: The vendor-reported quota state, or ``None`` when this
        provider reports no usage at all (which is not a reason to skip it).
    """

    connection_state: ConnectionState
    usage_state: UsageState | None = None


@dataclass(frozen=True)
class ProviderSelection:
    """The chosen provider and why it was chosen.

    :param provider: The provider that should run the work.
    :param moved_from: The candidate the policy skipped past, when it skipped
        one; ``None`` when the first choice was usable.
    :param reason: A non-secret sentence naming the trigger, for the log and
        for anything the user is shown.
    """

    provider: str
    moved_from: str | None = None
    reason: str | None = None


def _trigger_for(signals: ProviderSignals) -> RoutingTrigger | None:
    """Return the condition that disqualifies a candidate, if any."""
    if signals.usage_state is UsageState.EXHAUSTED:
        return RoutingTrigger.QUOTA_EXHAUSTED
    if signals.usage_state is UsageState.NEARLY_EXHAUSTED:
        return RoutingTrigger.QUOTA_NEARLY_EXHAUSTED
    if signals.connection_state is ConnectionState.AUTHENTICATION_REQUIRED:
        return RoutingTrigger.AUTHENTICATION_REQUIRED
    if signals.usage_state is UsageState.AUTHENTICATION_REQUIRED:
        return RoutingTrigger.AUTHENTICATION_REQUIRED
    if signals.connection_state is ConnectionState.UNAVAILABLE:
        return RoutingTrigger.PROVIDER_UNAVAILABLE
    if signals.usage_state is UsageState.PROVIDER_UNAVAILABLE:
        return RoutingTrigger.PROVIDER_UNAVAILABLE
    if signals.connection_state is ConnectionState.MISCONFIGURED:
        return RoutingTrigger.MISCONFIGURED
    return None


_TRIGGER_SENTENCE: dict[RoutingTrigger, str] = {
    RoutingTrigger.QUOTA_EXHAUSTED: "has used its whole quota",
    RoutingTrigger.QUOTA_NEARLY_EXHAUSTED: "has nearly used its quota",
    RoutingTrigger.AUTHENTICATION_REQUIRED: "is not signed in",
    RoutingTrigger.PROVIDER_UNAVAILABLE: "is unavailable on this host",
    RoutingTrigger.MISCONFIGURED: "is misconfigured",
}


def select_provider(
    policy: ProviderRoutingPolicy | None,
    signals: dict[str, ProviderSignals],
    *,
    pinned: str | None = None,
) -> ProviderSelection | None:
    """Choose the provider to run the work.

    :param policy: The routing policy for this harness, or ``None``.
    :param signals: Per-candidate local knowledge, keyed by provider name. A
        candidate absent from this mapping is treated as unknown, and unknown
        is usable — never skip on missing information.
    :param pinned: An explicit per-session pin, which always wins.
    :returns: The selection, or ``None`` when there is nothing to decide (no
        policy, or an empty order) and the caller should keep its own default.
    """
    if pinned is not None:
        # Rule 1. Not even an exhausted pin is second-guessed: the user asked
        # for this account, and moving them off it silently is the failure mode
        # this whole design exists to avoid.
        return ProviderSelection(provider=pinned)
    if policy is None or not policy.order:
        return None
    skipped: list[tuple[str, RoutingTrigger]] = []
    for candidate in policy.order:
        trigger = _trigger_for(signals.get(candidate, ProviderSignals(ConnectionState.UNKNOWN)))
        if trigger is not None and trigger in policy.triggers:
            skipped.append((candidate, trigger))
            continue
        if not skipped:
            return ProviderSelection(provider=candidate)
        moved_from, moved_trigger = skipped[0]
        return ProviderSelection(
            provider=candidate,
            moved_from=moved_from,
            reason=(
                f"{moved_from} {_TRIGGER_SENTENCE[moved_trigger]}; "
                f"this session runs on {candidate} instead."
            ),
        )
    # Every candidate is disqualified. Fall back to the first one rather than
    # refusing to launch: an exhausted account that reports its own limit is
    # still the user's best guess, and its failure will be explicit.
    first, first_trigger = skipped[0]
    _logger.warning(
        "provider routing: every candidate for %s is unusable (%s %s); using %s anyway.",
        policy.harness,
        first,
        first_trigger.value,
        first,
    )
    return ProviderSelection(provider=first)


def _parse_triggers(harness: str, raw: object) -> frozenset[RoutingTrigger]:
    """Parse a policy's ``on:`` list, failing loud on an unknown trigger."""
    if raw is None:
        return _DEFAULT_TRIGGERS
    if not isinstance(raw, list) or not raw:
        raise OmnigentError(
            f"provider_routing.{harness}: 'on' must be a non-empty list of triggers.",
            code=ErrorCode.INVALID_INPUT,
        )
    triggers: set[RoutingTrigger] = set()
    for item in raw:
        try:
            triggers.add(RoutingTrigger(str(item)))
        except ValueError as exc:
            valid = ", ".join(sorted(t.value for t in RoutingTrigger))
            raise OmnigentError(
                f"provider_routing.{harness}: unknown trigger {item!r}; expected one of {valid}.",
                code=ErrorCode.INVALID_INPUT,
            ) from exc
    return frozenset(triggers)


def load_routing_policies(config: dict[str, object]) -> dict[str, ProviderRoutingPolicy]:
    """Parse the ``provider_routing:`` block into per-harness policies.

    A missing block means no failover anywhere, which is the behaviour of every
    config written before this existed.

    :param config: The effective Omnigent config.
    :returns: Policies keyed by harness id.
    :raises OmnigentError: On a malformed policy — a silently ignored typo here
        would leave a user believing failover is configured when it is not.
    """
    raw_block = config.get(ROUTING_CONFIG_KEY)
    if raw_block is None:
        return {}
    if not isinstance(raw_block, dict):
        raise OmnigentError(
            f"'{ROUTING_CONFIG_KEY}' must be a mapping of harness to routing policy.",
            code=ErrorCode.INVALID_INPUT,
        )
    policies: dict[str, ProviderRoutingPolicy] = {}
    for raw_harness, raw_policy in raw_block.items():
        harness = str(raw_harness)
        if not isinstance(raw_policy, dict):
            raise OmnigentError(
                f"provider_routing.{harness}: must be a mapping with an 'order' list.",
                code=ErrorCode.INVALID_INPUT,
            )
        raw_order = raw_policy.get("order")
        if not isinstance(raw_order, list) or not raw_order:
            raise OmnigentError(
                f"provider_routing.{harness}: 'order' must be a non-empty list of provider names.",
                code=ErrorCode.INVALID_INPUT,
            )
        order: list[str] = []
        for name in raw_order:
            if not isinstance(name, str) or not name.strip():
                raise OmnigentError(
                    f"provider_routing.{harness}: 'order' entries must be provider names.",
                    code=ErrorCode.INVALID_INPUT,
                )
            order.append(name.strip())
        policies[harness] = ProviderRoutingPolicy(
            harness=harness,
            order=tuple(order),
            triggers=_parse_triggers(harness, raw_policy.get("on")),
        )
    return policies


__all__ = [
    "ROUTING_CONFIG_KEY",
    "ProviderRoutingPolicy",
    "ProviderSelection",
    "ProviderSignals",
    "RoutingTrigger",
    "load_routing_policies",
    "select_provider",
]
