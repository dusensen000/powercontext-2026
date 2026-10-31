"""Apply model-produced diffs and run the sample project's tests."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from . import config
from .minimax_client import build_messages, extract_diff, get_client

TARGET_TESTS = "tests/test_target_filter.py"
REGRESSION_TESTS = "tests/test_regression.py"
MAX_ATTEMPTS = 3

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@")


# --------------------------------------------------------------------------- #
# workspace
# --------------------------------------------------------------------------- #
def prepare_workdir(source: Path | None = None, dest: Path | None = None) -> Path:
    source = source or config.SAMPLE
    dest = dest or (config.WORK / "sample")
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        source,
        dest,
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc"),
    )
    return dest


def source_files(workdir: Path, paths: List[str]) -> Dict[str, str]:
    files: Dict[str, str] = {}
    for rel in paths:
        if not rel.startswith("src/"):
            continue
        path = workdir / rel
        if path.is_file():
            files[rel] = path.read_text(encoding="utf-8")
    return files or {
        "src/taskboard/service.py": (workdir / "src/taskboard/service.py").read_text(
            encoding="utf-8"
        )
    }


# --------------------------------------------------------------------------- #
# diff application
# --------------------------------------------------------------------------- #
def apply_diff(text: str, root: Path) -> List[str]:
    """Apply ``text`` to ``root``.

    The pure-Python applier runs first: ``git apply`` resolves paths against the
    enclosing repository root, which is wrong when the work copy lives inside a
    larger checkout. ``git``/``patch`` remain as fallbacks for unusual hunks.
    """
    errors: List[str] = []
    try:
        return _apply_python(text, root)
    except Exception as exc:  # noqa: BLE001 - fall through to external tools
        errors.append(f"python: {exc}")

    for cmd in (
        ["git", "apply", "-p1", "--recount", "--whitespace=nowarn", "-"],
        ["patch", "-p1", "--batch", "--forward"],
    ):
        try:
            proc = subprocess.run(
                cmd, cwd=root, input=text, text=True,
                capture_output=True, timeout=60,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            errors.append(f"{cmd[0]}: {exc}")
            continue
        if proc.returncode == 0:
            return _touched_files(text)
        errors.append(f"{cmd[0]}: {proc.stderr.strip()[:400]}")

    raise RuntimeError("could not apply diff | " + " | ".join(errors))


def _touched_files(text: str) -> List[str]:
    files = []
    for line in text.splitlines():
        if line.startswith("+++ "):
            path = line[4:].split("\t")[0].strip().strip('"')
            if path.startswith("b/"):
                path = path[2:]
            if path not in ("/dev/null", "") and path not in files:
                files.append(path)
    return files


def _parse(text: str) -> List[Dict[str, Any]]:
    files: List[Dict[str, Any]] = []
    current: Dict[str, Any] | None = None
    hunk: Dict[str, Any] | None = None
    for line in text.splitlines():
        if line.startswith("diff --git "):
            current = None
            hunk = None
        elif line.startswith("--- "):
            current = {"path": None, "hunks": []}
            files.append(current)
            hunk = None
        elif line.startswith("+++ ") and current is not None:
            path = line[4:].split("\t")[0].strip().strip('"')
            current["path"] = path[2:] if path.startswith("b/") else path
        else:
            match = _HUNK.match(line)
            if match and current is not None:
                hunk = {"old_start": int(match.group(1)), "lines": []}
                current["hunks"].append(hunk)
            elif hunk is not None and line[:1] in (" ", "+", "-"):
                hunk["lines"].append(line)
    return [f for f in files if f["path"] and f["hunks"]]


def _apply_python(text: str, root: Path) -> List[str]:
    touched: List[str] = []
    for spec in _parse(text):
        path = root / spec["path"]
        lines = path.read_text(encoding="utf-8").splitlines()
        offset = 0
        for hunk in spec["hunks"]:
            old = [line[1:] for line in hunk["lines"] if not line.startswith("+")]
            new = [line[1:] for line in hunk["lines"] if not line.startswith("-")]
            start = max(hunk["old_start"] - 1 + offset, 0)
            pos = _locate(lines, old, start)
            if pos is None:
                raise RuntimeError(f"hunk not found in {spec['path']} at line {start + 1}")
            lines[pos : pos + len(old)] = new
            offset += len(new) - len(old)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        touched.append(spec["path"])
    if not touched:
        raise RuntimeError("diff parsed to zero files")
    return touched


def _locate(lines: List[str], old: List[str], start: int) -> int | None:
    if not old:
        return min(start, len(lines))
    limit = min(len(lines), start + 200)
    for pos in range(start, limit - len(old) + 1):
        if lines[pos : pos + len(old)] == old:
            return pos
    for pos in range(0, len(lines) - len(old) + 1):
        if lines[pos : pos + len(old)] == old:
            return pos
    return None


# --------------------------------------------------------------------------- #
# tests
# --------------------------------------------------------------------------- #
def run_pytest(workdir: Path, target: str, log_name: str) -> Dict[str, Any]:
    config.ensure_dirs()
    started = time.time()
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", target, "-q", "--no-header"],
        cwd=workdir,
        text=True,
        capture_output=True,
        timeout=180,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    duration = round(time.time() - started, 3)
    output = (proc.stdout + proc.stderr).strip()
    version = code_version(workdir)
    (config.ARTIFACTS / "test_logs" / f"{log_name}.log").write_text(
        f"$ cd {workdir} && python -m pytest {target} -q\n"
        f"repo_commit={repo_commit()} code_version={version}\n"
        f"exit={proc.returncode} duration={duration}s\n\n{output}\n",
        encoding="utf-8",
    )
    return {
        "target": target,
        "exit_code": proc.returncode,
        "passed": proc.returncode == 0,
        "duration_s": duration,
        "counts": _counts(output),
        "code_version": version,
        "output": output,
        "log": f"artifacts/test_logs/{log_name}.log",
    }


def code_version(workdir: Path) -> str:
    """Stable hash of the source and test files a test run is based on."""
    digest = hashlib.sha1()
    paths = sorted(
        list((workdir / "src").rglob("*.py")) + list((workdir / "tests").rglob("test_*.py"))
    )
    for path in paths:
        digest.update(path.relative_to(workdir).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def repo_commit() -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(config.ROOT), "rev-parse", "--short", "HEAD"],
            text=True, capture_output=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "unknown"
    return proc.stdout.strip() or "unknown"


def _counts(output: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for word in ("passed", "failed", "error", "errors", "skipped"):
        match = re.search(rf"(\d+) {word}\b", output)
        if match:
            counts[word.rstrip("s")] = int(match.group(1))
    return counts


# --------------------------------------------------------------------------- #
# development loop
# --------------------------------------------------------------------------- #
def develop(
    bundle: Dict[str, Any],
    workdir: Path,
    target: str = TARGET_TESTS,
    max_attempts: int = MAX_ATTEMPTS,
) -> Dict[str, Any]:
    client = get_client()
    client_name = type(client).__name__
    code_paths = [item["path"] for item in bundle["code"]]
    failure: str | None = None
    attempts: List[Dict[str, Any]] = []

    for attempt in range(1, max_attempts + 1):
        messages = build_messages(bundle, source_files(workdir, code_paths), failure)
        prompt_dir = config.ARTIFACTS / "prompts"
        prompt_dir.mkdir(parents=True, exist_ok=True)
        (prompt_dir / f"attempt{attempt}.json").write_text(
            json.dumps(
                {"provider": client_name, "messages": messages},
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )
        try:
            reply = client.complete(messages)
            diff = extract_diff(reply)
            applied = apply_diff(diff, workdir)
        except Exception as exc:  # noqa: BLE001 - model output is untrusted
            attempts.append(
                {"attempt": attempt, "provider": client_name, "applied": [],
                 "error": str(exc), "target": None}
            )
            failure = f"上一步失败：{exc}"
            continue

        result = run_pytest(workdir, target, f"attempt{attempt}_target")
        attempts.append(
            {
                "attempt": attempt,
                "provider": client_name,
                "diff_sha1": hashlib.sha1(diff.encode()).hexdigest(),
                "diff": diff,
                "applied": applied,
                "error": None,
                "target": result,
            }
        )
        if result["passed"]:
            break
        failure = result["output"]

    last = attempts[-1] if attempts else {}
    final_diff = next(
        (a["diff"] for a in reversed(attempts) if a.get("diff")), ""
    )
    return {
        "provider": client_name,
        "attempts": attempts,
        "ok": bool(last.get("target") and last["target"]["passed"]),
        "final_diff": final_diff,
    }
