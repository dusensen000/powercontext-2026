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

"""Coalesce concurrent embedding requests and cache successful vectors."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from powercontext.builtin.inference.models import EmbeddingResult, EmbeddingVector, InferenceUsage

if TYPE_CHECKING:
    from powercontext.builtin.artifacts.memory.models import EmbeddingProfile
    from powercontext.builtin.inference.protocols import EmbeddingModel

__all__ = ["CoalescingEmbeddingModel"]


@dataclass(eq=False)
class _Batch:
    texts: tuple[str, ...]
    futures: dict[str, asyncio.Future[_Completion]]
    usage: InferenceUsage = field(default_factory=lambda: InferenceUsage(requests=0))


@dataclass(frozen=True)
class _Completion:
    vector: EmbeddingVector
    batch: _Batch


class CoalescingEmbeddingModel:
    """Share in-flight work per text and reuse successful vectors across calls."""

    def __init__(
        self,
        model: EmbeddingModel,
        *,
        max_batch_size: int = 64,
        coalesce_ms: float = 5.0,
        cache_size: int = 1024,
    ) -> None:
        if isinstance(max_batch_size, bool) or not isinstance(max_batch_size, int) or max_batch_size < 1:
            raise ValueError("max_batch_size must be a positive integer")  # noqa: TRY003
        if isinstance(coalesce_ms, bool) or not isinstance(coalesce_ms, int | float) or coalesce_ms < 0:
            raise ValueError("coalesce_ms must be a non-negative number")  # noqa: TRY003
        if isinstance(cache_size, bool) or not isinstance(cache_size, int) or cache_size < 0:
            raise ValueError("cache_size must be a non-negative integer")  # noqa: TRY003
        self._model = model
        self.profile: EmbeddingProfile = model.profile
        self._max_batch_size = max_batch_size
        self._coalesce_ms = float(coalesce_ms)
        self._cache_size = cache_size
        self._cache: OrderedDict[str, EmbeddingVector] = OrderedDict()
        self._pending: dict[str, asyncio.Future[_Completion]] = {}
        self._inflight: dict[str, asyncio.Future[_Completion]] = {}
        self._wake: asyncio.Event | None = None
        self._worker: asyncio.Task[None] | None = None
        self._tasks: set[asyncio.Task[None]] = set()

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        """Embed one ordered batch, sharing work with concurrent callers."""

        if not texts:
            return EmbeddingResult(vectors=(), usage=InferenceUsage(requests=0))

        unique = tuple(dict.fromkeys(texts))
        vectors: dict[str, EmbeddingVector] = {}
        waiting: dict[str, asyncio.Future[_Completion]] = {}
        for text in unique:
            cached = self._cache_get(text)
            if cached is not None:
                vectors[text] = cached
                continue
            future = self._inflight.get(text) or self._pending.get(text)
            if future is None:
                future = asyncio.get_running_loop().create_future()
                self._pending[text] = future
                self._ensure_worker()
                assert self._wake is not None
                self._wake.set()
            waiting[text] = future

        batches: dict[int, _Batch] = {}
        if waiting:
            await asyncio.wait(tuple(waiting.values()))
            for text, future in waiting.items():
                completion = future.result()
                vectors[text] = completion.vector
                batches[id(completion.batch)] = completion.batch

        requests = 0
        input_tokens = 0
        output_tokens = 0
        has_tokens = False
        for batch in batches.values():
            usage = batch.usage
            requests += usage.requests
            if usage.input_tokens is not None:
                has_tokens = True
                input_tokens += usage.input_tokens
            if usage.output_tokens is not None:
                has_tokens = True
                output_tokens += usage.output_tokens
        return EmbeddingResult(
            vectors=tuple(vectors[text] for text in texts),
            usage=InferenceUsage(
                requests=requests,
                input_tokens=input_tokens if has_tokens else None,
                output_tokens=output_tokens if has_tokens else None,
            ),
        )

    def _cache_get(self, text: str) -> EmbeddingVector | None:
        if self._cache_size == 0:
            return None
        vector = self._cache.get(text)
        if vector is not None:
            self._cache.move_to_end(text)
        return vector

    def _cache_put(self, text: str, vector: EmbeddingVector) -> None:
        if self._cache_size == 0:
            return
        self._cache[text] = vector
        self._cache.move_to_end(text)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)

    def _ensure_worker(self) -> None:
        if self._worker is None or self._worker.done():
            self._wake = asyncio.Event()
            self._worker = asyncio.get_running_loop().create_task(self._dispatch_loop())
            self._worker.add_done_callback(self._consume_worker_result)

    @staticmethod
    def _consume_worker_result(task: asyncio.Task[None]) -> None:
        try:
            task.result()
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass

    async def _dispatch_loop(self) -> None:
        assert self._wake is not None
        while True:
            await self._wake.wait()
            self._wake.clear()
            if not self._pending:
                continue
            if self._coalesce_ms:
                await asyncio.sleep(self._coalesce_ms / 1000.0)
            while self._pending:
                texts: list[str] = []
                futures: dict[str, asyncio.Future[_Completion]] = {}
                for text, future in list(self._pending.items()):
                    if len(texts) >= self._max_batch_size:
                        break
                    texts.append(text)
                    futures[text] = future
                    del self._pending[text]
                    self._inflight[text] = future
                batch = _Batch(texts=tuple(texts), futures=futures)
                task = asyncio.get_running_loop().create_task(self._execute(batch))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)

    async def _execute(self, batch: _Batch) -> None:
        try:
            result = await self._model.embed(batch.texts)
            if len(result.vectors) != len(batch.texts):
                raise ValueError("embedding vector count does not match the input text count")  # noqa: TRY003
            batch.usage = result.usage
            for text, vector in zip(batch.texts, result.vectors, strict=True):
                stored = tuple(vector)
                self._cache_put(text, stored)
                future = batch.futures[text]
                if not future.done():
                    future.set_result(_Completion(vector=stored, batch=batch))
        except Exception as error:
            for future in batch.futures.values():
                if not future.done():
                    future.set_exception(error)
        finally:
            for text in batch.texts:
                self._inflight.pop(text, None)
            if self._pending and self._wake is not None:
                self._wake.set()
