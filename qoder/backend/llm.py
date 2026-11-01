from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI

from .config import STEP_API_KEY, STEP_BASE_URL, STEP_MODEL

_client: OpenAI | None = None
_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=STEP_API_KEY, base_url=STEP_BASE_URL)
    return _client


def chat_json(system: str, user: str, *, model: str | None = None) -> dict[str, Any]:
    response = get_client().chat.completions.create(
        model=model or STEP_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0,
    )
    return parse_json(response.choices[0].message.content or "")


def parse_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    fenced = _FENCE.search(stripped)
    if fenced:
        stripped = fenced.group(1).strip()
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for index, char in enumerate(stripped):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError(f"模型输出无法解析为 JSON：{text[:200]}")
