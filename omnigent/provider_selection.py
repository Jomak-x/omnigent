"""Pick the provider a native session launches on, applying the routing policy.

This is where the policy meets reality: it gathers what the host locally knows
about each candidate — the settled connection state every provider row already
carries, and, for providers whose vendor reports one, a usage reading — and
hands both to :func:`~omnigent.onboarding.provider_routing.select_provider`.

Cost is proportional to intent. With no ``provider_routing:`` block nothing
here runs at all. With one, usage is read only for candidates whose vendor
exposes it, through the same cached, on-demand path a status surface uses, so a
launch costs at most one bounded probe per account per cache window — and only
for a user who asked for failover.
"""

from __future__ import annotations

import logging

from omnigent.onboarding.provider_inventory import (
    CapabilitySupport,
    ConnectionState,
    ProviderInventoryEntry,
    build_provider_inventory,
)
from omnigent.onboarding.provider_routing import (
    ProviderSelection,
    ProviderSignals,
    load_routing_policies,
    select_provider,
)
from omnigent.onboarding.provider_usage import UsageState

_logger = logging.getLogger(__name__)


async def _usage_state_for(row: ProviderInventoryEntry) -> UsageState | None:
    """Read a candidate's quota state, or ``None`` when it reports none."""
    if row.capabilities.usage_status is not CapabilitySupport.SUPPORTED:
        return None
    if row.cli != "codex":  # the only vendor wired to report usage today
        return None
    from omnigent.codex_usage import codex_usage_status

    status = await codex_usage_status(row.provider_id, codex_home=row.cli_home)
    return status.state


async def choose_provider_for_harness(
    harness: str,
    *,
    pinned: str | None = None,
) -> ProviderSelection | None:
    """Resolve which provider should run *harness* on this machine.

    :param harness: The harness about to launch, e.g. ``"codex-native"``.
    :param pinned: The session's explicit provider pin, which always wins.
    :returns: The selection, or ``None`` when nothing is configured to decide
        and the caller should keep its own default resolution. Never raises:
        a routing failure must degrade to the default, not block a launch.
    """
    if pinned is not None:
        return ProviderSelection(provider=pinned)
    try:
        from omnigent.onboarding.provider_config import load_config

        config = load_config()
        policy = load_routing_policies(config).get(harness)
        if policy is None:
            return None
        inventory = {row.provider_id: row for row in build_provider_inventory(config)}
        signals: dict[str, ProviderSignals] = {}
        for candidate in policy.order:
            row = inventory.get(candidate)
            if row is None:
                # A policy naming a provider this host does not have is a real
                # misconfiguration, but not one worth failing a launch over:
                # treat it as unavailable so the policy moves past it, and say
                # so once.
                _logger.warning(
                    "provider routing: %s names provider %r, which this host does not have.",
                    harness,
                    candidate,
                )
                signals[candidate] = ProviderSignals(ConnectionState.UNAVAILABLE)
                continue
            signals[candidate] = ProviderSignals(
                connection_state=row.connection_state,
                usage_state=await _usage_state_for(row),
            )
        selection = select_provider(policy, signals)
    except Exception:  # routing must never block a launch
        _logger.exception("provider routing failed for %s; using the configured default", harness)
        return None
    if selection is not None and selection.moved_from is not None:
        _logger.warning("provider routing: %s", selection.reason)
    return selection


__all__ = ["choose_provider_for_harness"]
