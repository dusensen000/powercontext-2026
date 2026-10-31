"""MiniMax client: turn a context bundle into a unified diff.

Two providers are supported:

* ``live`` – call the MiniMax chat completion endpoint (official protocol or the
  OpenAI-compatible one) using only the standard library.
* ``stub`` – replay a known-good diff, used for offline smoke tests and for
  verifying the rest of the pipeline without spending tokens.

Both providers return plain text; :func:`extract_diff` normalises it into a
unified diff that :mod:`sddctx.agent` can apply.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

from . import config
from .context import render_context_text

SYSTEM_PROMPT = """你是一名在规范驱动开发（SDD）流程中工作的资深 Python 工程师。
你只能依据用户给出的《开发上下文》工作，不得臆造上下文中不存在的模块或接口。

输出要求（严格遵守）：
1. 只输出一个 unified diff（git 格式），以 `diff --git a/... b/...` 开头；
2. 不要输出解释、Markdown 代码块围栏、测试用例或任何额外文字；
3. 只修改 `src/` 下的实现文件，禁止修改 `tests/` 与 `specs/`；
4. 必须实现上下文中所有生效的需求（REQ-*），并保持既有行为不变。"""


def build_messages(
    bundle: Dict[str, Any], file_contents: Dict[str, str], failure: str | None
) -> List[Dict[str, str]]:
    parts = [
        "# 开发上下文",
        f"## 任务\n{bundle['task']}",
        "## 生效规格与相关证据",
        render_context_text(bundle),
        "## 当前源码",
    ]
    for path, text in file_contents.items():
        parts.append(f"### {path}\n```python\n{text}\n```")
    if failure:
        parts.append("## 上一轮失败测试输出（请修复）\n```text\n" + failure[-4000:] + "\n```")
    parts.append("现在输出修复该任务的 unified diff。")
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def config_context_text(bundle: Dict[str, Any]) -> str:
    from .context import render_context_text

    return render_context_text(bundle)


# --------------------------------------------------------------------------- #
# providers
# --------------------------------------------------------------------------- #
class StubClient:
    """Deterministic provider that replays a stored diff."""

    def __init__(self, patch: Path | None = None) -> None:
        self.patch = patch or (Path(__file__).resolve().parent / "golden_patch.diff")

    def complete(self, messages: List[Dict[str, str]]) -> str:
        return self.patch.read_text(encoding="utf-8")


class MiniMaxClient:
    def __init__(self) -> None:
        if not config.MINIMAX_API_KEY:
            raise RuntimeError(
                "MINIMAX_API_KEY is not set; export it or run with SDDCTX_PROVIDER=stub"
            )
        self.base_url = config.MINIMAX_BASE_URL
        self.model = config.MINIMAX_MODEL
        self.protocol = config.MINIMAX_PROTOCOL
        self.api_key = config.MINIMAX_API_KEY

    def _endpoint(self) -> str:
        if self.protocol == "openai":
            return f"{self.base_url}/v1/chat/completions"
        return f"{self.base_url}/v1/text/chatcompletion_v2"

    def complete(self, messages: List[Dict[str, str]]) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 4096,
        }
        request = urllib.request.Request(
            self._endpoint(),
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                body = json.load(response)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"MiniMax HTTP {error.code}: {detail[:800]}") from error

        base_resp = body.get("base_resp") or {}
        if base_resp.get("status_code") not in (None, 0):
            raise RuntimeError(f"MiniMax error: {base_resp}")
        choices = body.get("choices") or []
        if choices:
            message = choices[0].get("message") or {}
            content = message.get("content")
            if isinstance(content, list):  # some providers return content blocks
                content = "".join(
                    block.get("text", "") for block in content if isinstance(block, dict)
                )
            if content:
                return str(content)
        if body.get("reply"):
            return str(body["reply"])
        raise RuntimeError(f"MiniMax response has no content: {json.dumps(body)[:500]}")


def get_client():
    if config.PROVIDER == "stub":
        return StubClient()
    return MiniMaxClient()


# --------------------------------------------------------------------------- #
# diff handling
# --------------------------------------------------------------------------- #
_FENCE = re.compile(r"```(?:diff|patch)?\s*(.*?)```", re.DOTALL)
_DIFF_START = re.compile(r"^diff --git ", re.MULTILINE)


def extract_diff(reply: str) -> str:
    """Strip fences and any prose around the unified diff."""
    text = reply.strip()
    fences = _FENCE.findall(text)
    if fences:
        text = max(fences, key=len).strip()
    match = _DIFF_START.search(text)
    if match:
        text = text[match.start() :]
    if not text.endswith("\n"):
        text += "\n"
    if not _DIFF_START.search(text) and "@@" not in text:
        raise ValueError("model reply contains no unified diff")
    return text
