"""Tests for structured SDK limit detection in the runner proxy."""

from omnigent.runner.app import _is_provider_rate_limit_error


def test_sdk_rate_limit_code_triggers_a_provider_refresh() -> None:
    assert _is_provider_rate_limit_error(
        {
            "type": "response.failed",
            "response": {"error": {"code": "rate_limit_exceeded"}},
        }
    )


def test_error_text_alone_never_triggers_a_provider_refresh() -> None:
    assert not _is_provider_rate_limit_error(
        {
            "type": "response.failed",
            "error": {"message": "usage limit exceeded"},
        }
    )
