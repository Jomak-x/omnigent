"""Tests for the shared provider usage/quota value type."""

from __future__ import annotations

import pytest

from omnigent.onboarding.provider_usage import (
    ProviderUsageStatus,
    UsageState,
    UsageWindow,
    unknown_usage,
    usage_state_for,
    window_label,
)


@pytest.mark.parametrize(
    ("minutes", "expected"),
    [
        (300, "5-hour limit"),
        (60, "Hourly limit"),
        (10080, "Weekly limit"),
        (20160, "2-week limit"),
        (1440, "Daily limit"),
        (4320, "3-day limit"),
        (90, "90-minute limit"),
    ],
)
def test_window_label_describes_the_reported_duration(minutes: int, expected: str) -> None:
    assert window_label(minutes, fallback="Current limit") == expected


@pytest.mark.parametrize("minutes", [None, 0, -5])
def test_window_label_falls_back_when_no_duration_was_reported(minutes: int | None) -> None:
    assert window_label(minutes, fallback="Current limit") == "Current limit"


def _window(used: float) -> UsageWindow:
    return UsageWindow(window_id="primary", label="5-hour limit", used_percent=used)


@pytest.mark.parametrize(
    ("used", "expected"),
    [
        (0.0, UsageState.AVAILABLE),
        (49.9, UsageState.AVAILABLE),
        (50.0, UsageState.PARTIALLY_USED),
        (89.9, UsageState.PARTIALLY_USED),
        (90.0, UsageState.NEARLY_EXHAUSTED),
        (99.9, UsageState.NEARLY_EXHAUSTED),
        (100.0, UsageState.EXHAUSTED),
    ],
)
def test_usage_state_follows_the_reported_percentage(used: float, expected: UsageState) -> None:
    assert usage_state_for((_window(used),)) is expected


def test_no_reported_window_is_unknown_rather_than_available() -> None:
    # The whole point: silence must never render as a full quota.
    assert usage_state_for(()) is UsageState.UNKNOWN


def test_the_most_consumed_window_decides_the_state() -> None:
    windows = (
        UsageWindow(window_id="primary", label="5-hour limit", used_percent=100.0),
        UsageWindow(window_id="secondary", label="Weekly limit", used_percent=12.0),
    )

    assert usage_state_for(windows) is UsageState.EXHAUSTED


def test_status_serializes_windows_and_staleness() -> None:
    status = ProviderUsageStatus(
        provider_id="codex",
        state=UsageState.NEARLY_EXHAUSTED,
        windows=(
            UsageWindow(
                window_id="primary",
                label="5-hour limit",
                used_percent=95.0,
                window_minutes=300,
                resets_at=1788122499,
            ),
        ),
        plan="plus",
        checked_at=1788112841.0,
    )

    assert status.as_dict() == {
        "provider_id": "codex",
        "profile": None,
        "state": "nearly_exhausted",
        "windows": [
            {
                "id": "primary",
                "label": "5-hour limit",
                "used_percent": 95.0,
                "window_minutes": 300,
                "resets_at": 1788122499,
            }
        ],
        "plan": "plus",
        "message": None,
        "checked_at": 1788112841.0,
    }


def test_unknown_usage_carries_a_reason_and_no_numbers() -> None:
    status = unknown_usage("codex", "Nothing to report.", state=UsageState.AUTHENTICATION_REQUIRED)

    assert status.state is UsageState.AUTHENTICATION_REQUIRED
    assert status.windows == ()
    assert status.message == "Nothing to report."
    assert status.checked_at > 0
