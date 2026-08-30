"""Provider usage/quota status, reported only where a vendor exposes it.

The rule this module enforces: a percentage is shown only when the provider
itself reported one. Omnigent never estimates a quota from token counts, never
infers "probably fine" from a successful turn, and never fills an unknown
window with a plausible number. A provider whose vendor exposes nothing
reports :attr:`UsageState.UNKNOWN`, which the UI renders as "not reported"
rather than as a full battery.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum

from omnigent.json_types import JsonObject


class UsageState(str, Enum):
    """How much of a provider's quota is left, as the vendor reported it."""

    AVAILABLE = "available"
    PARTIALLY_USED = "partially_used"
    NEARLY_EXHAUSTED = "nearly_exhausted"
    EXHAUSTED = "exhausted"
    UNKNOWN = "unknown"
    AUTHENTICATION_REQUIRED = "authentication_required"
    PROVIDER_UNAVAILABLE = "provider_unavailable"


# Boundaries between the reported states, in percent used. Chosen so
# "nearly exhausted" leaves room to finish a turn and switch profiles.
_PARTIALLY_USED_AT = 50.0
_NEARLY_EXHAUSTED_AT = 90.0
_EXHAUSTED_AT = 100.0


@dataclass(frozen=True)
class UsageWindow:
    """One quota window the provider reported.

    :param window_id: Stable id for the window, e.g. ``"primary"``.
    :param label: Human label derived from the window length, e.g.
        ``"5-hour limit"``. Never invented: a provider that reports no
        duration gets a generic label.
    :param used_percent: Percent of the window consumed, as reported.
    :param window_minutes: The window's length in minutes, or ``None``.
    :param resets_at: Unix seconds when the window resets, or ``None``.
    """

    window_id: str
    label: str
    used_percent: float
    window_minutes: int | None = None
    resets_at: int | None = None

    def as_dict(self) -> JsonObject:
        """Return the public API representation."""
        return {
            "id": self.window_id,
            "label": self.label,
            "used_percent": self.used_percent,
            "window_minutes": self.window_minutes,
            "resets_at": self.resets_at,
        }


def window_label(window_minutes: int | None, *, fallback: str) -> str:
    """Describe a quota window by its length.

    :param window_minutes: The window length in minutes, or ``None`` when the
        provider did not report one.
    :param fallback: Label to use when the length is unknown, e.g.
        ``"Current limit"``.
    :returns: A label such as ``"5-hour limit"`` or ``"Weekly limit"``.
    """
    if window_minutes is None or window_minutes <= 0:
        return fallback
    if window_minutes % 10080 == 0:
        weeks = window_minutes // 10080
        return "Weekly limit" if weeks == 1 else f"{weeks}-week limit"
    if window_minutes % 1440 == 0:
        days = window_minutes // 1440
        return "Daily limit" if days == 1 else f"{days}-day limit"
    if window_minutes % 60 == 0:
        hours = window_minutes // 60
        return "Hourly limit" if hours == 1 else f"{hours}-hour limit"
    return f"{window_minutes}-minute limit"


def usage_state_for(windows: tuple[UsageWindow, ...]) -> UsageState:
    """Reduce reported windows to one state, worst window first.

    :param windows: The windows a provider reported; empty means nothing was
        reported.
    :returns: The state for the most-consumed window, or
        :attr:`UsageState.UNKNOWN` when there is nothing to judge.
    """
    if not windows:
        return UsageState.UNKNOWN
    worst = max(window.used_percent for window in windows)
    if worst >= _EXHAUSTED_AT:
        return UsageState.EXHAUSTED
    if worst >= _NEARLY_EXHAUSTED_AT:
        return UsageState.NEARLY_EXHAUSTED
    if worst >= _PARTIALLY_USED_AT:
        return UsageState.PARTIALLY_USED
    return UsageState.AVAILABLE


@dataclass(frozen=True)
class ProviderUsageStatus:
    """A provider's quota status at a moment in time.

    :param provider_id: The inventory row this describes, e.g. ``"codex"``.
    :param profile: The account/profile the status belongs to, when the
        provider distinguishes them; ``None`` today.
    :param state: The reduced state across :attr:`windows`.
    :param windows: Every quota window the provider reported.
    :param plan: The vendor's plan name when reported, e.g. ``"plus"``.
    :param message: A non-secret sentence explaining the state, especially
        when there is no percentage to show.
    :param checked_at: Unix seconds when this status was read, so a UI can
        say how stale it is instead of implying it is live.
    """

    provider_id: str
    state: UsageState
    windows: tuple[UsageWindow, ...] = ()
    profile: str | None = None
    plan: str | None = None
    message: str | None = None
    checked_at: float = 0.0

    def as_dict(self) -> JsonObject:
        """Return the public API representation."""
        return {
            "provider_id": self.provider_id,
            "profile": self.profile,
            "state": self.state.value,
            "windows": [window.as_dict() for window in self.windows],
            "plan": self.plan,
            "message": self.message,
            "checked_at": self.checked_at,
        }


def unknown_usage(
    provider_id: str, message: str, *, state: UsageState | None = None
) -> ProviderUsageStatus:
    """Build a status that reports no numbers, only why there are none.

    :param provider_id: The inventory row this describes.
    :param message: The non-secret sentence to show instead of a percentage.
    :param state: An explicit non-numeric state (authentication required,
        provider unavailable); defaults to :attr:`UsageState.UNKNOWN`.
    :returns: A status carrying no windows.
    """
    return ProviderUsageStatus(
        provider_id=provider_id,
        state=state or UsageState.UNKNOWN,
        message=message,
        checked_at=time.time(),
    )


__all__ = [
    "ProviderUsageStatus",
    "UsageState",
    "UsageWindow",
    "unknown_usage",
    "usage_state_for",
    "window_label",
]
