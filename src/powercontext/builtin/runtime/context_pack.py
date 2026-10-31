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

"""Context Packs and prefix deltas for incremental context transport."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from typing import Any

PACK_SCHEMA = "powercontext.context-pack.v1"
DELTA_SCHEMA = "powercontext.context-pack-delta.v1"

__all__ = [
    "ContextPack",
    "ContextPackDelta",
    "ContextPackError",
    "apply_context_pack_delta",
]


class ContextPackError(ValueError):
    """A Context Pack or delta violated the wire protocol."""


@dataclass(frozen=True)
class ContextPack:
    """One complete chunked context and its verified wire identity."""

    items: tuple[bytes, ...]
    digest: str
    byte_count: int

    @classmethod
    def build(cls, items: tuple[bytes, ...]) -> ContextPack:
        chunks = _validate_items(items)
        digest = _digest(chunks)
        byte_count = _measure_pack(chunks, digest)
        return cls(items=chunks, digest=digest, byte_count=byte_count)

    @classmethod
    def from_content(cls, content: str, *, chunk_bytes: int = 512) -> ContextPack:
        if not isinstance(content, str):
            raise ContextPackError("content must be a string")  # noqa: TRY003
        if isinstance(chunk_bytes, bool) or not isinstance(chunk_bytes, int) or chunk_bytes < 1:
            raise ContextPackError("chunk_bytes must be a positive integer")  # noqa: TRY003
        data = content.encode("utf-8")
        chunks: list[bytes] = []
        position = 0
        while position < len(data):
            end = min(position + chunk_bytes, len(data))
            cut = end
            while cut < len(data) and cut > position and data[cut] & 0xC0 == 0x80:
                cut -= 1
            if cut == position:
                raise ContextPackError("chunk_bytes cannot hold the next UTF-8 character")  # noqa: TRY003
            chunks.append(data[position:cut])
            position = cut
        return cls.build(tuple(chunks))

    def to_bytes(self) -> bytes:
        return _pack_bytes(self.items, self.digest, self.byte_count)

    @classmethod
    def from_bytes(cls, data: bytes) -> ContextPack:
        payload = _decode_json(data)
        if set(payload) != {"schema", "items", "digest", "byte_count"}:
            raise ContextPackError("pack must contain exactly schema, items, digest, byte_count")  # noqa: TRY003
        if payload["schema"] != PACK_SCHEMA:
            raise ContextPackError("unsupported context pack schema")  # noqa: TRY003
        items = _decode_items(payload["items"], "items")
        digest = payload["digest"]
        if not isinstance(digest, str) or digest != _digest(items):
            raise ContextPackError("context pack digest does not match its items")  # noqa: TRY003
        byte_count = payload["byte_count"]
        if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count != len(data):
            raise ContextPackError("context pack byte_count does not match its wire bytes")  # noqa: TRY003
        return cls(items=items, digest=digest, byte_count=byte_count)


@dataclass(frozen=True)
class ContextPackDelta:
    """The suffix appended to a retained prefix of a base pack."""

    base_digest: str
    target_digest: str
    prefix_items: int
    appended: tuple[bytes, ...]

    def __post_init__(self) -> None:
        _validate_digest(self.base_digest)
        _validate_digest(self.target_digest)
        if (
            isinstance(self.prefix_items, bool)
            or not isinstance(self.prefix_items, int)
            or self.prefix_items < 0
        ):
            raise ContextPackError("prefix_items must be a non-negative integer")  # noqa: TRY003
        _validate_items(self.appended)
        if not isinstance(self.appended, tuple):
            raise ContextPackError("appended must be a tuple of bytes")  # noqa: TRY003

    @classmethod
    def between(cls, base: ContextPack, target: ContextPack) -> ContextPackDelta:
        prefix = 0
        for left, right in zip(base.items, target.items):
            if left != right:
                break
            prefix += 1
        return cls(
            base_digest=base.digest,
            target_digest=target.digest,
            prefix_items=prefix,
            appended=target.items[prefix:],
        )

    @property
    def byte_count(self) -> int:
        return len(self.to_bytes())

    def to_bytes(self) -> bytes:
        payload = {
            "schema": DELTA_SCHEMA,
            "base_digest": self.base_digest,
            "target_digest": self.target_digest,
            "prefix_items": self.prefix_items,
            "appended": [_encode_item(item) for item in self.appended],
        }
        return _canonical(payload)

    @classmethod
    def from_bytes(cls, data: bytes) -> ContextPackDelta:
        payload = _decode_json(data)
        if set(payload) != {"schema", "base_digest", "target_digest", "prefix_items", "appended"}:
            raise ContextPackError("delta must contain exactly its five wire fields")  # noqa: TRY003
        if payload["schema"] != DELTA_SCHEMA:
            raise ContextPackError("unsupported context pack delta schema")  # noqa: TRY003
        appended = _decode_items(payload["appended"], "appended")
        return cls(
            base_digest=payload["base_digest"],
            target_digest=payload["target_digest"],
            prefix_items=payload["prefix_items"],
            appended=appended,
        )


def apply_context_pack_delta(base: ContextPack, delta: ContextPackDelta) -> ContextPack:
    """Rebuild the target pack from a base pack and one delta."""

    if not isinstance(base, ContextPack):
        raise ContextPackError("base must be a ContextPack")  # noqa: TRY003
    if not isinstance(delta, ContextPackDelta):
        raise ContextPackError("delta must be a ContextPackDelta")  # noqa: TRY003
    if base.digest != delta.base_digest:
        raise ContextPackError("delta base digest does not match the base pack")  # noqa: TRY003
    if delta.prefix_items > len(base.items):
        raise ContextPackError("delta prefix exceeds the base pack item count")  # noqa: TRY003
    target = ContextPack.build((*base.items[: delta.prefix_items], *delta.appended))
    if target.digest != delta.target_digest:
        raise ContextPackError("rebuilt target digest does not match the delta")  # noqa: TRY003
    return target


def _validate_items(items: Any) -> tuple[bytes, ...]:
    if not isinstance(items, tuple):
        raise ContextPackError("items must be a tuple of bytes")  # noqa: TRY003
    for item in items:
        if not isinstance(item, bytes):
            raise ContextPackError("every chunk must be bytes")  # noqa: TRY003
    return items


def _validate_digest(digest: Any) -> None:
    if not isinstance(digest, str) or not digest:
        raise ContextPackError("digest must be a non-empty string")  # noqa: TRY003


def _encode_item(item: bytes) -> str:
    return base64.b64encode(item).decode("ascii")


def _decode_items(value: Any, field: str) -> tuple[bytes, ...]:
    if not isinstance(value, list):
        raise ContextPackError(f"{field} must be a list of Base64 strings")  # noqa: TRY003
    items: list[bytes] = []
    for encoded in value:
        if not isinstance(encoded, str):
            raise ContextPackError(f"{field} must contain only Base64 strings")  # noqa: TRY003
        try:
            items.append(base64.b64decode(encoded.encode("ascii"), validate=True))
        except (UnicodeEncodeError, binascii.Error) as error:
            raise ContextPackError(f"{field} contains invalid Base64") from error
    return tuple(items)


def _decode_json(data: bytes) -> dict[str, Any]:
    if not isinstance(data, bytes):
        raise ContextPackError("wire payload must be bytes")  # noqa: TRY003
    try:
        payload = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContextPackError("wire payload must be valid UTF-8 JSON") from error
    if not isinstance(payload, dict):
        raise ContextPackError("wire payload must be a JSON object")  # noqa: TRY003
    return payload


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(items: tuple[bytes, ...]) -> str:
    unsigned = {"schema": PACK_SCHEMA, "items": [_encode_item(item) for item in items]}
    return "sha256:" + hashlib.sha256(_canonical(unsigned)).hexdigest()


def _pack_bytes(items: tuple[bytes, ...], digest: str, byte_count: int) -> bytes:
    return _canonical(
        {
            "schema": PACK_SCHEMA,
            "items": [_encode_item(item) for item in items],
            "digest": digest,
            "byte_count": byte_count,
        }
    )


def _measure_pack(items: tuple[bytes, ...], digest: str) -> int:
    size = 0
    while True:
        measured = len(_pack_bytes(items, digest, size))
        if measured == size:
            return size
        size = measured
