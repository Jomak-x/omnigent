"""The Antigravity transcript-fallback label controls its chat notice.

The native bridge sets ``antigravity_native_transcript_fallback=1`` when it
must mirror the terminal transcript instead of handling prompts through RPC.
This test reshapes a seeded session's browser-visible snapshot with that label,
then removes it on reload. It drives the real SPA without launching Antigravity
or sending a model turn.
"""

from __future__ import annotations

import json
from urllib.parse import urlparse

from playwright.sync_api import Page, Route, expect

from tests.e2e_ui.conftest import fetch_with_retry

_NOTICE = '[data-testid="antigravity-transcript-fallback-notice"]'
_FALLBACK_LABEL = "antigravity_native_transcript_fallback"


def test_transcript_fallback_label_shows_and_hides_terminal_guidance(
    page: Page,
    seeded_session: tuple[str, str],
) -> None:
    """The terminal guidance follows the session fallback label across reloads."""
    base_url, session_id = seeded_session
    fallback_enabled = True

    def _patch_session_snapshot(route: Route) -> None:
        if (
            route.request.method != "GET"
            or urlparse(route.request.url).path != f"/v1/sessions/{session_id}"
        ):
            route.continue_()
            return

        response = fetch_with_retry(route)
        payload = response.json()
        labels = dict(payload.get("labels") or {})
        if fallback_enabled:
            labels[_FALLBACK_LABEL] = "1"
        else:
            labels.pop(_FALLBACK_LABEL, None)
        payload["labels"] = labels
        route.fulfill(
            status=response.status,
            headers={**response.headers, "content-type": "application/json"},
            body=json.dumps(payload),
        )

    page.route("**/v1/sessions/**", _patch_session_snapshot)

    page.goto(f"{base_url}/c/{session_id}")
    notice = page.locator(_NOTICE)
    expect(notice).to_be_visible(timeout=15_000)
    expect(notice).to_have_text(
        "Antigravity approval prompts appear in Terminal; respond there to continue."
    )

    fallback_enabled = False
    page.reload()
    expect(page.get_by_role("textbox", name="Message the agent")).to_be_visible(timeout=15_000)
    expect(notice).to_have_count(0, timeout=15_000)
