"""Read Codex's own quota status from the app-server it already ships.

Codex is the first provider whose vendor exposes real limits locally: its
app-server answers ``account/rateLimits/read`` with the percent consumed of
each window, the window length, and the reset time. Everything reported here
comes from that answer — nothing is estimated from token counts, and a Codex
build that does not implement the method reports "unknown" rather than a
guess.

The probe is deliberately expensive-but-rare: it starts a short-lived
app-server, asks one question, and tears the process down. It is called on
demand (a status surface opening, a manual refresh) and its answer is cached,
never polled on a timer — a background loop spawning a CLI every minute is
exactly the battery cost this design avoids.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import socket
import time
from dataclasses import replace

from cachetools import TTLCache

from omnigent.codex_native_app_server import (
    CodexAppServerClient,
    CodexAppServerResponseError,
)
from omnigent.inner import _proc
from omnigent.json_types import JsonObject
from omnigent.onboarding.provider_usage import (
    ProviderUsageStatus,
    UsageState,
    UsageWindow,
    unknown_usage,
    usage_state_for,
    window_label,
)

_logger = logging.getLogger(__name__)

_RATE_LIMITS_METHOD = "account/rateLimits/read"
# Seconds to wait for the app-server to accept a connection, then to answer.
_CONNECT_TIMEOUT_S = 10.0
_CONNECT_RETRY_DELAY_S = 0.05
_REQUEST_TIMEOUT_S = 15.0
_SHUTDOWN_TIMEOUT_S = 5.0
# How long a reading stays fresh. Quota windows move in hours, so a minute of
# staleness costs nothing and spares the machine a process per page render.
_DEFAULT_CACHE_TTL_S = 60.0
_CACHE_TTL_ENV_VAR = "OMNIGENT_PROVIDER_USAGE_TTL_S"
# JSON-RPC codes a Codex without the method answers with.
_UNSUPPORTED_METHOD_CODES = frozenset({-32600, -32601})


def _cache_ttl_seconds() -> float:
    """Return the configured cache lifetime, falling back to the default."""
    raw = os.environ.get(_CACHE_TTL_ENV_VAR)
    if raw is None:
        return _DEFAULT_CACHE_TTL_S
    try:
        ttl = float(raw)
    except ValueError:
        _logger.warning("Ignoring non-numeric %s=%r", _CACHE_TTL_ENV_VAR, raw)
        return _DEFAULT_CACHE_TTL_S
    return ttl if ttl > 0 else _DEFAULT_CACHE_TTL_S


# Built once at import: the TTL is a deployment choice, not a per-call one.
_usage_cache: TTLCache[str, ProviderUsageStatus] = TTLCache(maxsize=8, ttl=_cache_ttl_seconds())


def _allocate_loopback_port() -> int:
    """Return an ephemeral loopback port for the probe's app-server."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


async def _wait_for_listener(process: asyncio.subprocess.Process, port: int) -> None:
    """Wait until the probe app-server accepts loopback connections."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _CONNECT_TIMEOUT_S
    while loop.time() < deadline:
        if process.returncode is not None:
            raise RuntimeError(f"Codex usage probe exited early ({process.returncode})")
        try:
            _reader, writer = await asyncio.open_connection("127.0.0.1", port)
        except OSError:
            await asyncio.sleep(_CONNECT_RETRY_DELAY_S)
            continue
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
        return
    raise TimeoutError("Timed out waiting for the Codex usage probe app-server")


async def read_codex_rate_limits(*, codex_path: str, codex_home: str | None = None) -> JsonObject:
    """Ask a short-lived Codex app-server for the account's rate limits.

    :param codex_path: The Codex executable to run.
    :param codex_home: The Codex home to authenticate from — a provider's own
        ``cli_home`` when it names one, so a second account's limits are read
        from that account rather than the default home's.
    :returns: The raw ``rateLimits`` object from the app-server.
    :raises CodexAppServerResponseError: Codex refused the request (including
        a build that does not implement the method).
    :raises RuntimeError: The probe process exited before answering.
    :raises TimeoutError: The probe did not become ready or answer in time.
    """
    from omnigent.inner.codex_executor import _clean_codex_env, _codex_home_config_source_from_env

    env = _clean_codex_env()
    # Read the same home the launch authenticates from, so the numbers describe
    # the account that would actually run the work.
    env["CODEX_HOME"] = codex_home or str(_codex_home_config_source_from_env())
    port = _allocate_loopback_port()
    listen_url = f"ws://127.0.0.1:{port}"
    process = await asyncio.create_subprocess_exec(
        codex_path,
        "app-server",
        "--listen",
        listen_url,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        env=env,
        **_proc.spawn_kwargs(),
    )
    client: CodexAppServerClient | None = None
    try:
        await _wait_for_listener(process, port)
        client = CodexAppServerClient(ws_url=listen_url, client_name="omnigent-codex-usage")
        await client.connect()
        response = await asyncio.wait_for(
            client.request(_RATE_LIMITS_METHOD, {}),
            timeout=_REQUEST_TIMEOUT_S,
        )
    finally:
        if client is not None:
            with contextlib.suppress(Exception):
                await client.close()
        _proc.terminate_tree(process)
        try:
            await asyncio.wait_for(process.wait(), timeout=_SHUTDOWN_TIMEOUT_S)
        except TimeoutError:
            # Never leave the probe behind: an orphaned app-server keeps a
            # port and a credential-bearing process alive indefinitely.
            _proc.kill_tree(process)
            await process.wait()
    result = response.get("result")
    if not isinstance(result, dict):
        raise ValueError("Codex rate-limit result must be an object")
    rate_limits = result.get("rateLimits")
    if not isinstance(rate_limits, dict):
        raise ValueError("Codex rate-limit result must carry a rateLimits object")
    return rate_limits


def _window(raw: object, *, window_id: str, fallback_label: str) -> UsageWindow | None:
    """Convert one reported window, dropping anything without a percentage."""
    if not isinstance(raw, dict):
        return None
    used = raw.get("usedPercent")
    if not isinstance(used, (int, float)) or isinstance(used, bool):
        return None
    minutes = raw.get("windowDurationMins")
    resets_at = raw.get("resetsAt")
    return UsageWindow(
        window_id=window_id,
        label=window_label(
            int(minutes) if isinstance(minutes, int) and not isinstance(minutes, bool) else None,
            fallback=fallback_label,
        ),
        used_percent=float(used),
        window_minutes=int(minutes)
        if isinstance(minutes, int) and not isinstance(minutes, bool)
        else None,
        resets_at=int(resets_at)
        if isinstance(resets_at, int) and not isinstance(resets_at, bool)
        else None,
    )


def _credit_message(raw: object) -> str | None:
    """Describe purchased credits, which outlive an exhausted window."""
    if not isinstance(raw, dict):
        return None
    if raw.get("unlimited") is True:
        return "Credits are unlimited on this account, so work can continue past the limit."
    if raw.get("hasCredits") is True:
        return "Credits are available to continue past the limit."
    return None


def codex_usage_from_rate_limits(provider_id: str, rate_limits: JsonObject) -> ProviderUsageStatus:
    """Map Codex's reported limits onto the shared usage value type.

    :param provider_id: The inventory row this describes.
    :param rate_limits: The raw ``rateLimits`` object from the app-server.
    :returns: The status, carrying only percentages Codex itself reported.
    """
    windows = tuple(
        window
        for window in (
            _window(
                rate_limits.get("primary"), window_id="primary", fallback_label="Current limit"
            ),
            _window(
                rate_limits.get("secondary"),
                window_id="secondary",
                fallback_label="Longer-term limit",
            ),
        )
        if window is not None
    )
    plan = rate_limits.get("planType")
    state = usage_state_for(windows)
    message = None
    if state is UsageState.EXHAUSTED:
        message = _credit_message(rate_limits.get("credits"))
    elif not windows:
        message = "Codex did not report any limit for this account."
    return ProviderUsageStatus(
        provider_id=provider_id,
        state=state,
        windows=windows,
        plan=plan if isinstance(plan, str) and plan else None,
        message=message,
        checked_at=time.time(),
    )


async def codex_usage_status(
    provider_id: str,
    *,
    refresh: bool = False,
    codex_home: str | None = None,
) -> ProviderUsageStatus:
    """Return Codex's quota status for one provider row.

    Local readiness decides first: a missing CLI or an unauthenticated one is
    reported without starting a probe at all. Otherwise a cached reading is
    served, or one probe is run and cached.

    :param provider_id: The inventory row this describes.
    :param refresh: Skip the cache and take a fresh reading.
    :param codex_home: The provider's own Codex home, when it names one. Part
        of the cache key, so two accounts never serve each other's numbers.
    :returns: The status; never raises, because a status read must settle.
    """
    from omnigent.codex_native import _codex_auth_unavailable_reason, _find_codex_cli

    reason = await asyncio.to_thread(_codex_auth_unavailable_reason)
    if reason == "binary-missing":
        return unknown_usage(
            provider_id,
            "The codex CLI is not installed on this host.",
            state=UsageState.PROVIDER_UNAVAILABLE,
        )
    if reason == "needs-auth":
        return unknown_usage(
            provider_id,
            "Codex has no credential on this host, so it reports no limits.",
            state=UsageState.AUTHENTICATION_REQUIRED,
        )
    codex_path = await asyncio.to_thread(_find_codex_cli)
    if not codex_path:
        return unknown_usage(
            provider_id,
            "The codex CLI is not installed on this host.",
            state=UsageState.PROVIDER_UNAVAILABLE,
        )
    cache_key = f"{codex_path}\x00{codex_home or ''}"
    if not refresh:
        cached = _usage_cache.get(cache_key)
        if cached is not None:
            # Keep the reading's own ``checked_at`` so the UI can say how old it is.
            return replace(cached, provider_id=provider_id)
    try:
        rate_limits = await read_codex_rate_limits(codex_path=codex_path, codex_home=codex_home)
    except CodexAppServerResponseError as exc:
        if exc.code in _UNSUPPORTED_METHOD_CODES:
            return unknown_usage(
                provider_id,
                "This version of the codex CLI does not report usage limits.",
            )
        _logger.warning("Codex usage probe was refused (code %s)", exc.code)
        return unknown_usage(provider_id, "Codex declined to report its usage limits.")
    except Exception:
        _logger.exception("Codex usage probe failed")
        return unknown_usage(provider_id, "The Codex usage probe failed on this host.")
    status = codex_usage_from_rate_limits(provider_id, rate_limits)
    _usage_cache[cache_key] = status
    return status


__all__ = [
    "codex_usage_from_rate_limits",
    "codex_usage_status",
    "read_codex_rate_limits",
]
