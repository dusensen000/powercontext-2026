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

"""Propagate Source availability through a registered evidence graph.

Each Scope owns an acyclic graph of Source, Memory, and Topic Memory nodes.
Withdrawing or restoring a Source re-evaluates every descendant through its
``all``/``any`` policy and reconciles native Memory entry state, so search and
Prepared Context stop offering unsupported content while exact historical
citations remain readable.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, StrictStr, field_validator
from sqlalchemy import text

from powercontext.artifacts import ArtifactRef, MemoryCitation
from powercontext.builtin.sources.journal import validate_scope_id
from powercontext.builtin.statistics.models import ModelUsagePurpose
from powercontext.sources.models import SourceRef

if TYPE_CHECKING:
    from collections.abc import Sequence

    from powercontext.builtin.runtime.application import BuiltinRuntime

_TOPIC_MEMORY_FAMILY = "topic-memory"
_LIFECYCLE_TABLE = "powercontext_source_lifecycle"
_LIFECYCLE_REASON = "source lifecycle"


class SourceLifecycleError(ValueError):
    """Reject a lifecycle registration, event, or resolution outside the contract."""


class SourceLifecycleEvent(BaseModel):
    """One immutable availability transition for a registered Source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: StrictStr
    revision: StrictInt
    sequence: StrictInt
    available: StrictBool
    reason: StrictStr

    @field_validator("node_id", "reason")
    @classmethod
    def _require_text(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("revision", "sequence")
    @classmethod
    def _require_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("must be a positive integer")
        return value


@dataclass(frozen=True)
class _Node:
    node_id: str
    kind: Literal["source", "memory", "topic"]
    reference: dict[str, Any]
    parents: tuple[str, ...] = ()
    policy: Literal["all", "any"] = "all"
    revision: int | None = None


@dataclass
class _ScopeState:
    nodes: dict[str, _Node] = field(default_factory=dict)
    sources: dict[str, dict[str, Any]] = field(default_factory=dict)

    def availability(self) -> dict[str, bool]:
        active: dict[str, bool] = {}
        for node in self.nodes.values():
            if node.kind == "source":
                active[node.node_id] = bool(self.sources[node.node_id]["available"])
                continue
            support = [active[parent] for parent in node.parents]
            active[node.node_id] = all(support) if node.policy == "all" else any(support)
        return active

    def encode(self) -> str:
        return json.dumps(
            {
                "version": 1,
                "nodes": [
                    {
                        "node_id": node.node_id,
                        "kind": node.kind,
                        "reference": node.reference,
                        "parents": list(node.parents),
                        "policy": node.policy,
                        "revision": node.revision,
                    }
                    for node in self.nodes.values()
                ],
                "sources": self.sources,
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    @classmethod
    def decode(cls, payload: str) -> _ScopeState:
        try:
            document = json.loads(payload)
            state = cls()
            for item in document["nodes"]:
                node = _Node(
                    node_id=item["node_id"],
                    kind=item["kind"],
                    reference=item["reference"],
                    parents=tuple(item["parents"]),
                    policy=item["policy"],
                    revision=item["revision"],
                )
                state.nodes[node.node_id] = node
            state.sources = {
                key: {
                    "revision": value["revision"],
                    "sequence": value["sequence"],
                    "available": value["available"],
                    "reason": value.get("reason"),
                }
                for key, value in document["sources"].items()
            }
            return state
        except (KeyError, TypeError, ValueError) as error:
            raise SourceLifecycleError("persisted lifecycle state is invalid") from error


def _decode_reference(node: _Node) -> SourceRef | MemoryCitation | ArtifactRef:
    if node.kind == "source":
        return SourceRef.model_validate(node.reference)
    if node.kind == "memory":
        return MemoryCitation.model_validate(node.reference)
    return ArtifactRef.model_validate(node.reference)


def _encode_reference(reference: SourceRef | MemoryCitation | ArtifactRef) -> dict[str, Any]:
    return reference.model_dump(mode="json")


def _topic_key(reference: ArtifactRef) -> tuple[str, str, int]:
    return (reference.family, reference.artifact_id, reference.revision)


def _require_node_id(value: object, field_name: str = "node_id") -> str:
    if not isinstance(value, str) or not value.strip():
        raise SourceLifecycleError(f"{field_name} must be a non-empty string")
    return value


def _require_positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SourceLifecycleError(f"{field_name} must be a positive integer")
    return value


def _require_parents(parents: object) -> tuple[str, ...]:
    if isinstance(parents, str) or parents is None:
        raise SourceLifecycleError("parents must be a sequence of node ids")
    items = tuple(parents)
    if not items:
        raise SourceLifecycleError("a derived node requires at least one parent")
    normalized = tuple(_require_node_id(parent, "parent") for parent in items)
    if len(set(normalized)) != len(normalized):
        raise SourceLifecycleError("parents must be unique")
    return normalized


def _require_policy(policy: object) -> Literal["all", "any"]:
    if policy not in {"all", "any"}:
        raise SourceLifecycleError("policy must be 'all' or 'any'")
    return policy  # type: ignore[return-value]


class LifecycleApplication:
    """Select the lifecycle service for one Scope and expose its derived view."""

    def __init__(self, runtime: BuiltinRuntime) -> None:
        self._runtime = runtime
        self._states: dict[str, _ScopeState] = {}
        self._loaded: set[str] = set()
        self._load_lock = asyncio.Lock()
        self._database_lock = asyncio.Lock()
        self._table_ready = False

    def for_scope(self, scope_id: str, /) -> ScopedSourceLifecycleService:
        return ScopedSourceLifecycleService(self, validate_scope_id(scope_id))

    async def inactive_topics(self, scope_id: str) -> frozenset[tuple[str, str, int]]:
        """Return registered Topic Memory revisions that must leave native search."""

        state = await self.state(scope_id)
        active = state.availability()
        return frozenset(
            _topic_key(ArtifactRef.model_validate(node.reference))
            for node in state.nodes.values()
            if node.kind == "topic" and not active[node.node_id]
        )

    async def state(self, scope_id: str) -> _ScopeState:
        scope = validate_scope_id(scope_id)
        if scope in self._loaded:
            return self._states[scope]
        async with self._load_lock:
            if scope in self._loaded:
                return self._states[scope]
            state = await self._read(scope)
            self._states[scope] = state
            self._loaded.add(scope)
            return state

    def _database(self) -> Any | None:
        service = getattr(self._runtime, "_record_service", None)
        return getattr(service, "_database", None)

    async def _read(self, scope_id: str) -> _ScopeState:
        database = self._database()
        if database is None:
            return _ScopeState()
        await self._ensure_table(database)
        async with database.transaction() as connection:
            result = await connection.execute(
                text(f"SELECT payload FROM {_LIFECYCLE_TABLE} WHERE scope_id = :scope_id"),
                {"scope_id": scope_id},
            )
            row = result.first()
        return _ScopeState() if row is None else _ScopeState.decode(row[0])

    async def _ensure_table(self, database: Any) -> None:
        if self._table_ready:
            return
        async with self._database_lock:
            if self._table_ready:
                return
            async with database.transaction() as connection:
                await connection.execute(
                    text(
                        f"CREATE TABLE IF NOT EXISTS {_LIFECYCLE_TABLE} "
                        "(scope_id VARCHAR(255) PRIMARY KEY, payload TEXT NOT NULL)"
                    )
                )
            self._table_ready = True

    async def persist(self, scope_id: str, state: _ScopeState) -> None:
        database = self._database()
        if database is None:
            return
        await self._ensure_table(database)
        payload = state.encode()
        async with database.transaction() as connection:
            updated = await connection.execute(
                text(f"UPDATE {_LIFECYCLE_TABLE} SET payload = :payload WHERE scope_id = :scope_id"),
                {"scope_id": scope_id, "payload": payload},
            )
            if updated.rowcount == 0:
                await connection.execute(
                    text(f"INSERT INTO {_LIFECYCLE_TABLE} (scope_id, payload) VALUES (:scope_id, :payload)"),
                    {"scope_id": scope_id, "payload": payload},
                )


class ScopedSourceLifecycleService:
    """Register an evidence graph and apply Source lifecycle events in one Scope."""

    def __init__(self, application: LifecycleApplication, scope_id: str) -> None:
        self._application = application
        self._runtime = application._runtime
        self.scope_id = scope_id

    async def register_source(self, node_id: str, reference: SourceRef, /, *, revision: int) -> None:
        node_id = _require_node_id(node_id)
        revision = _require_positive_int(revision, "revision")
        if not isinstance(reference, SourceRef):
            raise SourceLifecycleError("reference must be a SourceRef")
        node = _Node(
            node_id=node_id,
            kind="source",
            reference=_encode_reference(reference),
            revision=revision,
        )
        async with self._runtime._scoped_operation(self.scope_id), self._runtime._locked(self.scope_id):
            await self._require_source(reference)
            state = await self._application.state(self.scope_id)
            existing = state.nodes.get(node_id)
            if existing is not None:
                if existing != node:
                    raise SourceLifecycleError("node is already registered with a different binding")
                await self._application.persist(self.scope_id, state)
                await self._sync_memories(state)
                return
            state.nodes[node_id] = node
            state.sources[node_id] = {"revision": revision, "sequence": None, "available": True, "reason": None}
            await self._application.persist(self.scope_id, state)
            await self._sync_memories(state)

    async def register_memory(
        self,
        node_id: str,
        citation: MemoryCitation,
        /,
        *,
        parents: Sequence[str],
        policy: str,
    ) -> None:
        node_id = _require_node_id(node_id)
        if not isinstance(citation, MemoryCitation):
            raise SourceLifecycleError("citation must be a MemoryCitation")
        node = _Node(
            node_id=node_id,
            kind="memory",
            reference=_encode_reference(citation),
            parents=_require_parents(parents),
            policy=_require_policy(policy),
        )
        await self._register_derived(node, readability=self._require_memory)

    async def register_topic(
        self,
        node_id: str,
        reference: ArtifactRef,
        /,
        *,
        parents: Sequence[str],
        policy: str,
    ) -> None:
        node_id = _require_node_id(node_id)
        if not isinstance(reference, ArtifactRef):
            raise SourceLifecycleError("reference must be an ArtifactRef")
        if reference.family != _TOPIC_MEMORY_FAMILY:
            raise SourceLifecycleError("reference must be a Topic Memory artifact")
        node = _Node(
            node_id=node_id,
            kind="topic",
            reference=_encode_reference(reference),
            parents=_require_parents(parents),
            policy=_require_policy(policy),
        )
        await self._register_derived(node, readability=self._require_topic)

    async def apply(self, event: SourceLifecycleEvent, /) -> list[str]:
        if not isinstance(event, SourceLifecycleEvent):
            raise SourceLifecycleError("event must be a SourceLifecycleEvent")
        async with self._runtime._scoped_operation(self.scope_id), self._runtime._locked(self.scope_id):
            state = await self._application.state(self.scope_id)
            node = state.nodes.get(event.node_id)
            if node is None or node.kind != "source":
                raise SourceLifecycleError("event targets an unregistered Source")
            source = state.sources[event.node_id]
            if event.revision != source["revision"]:
                raise SourceLifecycleError("event revision does not match the registered Source")
            last = source["sequence"]
            if last is not None:
                if event.sequence < last:
                    raise SourceLifecycleError("event sequence must increase")
                if event.sequence == last:
                    if source["available"] != event.available or source.get("reason") != event.reason:
                        raise SourceLifecycleError("event sequence already carries different content")
                    await self._application.persist(self.scope_id, state)
                    await self._sync_memories(state)
                    return sorted(node_id for node_id, active in state.availability().items() if active)
            source["sequence"] = event.sequence
            source["available"] = event.available
            source["reason"] = event.reason
            await self._application.persist(self.scope_id, state)
            await self._sync_memories(state)
            return sorted(node_id for node_id, active in state.availability().items() if active)

    async def resolve(
        self,
        node_id: str,
        /,
        *,
        purpose: str,
    ) -> SourceRef | MemoryCitation | ArtifactRef:
        node_id = _require_node_id(node_id)
        if purpose not in {"generation", "audit"}:
            raise SourceLifecycleError("unknown resolve purpose")
        state = await self._application.state(self.scope_id)
        node = state.nodes.get(node_id)
        if node is None:
            raise SourceLifecycleError("unknown lifecycle node")
        if purpose == "generation" and not state.availability()[node_id]:
            raise SourceLifecycleError("node is not available for generation")
        return _decode_reference(node)

    async def _register_derived(self, node: _Node, *, readability: Any) -> None:
        if node.node_id in node.parents:
            raise SourceLifecycleError("a derived node cannot depend on itself")
        async with self._runtime._scoped_operation(self.scope_id), self._runtime._locked(self.scope_id):
            state = await self._application.state(self.scope_id)
            existing = state.nodes.get(node.node_id)
            if existing is not None:
                if existing != node:
                    raise SourceLifecycleError("node is already registered with a different binding")
                await self._application.persist(self.scope_id, state)
                await self._sync_memories(state)
                return
            for parent in node.parents:
                if parent not in state.nodes:
                    raise SourceLifecycleError("parent must be registered before its child")
            await readability(node)
            state.nodes[node.node_id] = node
            await self._application.persist(self.scope_id, state)
            await self._sync_memories(state)

    async def _require_source(self, reference: SourceRef) -> None:
        records = self._runtime._records()
        try:
            await records.get_source(self.scope_id, reference.source_type, reference.source_id)
        except Exception as error:
            raise SourceLifecycleError("Source reference is not readable") from error

    async def _require_memory(self, node: _Node) -> None:
        citation = MemoryCitation.model_validate(node.reference)
        async with self._runtime._context(self.scope_id) as context:
            service = context.artifacts.memory
            try:
                memory = await service.revision(citation.memory_ref)
                entries = await service.entries(memory)
            except Exception as error:
                raise SourceLifecycleError("Memory citation is not readable") from error
        if not any(entry.entry_id == citation.entry_id for entry in entries):
            raise SourceLifecycleError("Memory citation is not readable")

    async def _require_topic(self, node: _Node) -> None:
        reference = ArtifactRef.model_validate(node.reference)
        try:
            await self._runtime._records().get_artifact_revision(
                self.scope_id,
                reference.family,
                reference.artifact_id,
                reference.revision,
            )
        except Exception as error:
            raise SourceLifecycleError("Topic Memory reference is not readable") from error

    async def _sync_memories(self, state: _ScopeState) -> None:
        memory_nodes = tuple(node for node in state.nodes.values() if node.kind == "memory")
        if not memory_nodes:
            return
        active = state.availability()
        async with self._runtime._context(
            self.scope_id,
            embedding_purpose=ModelUsagePurpose.MEMORY_INDEXING,
        ) as context:
            service = context.artifacts.memory
            current = await service.head(context.artifacts.memory_artifact_id)
            entries = {entry.entry_id: entry for entry in await service.entries(current)}
            states = {item.entry_id: item.state for item in current.content.manifest.entries}
            deactivate = []
            reactivate = []
            for node in memory_nodes:
                citation = MemoryCitation.model_validate(node.reference)
                entry = entries.get(citation.entry_id)
                if entry is None:
                    raise SourceLifecycleError("registered Memory entry is no longer readable")
                desired = active[node.node_id]
                current_state = states.get(citation.entry_id)
                if desired and current_state != "active":
                    reactivate.append(entry)
                elif not desired and current_state != "inactive":
                    deactivate.append(entry)
            if deactivate:
                current = await service.forget(current, entries=tuple(deactivate), reason=_LIFECYCLE_REASON)
            if reactivate:
                entries = {entry.entry_id: entry for entry in await service.entries(current)}
                current = await service.reactivate(
                    current,
                    entries=tuple(entries[entry.entry_id] for entry in reactivate),
                    reason=_LIFECYCLE_REASON,
                )
