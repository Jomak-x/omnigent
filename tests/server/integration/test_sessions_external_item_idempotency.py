"""A re-posted external item with a ``source_id`` must persist exactly once.

The native transcript forwarders deliver at-least-once: a timed-out POST's
disposition is unknown, so the same item may be re-posted — and leaked
concurrent forwarders tailing one transcript post the same records in
parallel. ``data.source_id`` makes the persist idempotent.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from omnigent.harnesses.antigravity_native import reader, transcript
from omnigent.harnesses.antigravity_native.stop_hook import record_stop_event
from omnigent.runtime import pending_inputs
from tests.server.helpers import create_test_agent

pytestmark = pytest.mark.asyncio


async def _create_session(client: httpx.AsyncClient, name: str) -> str:
    agent = await create_test_agent(client, name=name)
    resp = await client.post("/v1/sessions", json={"agent_id": agent["id"]})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _post_item(
    client: httpx.AsyncClient,
    session_id: str,
    *,
    text: str,
    source_id: str | None,
    role: str = "user",
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "item_type": "message",
        "item_data": {
            "role": role,
            "content": [{"type": "input_text", "text": text}],
            **({"agent": "worker"} if role == "assistant" else {}),
        },
        "response_id": "resp_claude_echo",
    }
    if source_id is not None:
        data["source_id"] = source_id
    resp = await client.post(
        f"/v1/sessions/{session_id}/events",
        json={"type": "external_conversation_item", "data": data},
    )
    assert resp.status_code in (200, 201, 202), resp.text
    return resp.json()


async def _message_texts(client: httpx.AsyncClient, session_id: str) -> list[str]:
    items = (await client.get(f"/v1/sessions/{session_id}/items")).json()["data"]
    return [
        block.get("text", "")
        for item in items
        if item.get("type") == "message"
        for block in item.get("content", [])
    ]


async def test_reposted_item_with_source_id_persists_once(
    client: httpx.AsyncClient,
) -> None:
    session_id = await _create_session(client, "idem-repost")
    first = await _post_item(client, session_id, text="hello once", source_id="rec-1:0:message")
    second = await _post_item(client, session_id, text="hello once", source_id="rec-1:0:message")
    assert first["item_id"] == second["item_id"]
    assert await _message_texts(client, session_id) == ["hello once"]


async def test_transcript_reader_restart_dedupes_items_and_preserves_next_pending_input(
    client: httpx.AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_id = await _create_session(client, "agy-transcript-restart")
    bridge_dir = tmp_path / "bridge"
    conversation_id = "8bb3c819-e505-4812-b0f6-895bd2ec1f98"
    app_dir = bridge_dir / "agy-home" / ".gemini" / "antigravity-cli"
    transcript_path = (
        app_dir
        / "brain"
        / conversation_id
        / ".system_generated"
        / "logs"
        / "transcript_full.jsonl"
    )
    transcript_path.parent.mkdir(parents=True)
    cache = app_dir / "cache" / "last_conversations.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps({"/scratch": conversation_id}))

    def step(index: int, source: str, kind: str, content: str) -> str:
        return (
            json.dumps(
                {
                    "step_index": index,
                    "source": source,
                    "type": kind,
                    "status": "DONE",
                    "created_at": f"2026-09-13T02:00:{index:02d}Z",
                    "content": content,
                }
            )
            + "\n"
        )

    transcript_path.write_text(
        step(0, "USER_EXPLICIT", "USER_INPUT", "<USER_REQUEST>first</USER_REQUEST>")
        + step(1, "MODEL", "PLANNER_RESPONSE", "first answer")
    )
    record_stop_event(bridge_dir, {"conversationId": conversation_id, "fullyIdle": True})
    ticks = 0

    async def sleep(_duration: float) -> None:
        nonlocal ticks
        ticks += 1

    monkeypatch.setattr(reader, "_sleep", sleep)

    async def mirror() -> None:
        nonlocal ticks
        ticks = 0
        await reader._supervise_transcript(
            bridge_dir,
            transcript.TranscriptBinding(conversation_id, transcript_path),
            session_id,
            client=client,
            poll_interval_s=0,
            stop=lambda: ticks >= 4,
            committed_steps_out=None,
        )

    await mirror()
    assert await _message_texts(client, session_id) == ["first", "first answer"]
    pending_id = pending_inputs.record(
        session_id,
        [{"type": "input_text", "text": "second"}],
        created_by="alice@example.com",
    )
    with transcript_path.open("a") as handle:
        handle.write(
            step(2, "USER_EXPLICIT", "USER_INPUT", "<USER_REQUEST>second</USER_REQUEST>")
            + step(3, "MODEL", "PLANNER_RESPONSE", "second answer")
        )
    record_stop_event(bridge_dir, {"conversationId": conversation_id, "fullyIdle": True})
    await mirror()
    assert await _message_texts(client, session_id) == [
        "first",
        "first answer",
        "second",
        "second answer",
    ]
    assert all(
        entry["pending_id"] != pending_id for entry in pending_inputs.snapshot_for(session_id)
    )


async def test_distinct_source_ids_persist_separately(
    client: httpx.AsyncClient,
) -> None:
    session_id = await _create_session(client, "idem-distinct")
    await _post_item(client, session_id, text="same text", source_id="rec-1:0:message")
    await _post_item(client, session_id, text="same text", source_id="rec-2:0:message")
    assert await _message_texts(client, session_id) == ["same text", "same text"]


async def test_repost_without_source_id_keeps_legacy_behavior(
    client: httpx.AsyncClient,
) -> None:
    session_id = await _create_session(client, "idem-legacy")
    await _post_item(client, session_id, text="legacy", source_id=None)
    await _post_item(client, session_id, text="legacy", source_id=None)
    assert await _message_texts(client, session_id) == ["legacy", "legacy"]


async def test_duplicate_repost_restores_the_drained_pending_input(
    client: httpx.AsyncClient,
) -> None:
    """A duplicate must not consume the NEXT queued web message's entry.

    The persist path drains the oldest pending input before it knows the
    item is a duplicate; the dedupe result restores that entry to the
    front of the queue so the next genuine message still claims it.
    """
    session_id = await _create_session(client, "idem-pending")
    await _post_item(client, session_id, text="first msg", source_id="rec-1:0:message")

    next_pending = pending_inputs.record(
        session_id,
        [{"type": "input_text", "text": "second msg"}],
        created_by="alice@example.com",
    )
    # Duplicate of the already-persisted first message arrives late.
    await _post_item(client, session_id, text="first msg", source_id="rec-1:0:message")

    snapshot = pending_inputs.snapshot_for(session_id)
    assert [entry["pending_id"] for entry in snapshot] == [next_pending]
    assert await _message_texts(client, session_id) == ["first msg"]


async def test_bad_source_id_is_rejected(client: httpx.AsyncClient) -> None:
    session_id = await _create_session(client, "idem-bad")
    resp = await client.post(
        f"/v1/sessions/{session_id}/events",
        json={
            "type": "external_conversation_item",
            "data": {
                "item_type": "message",
                "item_data": {
                    "role": "user",
                    "content": [{"type": "input_text", "text": "x"}],
                },
                "response_id": "resp_claude_echo",
                "source_id": "x" * 300,
            },
        },
    )
    assert resp.status_code == 400


async def test_client_cannot_smuggle_a_stable_id() -> None:
    """``stable_id`` is internal-only: a client key inside event data is
    dropped by the item builder, never bound onto the entity."""
    from omnigent.server.routes._sessions.helpers import _build_new_item
    from omnigent.server.schemas import SessionEventInput

    body = SessionEventInput(
        type="message",
        data={
            "role": "user",
            "content": [{"type": "input_text", "text": "x"}],
            "stable_id": "ab" * 16,
        },
    )
    assert _build_new_item(body, "resp").stable_id is None
