"""Runner coordination regressions for Antigravity native Stop."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import Response

from omnigent.runner import app as runner_app
from omnigent.runner import create_runner_app
from omnigent.runtime.harnesses.process_manager import NoLiveHarnessError
from omnigent.spec.types import AgentSpec, ExecutorSpec
from tests.runner.conftest import (
    _FakeProcessManager,
    _ordered_user_texts,
    _runner_client,
    _ScriptedHarnessClient,
)
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
@pytest.mark.parametrize("recovery", ["retry", "idle", "failed"])
async def test_stop_failure_keeps_child_pending_until_live_harness_confirms(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, recovery: str
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

            assert harness_client.posted_bodies == []
            if recovery == "retry":
                harness_client.confirmed = True
                completion_body = {"type": "interrupt"}
            else:
                completion_body = {
                    "type": "external_session_status",
                    "data": {"status": recovery, "output": "native result"},
                }
            confirmed = await client.post(
                f"/v1/sessions/{child_id}/events", json=completion_body
            )

            assert confirmed.status_code == 204, confirmed.text
            await _wait_until(lambda: bool(harness_client.posted_bodies))
            await _wait_until(lambda: not parent_inbox.empty())
            delivered = parent_inbox.get_nowait()
            await _wait_until(lambda: child_id not in app.state.active_turns)
            fresh = await client.post(
                f"/v1/sessions/{child_id}/events",
                json={
                    "type": "message",
                    "content": [{"type": "input_text", "text": "fresh message"}],
                },
            )
            assert fresh.status_code == 202, fresh.text
            await _wait_until(lambda: len(harness_client.posted_bodies) == 2)
    finally:
        blocker.set()
        runner_app.unregister_subagent_work(child_id)
        runner_app._session_inboxes_ref.pop(parent_id, None)
        runner_app._session_inboxes_ref.pop(child_id, None)
        runner_app._session_event_queues_ref.pop(child_id, None)

    assert harness_client.interrupt_posts == (2 if recovery == "retry" else 1)
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
    assert "fresh message" in dispatched_texts
    assert delivered["status"] == {
        "retry": "cancelled",
        "idle": "completed",
        "failed": "failed",
    }[recovery]
    assert any(
        url == f"/v1/sessions/{parent_id}/events" and payload.get("type") == "message"
        for url, payload in server_client.posts
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("reader_first", [True, False])
async def test_cancelled_native_status_and_interrupt_wake_parent_once(
    monkeypatch: pytest.MonkeyPatch, reader_first: bool
) -> None:
    child_id = "antigravity-cancelled-child"
    parent_id = "antigravity-cancelled-parent"
    harness_client = _QuiescenceHarnessClient()
    server_client = _WakeServerClient()

    async def _resolver(*_args: Any, **_kwargs: Any) -> AgentSpec:
        return _antigravity_spec()

    app = create_runner_app(
        process_manager=_FakeProcessManager(harness_client),  # type: ignore[arg-type]
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
    terminal_body = {
        "type": "external_session_status",
        "data": {"status": "idle", "cancelled": True, "output": "partial reply"},
    }
    try:
        async with _runner_client(app) as client:
            created = await client.post(
                "/v1/sessions", json={"session_id": child_id, "agent_id": "antigravity"}
            )
            assert created.status_code == 201, created.text
            server_client.posts.clear()

            async def _interrupt(*_args: Any, **_kwargs: Any) -> Response:
                if reader_first:
                    observed = await client.post(
                        f"/v1/sessions/{child_id}/events", json=terminal_body
                    )
                    assert observed.status_code == 204, observed.text
                return Response(status_code=204)

            monkeypatch.setattr(harness_client, "post", _interrupt)
            stopped = await client.post(
                f"/v1/sessions/{child_id}/events", json={"type": "interrupt"}
            )
            assert stopped.status_code == 204, stopped.text
            observed = await client.post(
                f"/v1/sessions/{child_id}/events", json=terminal_body
            )
            assert observed.status_code == 204, observed.text
            await _wait_until(lambda: not parent_inbox.empty())
            assert parent_inbox.get_nowait()["status"] == "cancelled"
            assert parent_inbox.empty()
            await _wait_until(lambda: bool(server_client.posts))
            assert (
                len(
                    [
                        payload
                        for url, payload in server_client.posts
                        if url == f"/v1/sessions/{parent_id}/events"
                        and payload.get("type") == "message"
                    ]
                )
                == 1
            )
    finally:
        runner_app.unregister_subagent_work(child_id)
        runner_app._session_inboxes_ref.pop(parent_id, None)
        runner_app._session_inboxes_ref.pop(child_id, None)
        runner_app._session_event_queues_ref.pop(child_id, None)


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
    native_active = threading.Event()
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
            native_active.set()

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
    native_cancellations: list[Path] = []

    async def _native_ack(bridge_path: Path, *, expected_session_id: str | None) -> bool:
        assert expected_session_id == child_id
        if native_active.is_set():
            native_cancellations.append(bridge_path)
            native_active.clear()
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
            assert native_cancellations == []
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
    assert native_cancellations == [bridge_dir]
    assert not native_active.is_set()
    assert paste_calls == ["first turn", "first turn"]


@pytest.mark.asyncio
async def test_cancelled_stop_caller_retains_native_cancellation_before_later_turn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from omnigent.harnesses.antigravity_native import bridge
    from omnigent.harnesses.claude_native import bridge as relay_bridge
    from omnigent.inner import antigravity_native_executor as executor_mod
    from omnigent.runner.native import interrupt as interrupt_mod

    monkeypatch.setattr(runner_app, "_launch_native_terminal", AsyncMock(return_value=False))
    monkeypatch.setattr("omnigent.spec.parser.discover_host_skills", lambda *_args: [])
    monkeypatch.setattr(relay_bridge, "start_tool_relay", lambda **_kwargs: Mock())
    monkeypatch.setattr(relay_bridge, "post_tools_changed", lambda *_args: None)
    monkeypatch.setattr(
        interrupt_mod, "_session_labels_for_runner_spawn", AsyncMock(return_value={})
    )

    child_id = "antigravity-disconnected-stop"
    cascade_id = "c8f1b40b-03bd-4dc4-886a-dd406eeec926"
    monkeypatch.setattr(bridge, "_BRIDGE_ROOT", tmp_path / "agy-bridges")
    bridge_dir = bridge.bridge_dir_for_bridge_id(child_id)
    bridge.write_bridge_state(
        bridge_dir,
        bridge.AntigravityNativeBridgeState(
            session_id=child_id, conversation_id=cascade_id
        ),
    )
    bridge.write_tmux_target(
        bridge_dir, socket_path=tmp_path / "tmux.sock", tmux_target="main"
    )
    worker_started = asyncio.Event()
    release_worker = threading.Event()
    boundary_started = asyncio.Event()
    release_boundary = threading.Event()
    side_effects: list[str] = []
    loop = asyncio.get_running_loop()

    def _blocked_escape(*_args: Any, **_kwargs: Any) -> bool:
        loop.call_soon_threadsafe(worker_started.set)
        if not release_worker.wait(timeout=5):
            raise RuntimeError("test native cancellation worker was not released")
        side_effects.append("escape")
        return True

    def _record_boundary(*_args: Any, **_kwargs: Any) -> bool:
        loop.call_soon_threadsafe(boundary_started.set)
        if not release_boundary.wait(timeout=5):
            raise RuntimeError("test boundary worker was not released")
        side_effects.append("boundary")
        return True

    monkeypatch.setattr(executor_mod, "turn_is_idle_via_tui", lambda _bridge: False)
    monkeypatch.setattr(executor_mod, "resolve_language_server_port", lambda _cascade: None)
    monkeypatch.setattr(executor_mod, "interrupt_turn_via_tui", _blocked_escape)
    monkeypatch.setattr(executor_mod, "wait_for_turn_idle_via_tui", lambda _bridge: True)
    monkeypatch.setattr(
        executor_mod, "_record_confirmed_interruption_if_current", _record_boundary
    )

    class _DispatchHarnessClient(_ScriptedHarnessClient):
        def stream(self, *args: Any, **kwargs: Any) -> Any:
            side_effects.append("later-turn")
            return super().stream(*args, **kwargs)

    class _NoLiveInterruptProcessManager(_FakeProcessManager):
        async def get_client(
            self, conversation_id: str, harness: str, env: Any = None
        ) -> _ScriptedHarnessClient:
            if harness == "any":
                raise NoLiveHarnessError(f"no live harness for {conversation_id}")
            return await super().get_client(conversation_id, harness, env)

    harness_client = _DispatchHarnessClient([])
    process_manager = _NoLiveInterruptProcessManager(harness_client)

    async def _resolver(agent_id: str, session_id: str | None = None) -> AgentSpec:
        del agent_id, session_id
        return _antigravity_spec()

    app = create_runner_app(
        process_manager=process_manager,  # type: ignore[arg-type]
        spec_resolver=_resolver,
        server_client=NullServerClient(),  # type: ignore[arg-type]
    )
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

            abandoned = asyncio.create_task(
                client.post(f"/v1/sessions/{child_id}/events", json={"type": "interrupt"})
            )
            await asyncio.wait_for(worker_started.wait(), timeout=3)
            abandoned.cancel()
            with pytest.raises(asyncio.CancelledError):
                await abandoned

            repeated = asyncio.create_task(
                client.post(f"/v1/sessions/{child_id}/events", json={"type": "stop_session"})
            )
            await asyncio.sleep(0)
            assert not repeated.done()
            later = await client.post(
                f"/v1/sessions/{child_id}/events",
                json={
                    "type": "message",
                    "content": [{"type": "input_text", "text": "later turn"}],
                },
            )
            assert later.status_code == 202, later.text
            assert later.json()["status"] == "buffered"
            assert side_effects == []
            assert harness_client.posted_bodies == []

            release_worker.set()
            await asyncio.wait_for(boundary_started.wait(), timeout=3)
            repeated.cancel()
            with pytest.raises(asyncio.CancelledError):
                await repeated
            repeated = asyncio.create_task(
                client.post(f"/v1/sessions/{child_id}/events", json={"type": "interrupt"})
            )
            await asyncio.sleep(0)
            assert not repeated.done()
            assert side_effects == ["escape"]
            assert harness_client.posted_bodies == []
            release_boundary.set()
            confirmed = await repeated
            assert confirmed.status_code == 204, confirmed.text
            await _wait_until(lambda: len(harness_client.posted_bodies) == 1)
    finally:
        release_worker.set()
        release_boundary.set()
        proxy_blocker.set()
        await asyncio.gather(proxy_turn, return_exceptions=True)
        runner_app._session_inboxes_ref.pop(child_id, None)
        runner_app._session_event_queues_ref.pop(child_id, None)

    assert side_effects == ["escape", "boundary", "later-turn"]
    assert "later turn" in _ordered_user_texts(harness_client.posted_bodies[0])
