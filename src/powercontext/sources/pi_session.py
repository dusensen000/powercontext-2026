# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Capture one selected Pi session branch as immutable event evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources import (
    TEXT_EVIDENCE_PROJECTION_KEY,
    AdapterSourceDefinition,
    ConnectorRunCompletion,
    ConnectorRunSession,
    ConnectorRunStatus,
    TextEvidence,
)
from powercontext.sources.models import Source, SourceMaterialization

PI_EVENT_SOURCE_NAME = "pi-event"
PI_SESSION_CONNECTOR_NAME = "pi-session-history"
CONNECTOR_VERSION = "1"
PI_SESSION_VERSION = 3


class PiSessionInput(BaseModel):
    """One UTF-8 JSONL Pi session archive and an optional selected leaf."""

    content: bytes
    leaf_id: str | None = None


class PiEventInput(BaseModel):
    """One visible event on the selected root-to-leaf path."""

    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, Any]


class PiEventSource(Source):
    """Captured evidence for exactly one Pi session event."""

    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, Any]


def parse_pi_session(value: PiSessionInput, /) -> tuple[PiEventInput, ...]:
    """Parse the whole archive and return only the selected branch's evidence."""

    session_id, records, selected = _parse_archive(value.content, value.leaf_id)
    events: list[PiEventInput] = []
    for record in selected:
        visible = _visible_event(session_id, record)
        if visible is not None:
            events.append(visible)
    return tuple(events)


class _PiEventAdapter:
    """Resolve visible events into captured Sources and back."""

    input_class = PiEventInput
    name = PI_EVENT_SOURCE_NAME
    source_class = PiEventSource

    async def resolve(self, value: PiEventInput, /) -> PiEventSource:
        source_id = _event_source_id(value.session_id, value.event_id)
        return PiEventSource(
            name=source_id,
            materialization=SourceMaterialization.CAPTURED,
            session_id=value.session_id,
            event_id=value.event_id,
            parent_id=value.parent_id,
            event_type=value.event_type,
            role=value.role,
            content=value.content,
            record=value.record,
        )

    async def read(self, source: PiEventSource, /) -> PiEventInput:
        return PiEventInput(
            session_id=source.session_id,
            event_id=source.event_id,
            parent_id=source.parent_id,
            event_type=source.event_type,
            role=source.role,
            content=source.content,
            record=source.record,
        )


class _PiEventTextEvidence:
    """Project the complete event text without a model-compressed view."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PiEventSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PiEventSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=PI_EVENT_SOURCE_NAME,
            source_id=source.name,
            content=source.content,
            metadata={
                "session_id": source.session_id,
                "event_id": source.event_id,
                "parent_id": source.parent_id,
                "event_type": source.event_type,
                "role": source.role,
            },
        )


PI_EVENT_SOURCE_DEFINITION = AdapterSourceDefinition(
    _PiEventAdapter(),
    projections=(_PiEventTextEvidence(),),
)


class PiSessionConnector:
    """Incrementally capture the selected branch of one Pi session file."""

    name = PI_SESSION_CONNECTOR_NAME
    version = CONNECTOR_VERSION
    source_definitions = frozenset({PI_EVENT_SOURCE_NAME})

    def __init__(self, path: str | Path, leaf_id: str | None = None) -> None:
        self._path = Path(path)
        self._leaf_id = leaf_id

    async def run(self, session: ConnectorRunSession, /) -> ConnectorRunCompletion:
        raw = self._path.read_bytes()
        session_id, records, selected = _parse_archive(raw, self._leaf_id)
        checkpoint = _checkpoint_events(session.checkpoint)
        _reject_rewritten_events(records, checkpoint)

        proposed = dict(checkpoint)
        for record in selected:
            event = _visible_event(session_id, record)
            if event is None:
                continue
            digest = _record_digest(record)
            prior = proposed.get(event.event_id)
            if prior is not None:
                if prior != digest:
                    raise ValueError(  # noqa: TRY003
                        f"Pi event {event.event_id!r} was rewritten after import"
                    )
                continue
            await session.submit(event.event_id, PI_EVENT_SOURCE_NAME, event)
            proposed[event.event_id] = digest
        return ConnectorRunCompletion(
            status=ConnectorRunStatus.COMPLETE,
            checkpoint={"session_id": session_id, "events": proposed},
        )


def _parse_archive(
    content: bytes,
    leaf_id: str | None,
) -> tuple[str, dict[str, dict[str, Any]], tuple[dict[str, Any], ...]]:
    try:
        text = content.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as error:
        raise ValueError("Pi session archive must be strict UTF-8") from error

    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.split("\n"), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid Pi session JSON on line {line_number}") from error  # noqa: TRY003
        if not isinstance(row, dict):
            raise ValueError(f"Pi session line {line_number} must be a JSON object")  # noqa: TRY003
        rows.append(row)
    if not rows:
        raise ValueError("Pi session archive must not be empty")  # noqa: TRY003

    header = rows[0]
    if header.get("type") != "session" or header.get("version") != PI_SESSION_VERSION:
        raise ValueError("Pi session header must declare type=session and version=3")  # noqa: TRY003
    session_id = header.get("id")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("Pi session header must contain a non-empty id")  # noqa: TRY003

    records: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for row in rows[1:]:
        event_id = row.get("id")
        if not isinstance(event_id, str) or not event_id:
            raise ValueError("every Pi session record must contain a non-empty id")  # noqa: TRY003
        if event_id in records:
            raise ValueError(f"duplicate Pi session record id {event_id!r}")  # noqa: TRY003
        parent_id = row.get("parentId")
        if parent_id is not None:
            if not isinstance(parent_id, str) or not parent_id:
                raise ValueError("Pi session parentId must be a non-empty string or null")  # noqa: TRY003
            if parent_id not in records:
                raise ValueError(f"Pi session parent {parent_id!r} is missing or out of order")  # noqa: TRY003
        records[event_id] = row
        order.append(event_id)

    selected_leaf = order[-1] if leaf_id is None else leaf_id
    if selected_leaf not in records:
        raise ValueError(f"Pi session leaf {selected_leaf!r} does not exist")  # noqa: TRY003

    path: list[dict[str, Any]] = []
    cursor: str | None = selected_leaf
    while cursor is not None:
        record = records[cursor]
        path.append(record)
        cursor = record.get("parentId")
    path.reverse()
    return session_id, records, tuple(path)


def _visible_event(session_id: str, record: dict[str, Any]) -> PiEventInput | None:
    event_type = record.get("type")
    if event_type == "message":
        message = record.get("message")
        if not isinstance(message, dict):
            raise ValueError("Pi message records must contain a message object")  # noqa: TRY003
        role = message.get("role")
        if not isinstance(role, str) or not role:
            raise ValueError("Pi message records must contain a role")  # noqa: TRY003
        if role == "bashExecution":
            body = _bash_body(message)
        elif role == "toolResult":
            body = _tool_result_body(message)
        else:
            body = _message_body(message)
    elif event_type in {"compaction", "branch_summary"}:
        role = event_type
        summary = record.get("summary")
        body = summary if isinstance(summary, str) else ""
    elif event_type == "custom_message":
        role = "custom"
        body = _content_body(record.get("content"))
    else:
        return None

    if not body.strip():
        return None
    return PiEventInput(
        session_id=session_id,
        event_id=record["id"],
        parent_id=record.get("parentId"),
        event_type=event_type,
        role=role,
        content=f"{role}: {body}",
        record=record,
    )


def _message_body(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in _blocks(content):
        if block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
        elif block.get("type") == "toolCall":
            name = block.get("name")
            call_id = block.get("id")
            arguments = block.get("arguments")
            parts.append(
                f"[tool_call {name} {call_id}] "
                + json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            )
    return "\n".join(parts)


def _tool_result_body(message: dict[str, Any]) -> str:
    tool_name = message.get("toolName")
    tool_call_id = message.get("toolCallId")
    text = "\n".join(_text_parts(message.get("content")))
    return f"[tool_result {tool_name} {tool_call_id}] {text}"


def _bash_body(message: dict[str, Any]) -> str:
    command = message.get("command")
    output = message.get("output")
    return f"$ {command}\n{output if isinstance(output, str) else ''}"


def _content_body(content: object) -> str:
    return "\n".join(_text_parts(content))


def _blocks(content: object) -> list[dict[str, Any]]:
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, dict)]


def _text_parts(content: object) -> list[str]:
    if isinstance(content, str):
        return [content]
    parts: list[str] = []
    for block in _blocks(content):
        if block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    return parts


def _event_source_id(session_id: str, event_id: str) -> str:
    source_id = f"pi:{quote(session_id, safe='')}:{quote(event_id, safe='')}"
    if len(source_id) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(  # noqa: TRY003
            f"pi event source_id must not exceed {MAX_SOURCE_ID_LENGTH} characters"
        )
    return source_id


def _record_digest(record: dict[str, Any]) -> str:
    canonical = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _checkpoint_events(checkpoint: object) -> dict[str, str]:
    if not isinstance(checkpoint, dict):
        return {}
    events = checkpoint.get("events")
    if not isinstance(events, dict):
        return {}
    return {str(event_id): str(digest) for event_id, digest in events.items()}


def _reject_rewritten_events(records: dict[str, dict[str, Any]], checkpoint: dict[str, str]) -> None:
    for event_id, digest in checkpoint.items():
        record = records.get(event_id)
        if record is not None and _record_digest(record) != digest:
            raise ValueError(f"Pi event {event_id!r} was rewritten after import")  # noqa: TRY003


__all__ = [
    "PI_EVENT_SOURCE_DEFINITION",
    "PiEventInput",
    "PiEventSource",
    "PiSessionConnector",
    "PiSessionInput",
    "parse_pi_session",
]
