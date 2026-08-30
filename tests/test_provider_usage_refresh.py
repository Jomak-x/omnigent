"""Tests for runner-to-host provider usage refreshes after limit errors."""

from __future__ import annotations

import asyncio
import json

import httpx

from omnigent.provider_usage_refresh import refresh_session_provider_usage


def test_refresh_uses_the_sessions_exact_host_and_provider() -> None:
    requests: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/sessions/conv one":
            return httpx.Response(
                200,
                json={"host_id": "host/one", "provider_override": "codex work"},
            )
        return httpx.Response(200, json={"usage": {"state": "exhausted"}})

    async def _run() -> bool:
        async with httpx.AsyncClient(
            base_url="http://server",
            transport=httpx.MockTransport(_handler),
        ) as client:
            return await refresh_session_provider_usage(client, "conv one")

    assert asyncio.run(_run()) is True
    assert [request.url.path for request in requests] == [
        "/v1/sessions/conv one",
        "/v1/hosts/host/one/providers/codex work/usage",
    ]
    assert requests[1].url.params["refresh"] == "true"


def test_refresh_does_nothing_without_a_recorded_provider() -> None:
    requests: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=json.dumps({"host_id": "host_one"}))

    async def _run() -> bool:
        async with httpx.AsyncClient(
            base_url="http://server",
            transport=httpx.MockTransport(_handler),
        ) as client:
            return await refresh_session_provider_usage(client, "conv_one")

    assert asyncio.run(_run()) is False
    assert len(requests) == 1
