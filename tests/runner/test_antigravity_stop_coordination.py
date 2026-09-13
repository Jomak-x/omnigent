"""Runner coordination regressions for Antigravity native Stop."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from fastapi import Response

from omnigent.runner import app as runner_app
from omnigent.runner import create_runner_app
from omnigent.spec.types import AgentSpec, ExecutorSpec
from tests.runner.conftest import _FakeProcessManager, _runner_client, _ScriptedHarnessClient
from tests.runner.helpers import NullServerClient


def _antigravity_spec() -> AgentSpec:
    return AgentSpec(
        spec_version=1,
        name="antigravity",
        executor=ExecutorSpec(type="omnigent", config={"harness": "antigravity-native"}),
    )


async def _wait_until(predicate: Any) -> None:
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.01)


def _drain_events(queue: asyncio.Queue[dict[str, Any] | None]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    while not queue.empty():
        event = queue.get_nowait()
        if isinstance(event, dict):
            events.append(event)
    return events


class _WakeServerClient(NullServerClient):
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict[str, Any]]] = []

    async def post(self, url: str, **kwargs: Any) -> NullServerClient._Response:
        payload = kwargs.get("json")
        assert isinstance(payload, dict)
        self.posts.append((url, payload))
        return await super().post(url, **kwargs)


class _QuiescenceHarnessClient(_ScriptedHarnessClient):
    def __init__(self) -> None:
        super().__init__([])
        self.confirmed = False
        self.interrupt_posts = 0

    async def post(self, url: str, *, json: dict[str, Any], timeout: Any = None) -> Response:
        del url, timeout
        self.patched_events.append(json)
        if json.get("type") == "interrupt":
            self.interrupt_posts += 1
            return Response(status_code=204 if self.confirmed else 503)
        return Response(status_code=204)


@pytest.mark.asyncio
async def test_stop_failure_keeps_child_pending_until_live_harness_confirms(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A failed native confirmation cannot terminalize or drain a child turn."""
    from omnigent.harnesses.antigravity_native import bridge
    from omnigent.harnesses.claude_native import bridge as relay_bridge
    from omnigent.inner import antigravity_native_executor as executor_mod

    monkeypatch.setattr(bridge, "_BRIDGE_ROOT", tmp_path / "agy-bridges")
    monkeypatch.setattr("omnigent.spec.parser.discover_host_skills", lambda *_args: [])
    monkeypatch.setattr(relay_bridge, "start_tool_relay", lambda **_kwargs: Mock())
    monkeypatch.setattr(relay_bridge, "post_tools_changed", lambda *_args: None)

    child_id = "antigravity-stop-child"
    parent_id = "antigravity-stop-parent"
    harness_client = _QuiescenceHarnessClient()
    process_manager = _FakeProcessManager(harness_client)
    server_client = _WakeServerClient()

    async def _resolver(agent_id: str, session_id: str | None = None) -> AgentSpec:
        del agent_id, session_id
        return _antigravity_spec()

    direct_native_calls: list[Path] = []

    async def _direct_native_interrupt(
        bridge_dir: Path, *, expected_session_id: str | None
    ) -> bool:
        del expected_session_id
        direct_native_calls.append(bridge_dir)
        return True

    monkeypatch.setattr(executor_mod, "interrupt_bridge_turn", _direct_native_interrupt)
    app = create_runner_app(
        process_manager=process_manager,  # type: ignore[arg-type]
        spec_resolver=_resolver,
        server_client=server_client,  # type: ignore[arg-type]
    )
    parent_inbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    runner_app._session_inboxes_ref[parent_id] = parent_inbox
    runner_app.register_subagent_work(
        parent_session_id=parent_id,
        child_session_id=child_id,
        agent="antigravity",
        title="reply",
    )
    blocker = asyncio.Event()

    async def _raw_proxy_turn() -> None:
        await blocker.wait()

    try:
        async with _runner_client(app) as client:
            created = await client.post(
                "/v1/sessions", json={"session_id": child_id, "agent_id": "antigravity"}
            )
            assert created.status_code == 201, created.text
            event_queue = app.state.session_event_queues[child_id]
            _drain_events(event_queue)
            server_client.posts.clear()
            raw_task = asyncio.create_task(_raw_proxy_turn())
            app.state.active_turns[child_id] = raw_task
            app.state.session_message_buffers[child_id] = [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": "buffered follow-up"}],
                    "agent_id": "antigravity",
                }
            ]

            failed = await client.post(
                f"/v1/sessions/{child_id}/events", json={"type": "interrupt"}
            )

            assert failed.status_code == 503
            assert raw_task.cancelled()
            assert app.state.session_message_buffers[child_id][0]["content"] == [
                {"type": "input_text", "text": "buffered follow-up"}
            ]
            entry = runner_app.get_subagent_work(child_id)
            assert entry is not None
            assert entry.status == "launching"
            assert parent_inbox.empty()
            assert server_client.posts == []
            assert harness_client.interrupt_posts == 1
            assert direct_native_calls == []
            assert not [
                event
                for event in _drain_events(event_queue)
                if event.get("type") == "session.status"
                and event.get("status") in {"idle", "failed"}
            ]

            harness_client.confirmed = True
            confirmed = await client.post(
                f"/v1/sessions/{child_id}/events", json={"type": "interrupt"}
            )

            assert confirmed.status_code == 204, confirmed.text
            await _wait_until(lambda: bool(harness_client.posted_bodies))
            await _wait_until(lambda: not parent_inbox.empty())
            delivered = parent_inbox.get_nowait()
    finally:
        blocker.set()
        runner_app.unregister_subagent_work(child_id)
        runner_app._session_inboxes_ref.pop(parent_id, None)
        runner_app._session_inboxes_ref.pop(child_id, None)
        runner_app._session_event_queues_ref.pop(child_id, None)

    assert harness_client.interrupt_posts == 2
    assert direct_native_calls == []
    dispatched_texts = [
        block.get("text")
        for body in harness_client.posted_bodies
        for item in body.get("content", [])
        if isinstance(item, dict)
        for block in item.get("content", [])
        if isinstance(block, dict)
    ]
    assert "buffered follow-up" in dispatched_texts
    assert delivered["status"] == "cancelled"
    assert any(
        url == f"/v1/sessions/{parent_id}/events" and payload.get("type") == "message"
        for url, payload in server_client.posts
    )


@pytest.mark.asyncio
async def test_stop_waits_for_retained_adapter_injection_before_native_ack(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A timeout leaves a retrying TUI injection untouched until Stop can confirm it."""
    from omnigent.harnesses.antigravity_native import bridge
    from omnigent.inner import antigravity_native_executor as executor_mod
    from omnigent.inner import antigravity_native_harness as harness_mod
    from omnigent.inner.antigravity_native_executor import AntigravityNativeExecutor

    child_id = "antigravity-adapter-child"
    bridge_dir = tmp_path / "bridge"
    bridge.write_bridge_state(
        bridge_dir,
        bridge.AntigravityNativeBridgeState(
            session_id=child_id, conversation_id="agy_conv_placeholder"
        ),
    )
    bridge.write_tmux_target(
        bridge_dir, socket_path=tmp_path / "tmux.sock", tmux_target="main"
    )
    retry_started = asyncio.Event()
    release_retry = threading.Event()
    paste_calls: list[str] = []
    loop = asyncio.get_running_loop()

    def _paste_and_submit(
        _bridge_dir: Path, _socket_path: str, _tmux_target: str, *, content: str
    ) -> None:
        paste_calls.append(content)
        if len(paste_calls) == 2:
            loop.call_soon_threadsafe(retry_started.set)
            if not release_retry.wait(timeout=5):
                raise RuntimeError("test retry injection was not released")

    monkeypatch.setattr(
        bridge,
        "_wait_for_tmux_info",
        lambda *_args, **_kwargs: {
            "socket_path": str(tmp_path / "tmux.sock"),
            "tmux_target": "main",
        },
    )
    monkeypatch.setattr(bridge, "_session_alive", lambda *_args: True)
    monkeypatch.setattr(bridge, "_wait_for_agy_prompt_ready", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(bridge, "_paste_and_submit", _paste_and_submit)
    monkeypatch.setattr(
        bridge, "_account_verification_rejected", lambda *_args: len(paste_calls) == 1
    )
    monkeypatch.setattr(bridge, "_VERIFY_RETRY_INTERVAL_S", 0)
    monkeypatch.setattr(
        harness_mod,
        "_build_antigravity_native_executor",
        lambda: AntigravityNativeExecutor(bridge_dir=bridge_dir),
    )
    monkeypatch.setenv(bridge.ANTIGRAVITY_NATIVE_REQUEST_SESSION_ID_ENV_VAR, child_id)
    native_ack_calls: list[Path] = []

    async def _native_ack(bridge_path: Path, *, expected_session_id: str | None) -> bool:
        assert expected_session_id == child_id
        native_ack_calls.append(bridge_path)
        return True

    monkeypatch.setattr(executor_mod, "interrupt_bridge_turn", _native_ack)
    adapter = harness_mod.AntigravityNativeExecutorAdapter()
    native_executor = adapter._ensure_executor()
    assert isinstance(native_executor, AntigravityNativeExecutor)
    adapter._executor = None

    class _AdapterHarnessClient(_ScriptedHarnessClient):
        def __init__(self) -> None:
            super().__init__([])
            self.interrupt_posts = 0

        async def post(
            self, url: str, *, json: dict[str, Any], timeout: Any = None
        ) -> Response:
            del url, timeout
            self.patched_events.append(json)
            if json.get("type") == "interrupt":
                self.interrupt_posts += 1
                return await adapter._handle_interrupt_event()
            return Response(status_code=204)

    harness_client = _AdapterHarnessClient()
    process_manager = _FakeProcessManager(harness_client)

    async def _resolver(agent_id: str, session_id: str | None = None) -> AgentSpec:
        del agent_id, session_id
        return _antigravity_spec()

    monkeypatch.setattr(runner_app, "_ANTIGRAVITY_INTERRUPT_TIMEOUT_S", 0.01)
    app = create_runner_app(
        process_manager=process_manager,  # type: ignore[arg-type]
        spec_resolver=_resolver,
        server_client=NullServerClient(),  # type: ignore[arg-type]
    )
    delivery = asyncio.create_task(native_executor.enqueue_session_message("main", "first turn"))
    await asyncio.wait_for(retry_started.wait(), timeout=3)
    proxy_blocker = asyncio.Event()

    async def _raw_proxy_turn() -> None:
        await proxy_blocker.wait()

    proxy_turn = asyncio.create_task(_raw_proxy_turn())

    try:
        async with _runner_client(app) as client:
            created = await client.post(
                "/v1/sessions", json={"session_id": child_id, "agent_id": "antigravity"}
            )
            assert created.status_code == 201, created.text
            app.state.active_turns[child_id] = proxy_turn
            event_queue = app.state.session_event_queues[child_id]
            _drain_events(event_queue)

            timed_out = await client.post(
                f"/v1/sessions/{child_id}/events", json={"type": "stop_session"}
            )

            assert timed_out.status_code == 503
            assert native_ack_calls == []
            assert harness_client.interrupt_posts == 1
            assert paste_calls == ["first turn", "first turn"]
            assert not [
                event
                for event in _drain_events(event_queue)
                if event.get("type") == "session.status"
                and event.get("status") in {"idle", "failed"}
            ]

            release_retry.set()
            await asyncio.gather(delivery, return_exceptions=True)
            assert await delivery is True
            assert proxy_turn.cancelled()

            confirmed = await client.post(
                f"/v1/sessions/{child_id}/events", json={"type": "stop_session"}
            )
    finally:
        release_retry.set()
        proxy_blocker.set()
        await asyncio.gather(delivery, return_exceptions=True)
        await asyncio.gather(proxy_turn, return_exceptions=True)
        runner_app._session_inboxes_ref.pop(child_id, None)
        runner_app._session_event_queues_ref.pop(child_id, None)

    assert confirmed.status_code == 204, confirmed.text
    assert harness_client.interrupt_posts == 2
    assert native_ack_calls == [bridge_dir]
    assert paste_calls == ["first turn", "first turn"]
