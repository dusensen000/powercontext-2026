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

"""seekdb Memory search index answering both channels in one native statement."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pyobvector import VECTOR
from sqlalchemy import Table, TextClause, bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory import (
    CapabilityNotSupportedError,
    EmbeddingProfile,
    MemoryCapabilities,
    MemoryProjection,
    MemorySearchChannels,
    MemorySearchRequest,
)
from powercontext.builtin.artifacts.memory.canonical import validate_embedding
from powercontext.builtin.persistence.memory_index import memory_channel_hits
from powercontext.builtin.persistence.oceanbase.memory_index import (
    OceanBaseMemoryFTSIndex,
    OceanBaseMemoryVectorIndex,
)
from powercontext.builtin.persistence.tags import memory_tag_parameters, memory_tag_sql

_SEEKDB_HYBRID_SQL_TEMPLATE = """
(
    SELECT 'fts' AS channel,
           f.memory_artifact_id AS memory_artifact_id,
           f.head_revision AS head_revision,
           f.entry_id AS entry_id,
           f.entry_version_id AS entry_version_id,
           v.text AS text,
           MATCH (f.searchable_text) AGAINST (:fts_query) AS score,
           NULL AS distance
    FROM pc_memory_entry_heads AS f
    JOIN pc_memory_entry_versions AS v
      ON v.scope_id = f.scope_id
     AND v.memory_artifact_id = f.memory_artifact_id
     AND v.entry_version_id = f.entry_version_id
    WHERE f.scope_id = :scope_id
      AND f.memory_artifact_id IN :memory_artifact_ids
      {fts_tags}
      AND MATCH (f.searchable_text) AGAINST (:fts_query)
    ORDER BY score DESC,
             f.memory_artifact_id, f.entry_id, f.entry_version_id
    LIMIT :candidate_limit
)
UNION ALL
(
    SELECT 'vector' AS channel,
           m.memory_artifact_id AS memory_artifact_id,
           m.head_revision AS head_revision,
           m.entry_id AS entry_id,
           m.entry_version_id AS entry_version_id,
           v.text AS text,
           NULL AS score,
           l2_distance(m.embedding, :query_vector) AS distance
    FROM pc_memory_vector_entries AS m
    JOIN pc_memory_entry_versions AS v
      ON v.scope_id = m.scope_id
     AND v.memory_artifact_id = m.memory_artifact_id
     AND v.entry_version_id = m.entry_version_id
    WHERE m.scope_id = :scope_id
      AND m.memory_artifact_id IN :memory_artifact_ids
      {vector_tags}
    ORDER BY l2_distance(m.embedding, :query_vector) APPROXIMATE
    LIMIT :candidate_limit
)
"""
_SEEKDB_HYBRID_SQL = _SEEKDB_HYBRID_SQL_TEMPLATE.format(fts_tags="", vector_tags="")
_SEEKDB_TAGGED_HYBRID_SQL = _SEEKDB_HYBRID_SQL_TEMPLATE.format(
    fts_tags=memory_tag_sql("f"),
    vector_tags=memory_tag_sql("m"),
)


class SeekDBMemoryIndex:
    """One UNION ALL statement returns both the FTS and vector candidate rankings.

    Each branch keeps the native index access of the frozen single-channel path
    (``TEXT RETRIEVAL SCAN`` and ``VECTOR INDEX``); the application still fuses
    the two ordered channel rankings.
    """

    def __init__(self, profile: EmbeddingProfile | None) -> None:
        self._fts = OceanBaseMemoryFTSIndex()
        self._vector = None if profile is None else OceanBaseMemoryVectorIndex(profile)
        self.capabilities = MemoryCapabilities(
            fts=True,
            vector=self._vector is not None,
            hybrid=self._vector is not None,
            embedding_profile=profile,
            tag_filter=True,
        )
        self.tables: tuple[Table, ...] = (
            self._fts.tables if self._vector is None else self._fts.tables + self._vector.tables
        )
        self._hybrid_sql = (
            None
            if self._vector is None
            else _bind_hybrid(text(_SEEKDB_HYBRID_SQL), profile, tags=False)
        )
        self._tagged_hybrid_sql = (
            None
            if self._vector is None
            else _bind_hybrid(text(_SEEKDB_TAGGED_HYBRID_SQL), profile, tags=True)
        )

    async def initialize(self, connection: AsyncConnection, /) -> None:
        await self._fts.initialize(connection)
        if self._vector is not None:
            await self._vector.initialize(connection)

    async def replace(
        self,
        connection: AsyncConnection,
        scope_id: str,
        memory_ref: ArtifactRef,
        projections: tuple[MemoryProjection, ...],
        /,
    ) -> None:
        await self._fts.replace(connection, scope_id, memory_ref, projections)
        if self._vector is not None:
            await self._vector.replace(connection, scope_id, memory_ref, projections)

    async def delete(
        self,
        connection: AsyncConnection,
        scope_id: str,
        memory_ref: ArtifactRef,
        entry_ids: tuple[str, ...],
        /,
    ) -> None:
        await self._fts.delete(connection, scope_id, memory_ref, entry_ids)
        if self._vector is not None:
            await self._vector.delete(connection, scope_id, memory_ref, entry_ids)

    async def upsert(
        self,
        connection: AsyncConnection,
        scope_id: str,
        memory_ref: ArtifactRef,
        projections: tuple[MemoryProjection, ...],
        /,
    ) -> None:
        await self._fts.upsert(connection, scope_id, memory_ref, projections)
        if self._vector is not None:
            await self._vector.upsert(connection, scope_id, memory_ref, projections)

    async def search(
        self,
        connection: AsyncConnection,
        scope_id: str,
        request: MemorySearchRequest,
        /,
    ) -> MemorySearchChannels:
        if request.mode == "fts":
            return await self._fts.search(connection, scope_id, request)
        if request.mode == "vector":
            if self._vector is None:
                raise CapabilityNotSupportedError("vector")
            return await self._vector.search(connection, scope_id, request)
        if request.mode != "hybrid" or self._vector is None:
            return MemorySearchChannels()
        profile = self._vector.profile
        if request.embedding_profile != profile or request.query_vector is None:
            raise CapabilityNotSupportedError("embedding-profile")
        if not await self._vector.vector_complete(connection, scope_id, request.memories, profile):
            raise CapabilityNotSupportedError("vector")
        rows = (
            await connection.execute(
                self._hybrid_sql if request.tag_filter is None else self._tagged_hybrid_sql,
                {
                    "scope_id": scope_id,
                    "memory_artifact_ids": tuple(memory.artifact_id for memory in request.memories),
                    "fts_query": request.analyzed_query,
                    "query_vector": validate_embedding(
                        request.query_vector,
                        dimension=profile.dimension,
                    ),
                    "candidate_limit": request.candidate_limit,
                    **memory_tag_parameters(request.tag_filter),
                },
            )
        ).mappings().all()
        return MemorySearchChannels(
            fts=memory_channel_hits(_fts_rows(rows), request.memories),
            vector=memory_channel_hits(_vector_rows(rows), request.memories),
        )

    async def vector_complete(
        self,
        connection: AsyncConnection,
        scope_id: str,
        memories: tuple[ArtifactRef, ...],
        profile: EmbeddingProfile,
        /,
    ) -> bool:
        if self._vector is None:
            return False
        return await self._vector.vector_complete(connection, scope_id, memories, profile)

    async def hydrate(
        self,
        connection: AsyncConnection,
        scope_id: str,
        projections: tuple[MemoryProjection, ...],
        /,
    ) -> tuple[MemoryProjection, ...]:
        if self._vector is None:
            return await self._fts.hydrate(connection, scope_id, projections)
        return await self._vector.hydrate(connection, scope_id, projections)


def _bind_hybrid(statement: TextClause, profile: EmbeddingProfile, *, tags: bool) -> TextClause:
    statement = statement.bindparams(
        bindparam("memory_artifact_ids", expanding=True),
        bindparam("query_vector", type_=VECTOR(profile.dimension)),
    )
    if tags:
        statement = statement.bindparams(
            bindparam("tag_keys", expanding=True),
            bindparam("tag_hashes", expanding=True),
        )
    return statement


def _fts_rows(rows: Sequence[Mapping[Any, Any]]) -> tuple[Mapping[Any, Any], ...]:
    return tuple(
        sorted(
            (row for row in rows if str(row["channel"]) == "fts"),
            key=lambda row: (
                -float(row["score"]),
                str(row["memory_artifact_id"]).encode("utf-8"),
                str(row["entry_id"]).encode("utf-8"),
                str(row["entry_version_id"]).encode("utf-8"),
            ),
        )
    )


def _vector_rows(rows: Sequence[Mapping[Any, Any]]) -> tuple[Mapping[Any, Any], ...]:
    return tuple(
        sorted(
            (row for row in rows if str(row["channel"]) == "vector"),
            key=lambda row: (
                float(row["distance"]),
                str(row["memory_artifact_id"]).encode("utf-8"),
                str(row["entry_id"]).encode("utf-8"),
                str(row["entry_version_id"]).encode("utf-8"),
            ),
        )
    )
