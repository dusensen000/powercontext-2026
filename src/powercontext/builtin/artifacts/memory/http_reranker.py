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

"""HTTP scoring-service reranking with cross-batch global ordering."""

from __future__ import annotations

import math
from typing import Any

import httpx

from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.artifacts.memory.reranking import MemoryRerankDecision
from powercontext.builtin.inference import InferenceUsage

DEFAULT_POLICY_ID = "http-cross-encoder-v1"

__all__ = ["HTTPMemoryReranker"]


class HTTPMemoryReranker:
    """Score a coarse candidate pool through one batched HTTP contract."""

    def __init__(
        self,
        endpoint: str,
        *,
        client: httpx.AsyncClient,
        batch_size: int = 32,
        policy_id: str = DEFAULT_POLICY_ID,
    ) -> None:
        if not isinstance(endpoint, str) or not endpoint.strip():
            raise ValueError("endpoint must be a non-empty URL")  # noqa: TRY003
        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size <= 0:
            raise ValueError("batch_size must be a positive integer")  # noqa: TRY003
        if not isinstance(policy_id, str) or not policy_id.strip():
            raise ValueError("policy_id must be a non-empty string")  # noqa: TRY003
        self._endpoint = endpoint
        self._client = client
        self._batch_size = batch_size
        self.policy_id = policy_id

    async def rerank(
        self,
        query: str,
        candidates: tuple[MemoryHit, ...],
        limit: int,
        /,
    ) -> MemoryRerankDecision:
        """Score every candidate once, then select from the whole pool."""

        candidate_count = len(candidates)
        if candidate_count < 1:
            raise ValueError("rerank requires at least one candidate")  # noqa: TRY003
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > candidate_count:
            raise ValueError("rerank limit must be between one and the candidate count")  # noqa: TRY003

        scores: dict[int, float] = {}
        requests = 0
        for start in range(0, candidate_count, self._batch_size):
            batch = candidates[start : start + self._batch_size]
            ranks = tuple(range(start + 1, start + len(batch) + 1))
            payload = {
                "query": query,
                "candidates": [
                    {"rank": rank, "text": candidate.text}
                    for rank, candidate in zip(ranks, batch, strict=True)
                ],
            }
            response = await self._client.post(self._endpoint, json=payload)
            response.raise_for_status()
            requests += 1
            batch_scores = _parse_response(response, ranks)
            scores.update(batch_scores)

        ordered = tuple(
            sorted(scores, key=lambda rank: (-scores[rank], rank))[:limit]
        )
        return MemoryRerankDecision(
            selected_ranks=ordered,
            usage=InferenceUsage(requests=requests),
        )


def _parse_response(response: httpx.Response, expected_ranks: tuple[int, ...]) -> dict[int, float]:
    try:
        payload: Any = response.json()
    except ValueError as error:
        raise ValueError("reranker response must be valid JSON") from error

    if not isinstance(payload, dict) or set(payload) != {"scores"}:
        raise ValueError("reranker response must contain exactly the scores field")  # noqa: TRY003
    entries = payload["scores"]
    if not isinstance(entries, list):
        raise ValueError("reranker scores must be a list")  # noqa: TRY003

    scores: dict[int, float] = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"rank", "score"}:
            raise ValueError("each reranker score must contain exactly rank and score")  # noqa: TRY003
        rank = entry["rank"]
        score = entry["score"]
        if isinstance(rank, bool) or not isinstance(rank, int):
            raise ValueError("reranker score rank must be an integer")  # noqa: TRY003
        if rank not in expected_ranks:
            raise ValueError(f"reranker score rank {rank} is not part of this batch")  # noqa: TRY003
        if rank in scores:
            raise ValueError(f"reranker score rank {rank} was returned more than once")  # noqa: TRY003
        if isinstance(score, bool) or not isinstance(score, int | float):
            raise ValueError("reranker score must be a finite number")  # noqa: TRY003
        numeric = float(score)
        if not math.isfinite(numeric):
            raise ValueError("reranker score must be a finite number")  # noqa: TRY003
        scores[rank] = numeric

    if set(scores) != set(expected_ranks):
        raise ValueError("reranker response must cover every rank in this batch exactly once")  # noqa: TRY003
    return scores
