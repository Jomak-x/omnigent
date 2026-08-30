"""Refresh provider-reported usage after a structured limit failure."""

from __future__ import annotations

import asyncio
import logging
import urllib.parse
from typing import Any

import httpx

_logger = logging.getLogger(__name__)
_refresh_tasks: set[asyncio.Task[bool]] = set()


async def refresh_session_provider_usage(
    client: httpx.AsyncClient,
    session_id: str,
) -> bool:
    """Refresh the running session's pinned provider usage, best-effort.

    The refresh crosses runner -> server -> host and asks the vendor again;
    it never manufactures an exhausted reading from the turn error itself.

    :returns: ``True`` only when the host accepted and completed the refresh.
    """
    session_component = urllib.parse.quote(session_id, safe="")
    try:
        snapshot_response = await client.get(
            f"/v1/sessions/{session_component}",
            timeout=10.0,
        )
        if snapshot_response.status_code != 200:
            return False
        snapshot: Any = snapshot_response.json()
        if not isinstance(snapshot, dict):
            return False
        host_id = snapshot.get("host_id")
        provider_id = snapshot.get("provider_override")
        if not isinstance(host_id, str) or not host_id:
            return False
        if not isinstance(provider_id, str) or not provider_id:
            return False
        usage_response = await client.get(
            "/v1/hosts/"
            f"{urllib.parse.quote(host_id, safe='')}/providers/"
            f"{urllib.parse.quote(provider_id, safe='')}/usage",
            params={"refresh": "true"},
            timeout=45.0,
        )
        if usage_response.status_code >= 400:
            _logger.warning(
                "provider usage refresh failed for session %s (HTTP %s)",
                session_id,
                usage_response.status_code,
            )
            return False
    except (httpx.HTTPError, ValueError, TypeError):
        _logger.warning(
            "provider usage refresh failed for session %s",
            session_id,
            exc_info=True,
        )
        return False
    return True


def schedule_session_provider_usage_refresh(
    client: httpx.AsyncClient,
    session_id: str,
) -> None:
    """Start a best-effort refresh without delaying failure delivery."""
    task = asyncio.create_task(
        refresh_session_provider_usage(client, session_id),
        name=f"provider-usage-refresh:{session_id}",
    )
    _refresh_tasks.add(task)
    task.add_done_callback(_refresh_tasks.discard)


__all__ = ["refresh_session_provider_usage", "schedule_session_provider_usage_refresh"]
