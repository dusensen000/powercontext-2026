"""End-to-end verification of the SDD context loop.

Run ``python -m sddctx.cli demo`` (or ``python -m sddctx.verify``) and the script:

1. resets the engineering index and ingests specs / code / tests into seekdb;
2. builds a bounded development context for the task;
3. proves the target tests currently fail on a pristine copy of the project;
4. sends the context to MiniMax and applies the returned diff;
5. re-runs the target tests plus the regression suite;
6. saves task progress to PowerContext and reloads it in a **separate process**;
7. simulates a spec change and re-ingests, showing the new requirement reaches
   the context while the old index is untouched.
"""

from __future__ import annotations

import datetime as _dt
import json
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List

from . import agent, config, ingest, state
from .context import build_context, render_context_text
from .db import DocStore

TASK_ID = "taskboard-status-filter"
EVOLVE_TASK = (
    "为 list_tasks 增加按 priority 降序排序的能力，priority 相同时保持 due_date 排序，"
    "并保持状态筛选与分页行为不变。"
)
EVOLVED_SPEC = config.SAMPLE / "specs_phase2" / "taskboard-phase2.md"


class Report:
    def __init__(self) -> None:
        self.started = time.time()
        self.steps: List[Dict[str, Any]] = []
        self.data: Dict[str, Any] = {}

    def step(self, name: str, fn: Callable[[], str], key: str | None = None) -> Any:
        begin = time.time()
        try:
            value = fn()
        except Exception as exc:  # noqa: BLE001 - the report must survive failures
            self.steps.append(
                {"name": name, "ok": False, "detail": f"{type(exc).__name__}: {exc}",
                 "duration_s": round(time.time() - begin, 3)}
            )
            print(f"[fail] {name}: {exc}")
            self.write()
            raise
        detail = value[0] if isinstance(value, tuple) else str(value)
        payload = value[1] if isinstance(value, tuple) else value
        self.steps.append(
            {"name": name, "ok": True, "detail": detail,
             "duration_s": round(time.time() - begin, 3)}
        )
        if key:
            self.data[key] = payload
        print(f"[ok]   {name}: {detail}")
        return payload

    def write(self) -> Path:
        config.ensure_dirs()
        body = {
            "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
            "duration_s": round(time.time() - self.started, 2),
            "task": config.TASK,
            "provider": config.PROVIDER,
            "db_backend": config.DB_BACKEND,
            "state_backend": state.get_state_store().backend,
            "steps": self.steps,
            **self.data,
        }
        path = config.ARTIFACTS / "report.json"
        path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
        return path


def reset_artifacts() -> None:
    config.ensure_dirs()
    for path in (config.ARTIFACTS / "db_queries.log", config.ARTIFACTS / "state_ops.log"):
        if path.exists():
            path.unlink()
    for log in (config.ARTIFACTS / "test_logs").glob("*.log"):
        log.unlink()
    prompts = config.ARTIFACTS / "prompts"
    if prompts.is_dir():
        shutil.rmtree(prompts)
    for name in (
        "context.json", "context.md", "context_evolved.json", "context_resume.md",
        "diff.patch", "service_before.py", "service_after.py", "dev_record.json",
        "report.json",
    ):
        path = config.ARTIFACTS / name
        if path.exists():
            path.unlink()
    if config.STATE_BACKEND == "local":
        local_state = config.DATA / "state.json"
        if local_state.exists():
            local_state.unlink()


def _evolved_store() -> DocStore:
    if config.DB_BACKEND == "sqlite":
        return DocStore(backend="sqlite", path=str(config.DATA / "sddctx_evolve.sqlite3"))
    return DocStore(db_name=f"{config.DB_NAME}_evolve")


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    report = Report()
    try:
        report.step("reset artifacts", lambda: reset_artifacts() or ("cleaned", None))

        store = DocStore()

        def init_index() -> tuple[str, Dict[str, int]]:
            counts = ingest.ingest(store, config.SAMPLE)
            _check(counts["spec"] > 0 and counts["code"] > 0 and counts["test"] > 0,
                   f"empty index: {counts}")
            return f"{counts} (backend={config.DB_BACKEND}, db={config.DB_NAME})", counts

        report.step("ingest specs/code/tests into database", init_index, "ingest")

        def build() -> tuple[str, Dict[str, Any]]:
            bundle = build_context(store, config.TASK)
            _check(any(s.get("req_id") == "REQ-003" for s in bundle["specs"]),
                   "REQ-003 missing from the retrieved specs")
            _check(any(c.get("symbol") == "list_tasks" for c in bundle["code"]),
                   "list_tasks missing from the retrieved code")
            (config.ARTIFACTS / "context.json").write_text(
                json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
            (config.ARTIFACTS / "context.md").write_text(
                render_context_text(bundle), encoding="utf-8")
            detail = (
                f"specs={[s.get('req_id') for s in bundle['specs']]} "
                f"code={[c.get('symbol') for c in bundle['code']]} "
                f"tests={[t.get('symbol') for t in bundle['tests']]}"
            )
            return detail, bundle

        bundle = report.step("build development context", build, "context")

        workdir = agent.prepare_workdir()

        def before() -> tuple[str, Dict[str, Any]]:
            shutil.copyfile(
                workdir / "src/taskboard/service.py",
                config.ARTIFACTS / "service_before.py",
            )
            result = agent.run_pytest(workdir, agent.TARGET_TESTS, "before_target")
            _check(not result["passed"], "target tests already pass on a clean checkout")
            return f"target tests fail as expected: {result['counts']}", result

        before_result = report.step("confirm target tests fail before the change", before, "before")

        def develop() -> tuple[str, Dict[str, Any]]:
            development = agent.develop(bundle, workdir)
            _check(development["ok"], "model did not make the target tests pass")
            if development["final_diff"]:
                (config.ARTIFACTS / "diff.patch").write_text(
                    development["final_diff"], encoding="utf-8")
            shutil.copyfile(
                workdir / "src/taskboard/service.py",
                config.ARTIFACTS / "service_after.py",
            )
            return (
                f"provider={development['provider']} attempts={len(development['attempts'])}",
                development,
            )

        development = report.step(
            f"MiniMax modifies code and target tests pass (provider={config.PROVIDER})",
            develop, "development",
        )

        def after() -> tuple[str, Dict[str, Any]]:
            result = agent.run_pytest(workdir, agent.TARGET_TESTS, "after_target")
            _check(result["passed"], f"target tests still fail: {result['counts']}")
            return f"target tests pass: {result['counts']}", result

        target = report.step("re-run target tests after the change", after, "after")

        def regression() -> tuple[str, Dict[str, Any]]:
            result = agent.run_pytest(workdir, agent.REGRESSION_TESTS, "regression")
            _check(result["passed"], f"regression tests broke: {result['counts']}")
            return f"regression tests pass: {result['counts']}", result

        regression_result = report.step(
            "run regression tests", regression, "regression")

        def record_dev() -> tuple[str, Dict[str, Any]]:
            dev = {
                "task_id": TASK_ID,
                "task": config.TASK,
                "created_at": _dt.datetime.now().isoformat(timespec="seconds"),
                "provider": development["provider"],
                "model": config.MINIMAX_MODEL if config.PROVIDER != "stub" else "stub-replay",
                "protocol": config.MINIMAX_PROTOCOL,
                "endpoint": config.MINIMAX_BASE_URL if config.PROVIDER != "stub" else "",
                "live_minimax": config.PROVIDER != "stub",
                "context_file": "artifacts/context.json",
                "context_sources": bundle["sources"],
                "before": {
                    "target": before_result["target"],
                    "exit_code": before_result["exit_code"],
                    "counts": before_result["counts"],
                    "code_version": before_result["code_version"],
                    "log": before_result["log"],
                    "output": before_result["output"][-1500:],
                },
                "attempts": [
                    {
                        "attempt": item["attempt"],
                        "provider": item.get("provider"),
                        "prompt_file": f"artifacts/prompts/attempt{item['attempt']}.json",
                        "diff_sha1": item.get("diff_sha1"),
                        "applied": item.get("applied"),
                        "error": item.get("error"),
                        "diff": item.get("diff") or "",
                        "target_tests": (
                            {
                                "passed": item["target"]["passed"],
                                "exit_code": item["target"]["exit_code"],
                                "counts": item["target"]["counts"],
                                "code_version": item["target"]["code_version"],
                                "log": item["target"]["log"],
                            }
                            if item.get("target")
                            else None
                        ),
                    }
                    for item in development["attempts"]
                ],
                "after": {
                    "target": target["target"],
                    "exit_code": target["exit_code"],
                    "counts": target["counts"],
                    "code_version": target["code_version"],
                    "log": target["log"],
                },
                "regression": {
                    "target": regression_result["target"],
                    "exit_code": regression_result["exit_code"],
                    "counts": regression_result["counts"],
                    "code_version": regression_result["code_version"],
                    "log": regression_result["log"],
                },
                "final_diff_file": "artifacts/diff.patch",
            }
            path = config.ARTIFACTS / "dev_record.json"
            path.write_text(json.dumps(dev, ensure_ascii=False, indent=2), encoding="utf-8")
            return f"wrote {path.name}: {len(dev['attempts'])} attempt(s), " \
                   f"diff_sha1={dev['attempts'][-1]['diff_sha1']}", dev

        report.step("write MiniMax development record", record_dev, "dev_record")

        changed = sorted({p for a in development["attempts"] for p in (a.get("applied") or [])})
        done = [
            "实现 REQ-003：status 非空时在排序后、分页前筛选",
            "目标测试 tests/test_target_filter.py 通过",
            "回归测试 tests/test_regression.py 通过",
        ]
        todo = [
            "按 REQ-005（docs/sample-task.md 的演进场景）支持 priority 排序",
        ]
        record = state.build_record(
            task_id=TASK_ID,
            task=config.TASK,
            status="done",
            development=development,
            target=target,
            regression=regression_result,
            changed_files=changed,
            context=bundle,
            done=done,
            todo=todo,
            extra={"workdir": str(workdir.relative_to(config.ROOT))},
        )

        def save_state() -> tuple[str, Dict[str, Any]]:
            saved = state.get_state_store().save(record)
            return (
                f"backend={saved['backend']} scope={saved.get('scope_id', '-')} "
                f"artifacts={saved.get('artifacts', saved.get('path'))}",
                saved,
            )

        report.step("save task progress", save_state, "state")

        def reload_state() -> tuple[str, Dict[str, Any]]:
            proc = subprocess.run(
                [sys.executable, "-m", "sddctx.cli", "state-load"],
                cwd=config.ROOT, text=True, capture_output=True, timeout=60,
            )
            _check(proc.returncode == 0, f"state-load failed: {proc.stderr.strip()[:400]}")
            loaded = json.loads(proc.stdout)
            _check(loaded.get("task_id") == TASK_ID,
                   f"reloaded task_id mismatch: {loaded.get('task_id')}")
            _check(loaded.get("status") == "done", "reloaded status is not done")
            return (
                f"separate process resumed {loaded['task_id']} "
                f"({len(loaded.get('changed_files', []))} file(s), status={loaded['status']})",
                loaded,
            )

        report.step("resume progress in a new process", reload_state, "reload")

        def resume_context() -> tuple[str, Dict[str, Any]]:
            loaded = state.get_state_store().load()
            _check(loaded is not None, "no persisted state to resume from")
            resumed = build_context(store, EVOLVE_TASK, history=loaded)
            text = render_context_text(resumed)
            _check("上一轮任务进展" in text, "history section missing from the context")
            _check(TASK_ID in text, "persisted task id missing from the context")
            (config.ARTIFACTS / "context_resume.md").write_text(text, encoding="utf-8")
            return (
                f"next-task context carries {loaded['task_id']} "
                f"({len(loaded.get('todo', []))} todo item(s)) and {len(resumed['specs'])} specs",
                resumed,
            )

        report.step("use resumed state in the next task context", resume_context, "resume")

        def evolve() -> tuple[str, Dict[str, Any]]:
            target_dir = config.WORK / "evolved"
            if target_dir.exists():
                shutil.rmtree(target_dir)
            shutil.copytree(
                config.SAMPLE, target_dir,
                ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc"),
            )
            spec_path = target_dir / "specs" / "taskboard-phase2.md"
            shutil.copyfile(EVOLVED_SPEC, spec_path)

            evolved = _evolved_store()
            try:
                counts = ingest.ingest(evolved, target_dir)
                phase2 = build_context(evolved, EVOLVE_TASK)
                reqs = [s.get("req_id") for s in phase2["specs"]]
                _check("REQ-005" in reqs, f"REQ-005 not retrieved: {reqs}")
                _check(reqs[0] == "REQ-005", f"REQ-005 not ranked first: {reqs}")
                phase1 = build_context(store, config.TASK)
                _check(all(s.get("req_id") != "REQ-005" for s in phase1["specs"]),
                       "phase-1 index was polluted by the phase-2 spec")
                (config.ARTIFACTS / "context_evolved.json").write_text(
                    json.dumps(phase2, ensure_ascii=False, indent=2), encoding="utf-8")
                return (
                    f"re-ingested {counts['total']} chunks in the evolved database; "
                    f"REQ-005 ranked first; phase-1 index unchanged",
                    {"counts": counts, "specs": reqs,
                     "sources": phase2["sources"]},
                )
            finally:
                evolved.close()

        report.step("spec change re-ingest keeps context valid", evolve, "evolve")

        store.close()
        path = report.write()
        failures = [s for s in report.steps if not s["ok"]]
        print(f"\nreport: {path}")
        print(f"steps: {len(report.steps)} total, {len(failures)} failed")
        return 0 if not failures else 1
    except Exception:
        traceback.print_exc()
        report.write()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
