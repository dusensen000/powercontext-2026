"""Command line entry points for the SDD context module."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import agent, config, ingest, state
from .context import build_context, render_context_text
from .db import DocStore


def cmd_init_db(args: argparse.Namespace) -> int:
    store = DocStore()
    try:
        print(f"backend={store.backend} path={store.path} db={store.db_name}")
        print(f"rows={store.count()}")
    finally:
        store.close()
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    sample = Path(args.sample) if args.sample else config.SAMPLE
    store = DocStore()
    try:
        counts = ingest.ingest(store, sample)
        print(json.dumps({"sample": str(sample), **counts}, ensure_ascii=False))
    finally:
        store.close()
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    store = DocStore()
    try:
        history = state.get_state_store().load() if args.resume else None
        bundle = build_context(store, args.task, history=history)
    finally:
        store.close()
    if args.write:
        config.ensure_dirs()
        (config.ARTIFACTS / "context.json").write_text(
            json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
        (config.ARTIFACTS / "context.md").write_text(
            render_context_text(bundle), encoding="utf-8")
    if args.format == "text":
        print(render_context_text(bundle))
    else:
        print(json.dumps(
            {
                "task": bundle["task"],
                "specs": [s.get("req_id") or s["path"] for s in bundle["specs"]],
                "code": [f"{c['path']}:{c.get('symbol')}" for c in bundle["code"]],
                "tests": [f"{t['path']}::{t.get('symbol')}" for t in bundle["tests"]],
                "sources": bundle["sources"],
            },
            ensure_ascii=False, indent=2,
        ))
    return 0


def cmd_run_agent(args: argparse.Namespace) -> int:
    store = DocStore()
    try:
        bundle = build_context(store, args.task)
    finally:
        store.close()
    workdir = agent.prepare_workdir()
    result = agent.develop(bundle, workdir)
    config.ensure_dirs()
    if result["final_diff"]:
        (config.ARTIFACTS / "diff.patch").write_text(result["final_diff"], encoding="utf-8")
    summary = {
        "provider": result["provider"],
        "ok": result["ok"],
        "attempts": [
            {
                "attempt": a["attempt"],
                "applied": a["applied"],
                "error": a["error"],
                "target_passed": bool(a.get("target") and a["target"]["passed"]),
            }
            for a in result["attempts"]
        ],
        "workdir": str(workdir),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


def cmd_test(args: argparse.Namespace) -> int:
    workdir = config.WORK / "sample"
    if not workdir.is_dir():
        print(f"no workdir at {workdir}; run `run-agent` or `demo` first", file=sys.stderr)
        return 2
    targets = {
        "target": agent.TARGET_TESTS,
        "regression": agent.REGRESSION_TESTS,
    }
    selected = targets.values() if args.suite == "all" else [targets[args.suite]]
    ok = True
    for index, target in enumerate(selected):
        result = agent.run_pytest(workdir, target, f"manual_{args.suite}_{index}")
        print(f"{target}: exit={result['exit_code']} counts={result['counts']}")
        if result["output"]:
            print(result["output"])
        ok = ok and result["passed"]
    return 0 if ok else 1


def cmd_state_load(args: argparse.Namespace) -> int:
    record = state.get_state_store().load()
    if record is None:
        print("{}")
        return 1
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


def cmd_state_save_demo(args: argparse.Namespace) -> int:
    record = {
        "task_id": args.task_id,
        "task": args.task,
        "status": args.status,
        "changed_files": [],
        "note": "written by `state-save-demo` to check connectivity",
    }
    print(json.dumps(state.get_state_store().save(record), ensure_ascii=False, indent=2))
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    from . import verify

    return verify.main()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sddctx", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init-db", help="open the database and print row count")
    p.set_defaults(func=cmd_init_db)

    p = sub.add_parser("ingest", help="re-index specs/code/tests")
    p.add_argument("--sample", help="project directory to index (default: sample/)")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("context", help="build a development context for a task")
    p.add_argument("--task", default=config.TASK)
    p.add_argument("--format", choices=("summary", "text"), default="summary")
    p.add_argument("--write", action="store_true", help="also write artifacts/context.{json,md}")
    p.add_argument("--resume", action="store_true", help="include persisted task progress")
    p.set_defaults(func=cmd_context)

    p = sub.add_parser("run-agent", help="let MiniMax modify the sample project")
    p.add_argument("--task", default=config.TASK)
    p.set_defaults(func=cmd_run_agent)

    p = sub.add_parser("test", help="run tests in the working copy")
    p.add_argument("suite", nargs="?", choices=("target", "regression", "all"), default="all")
    p.set_defaults(func=cmd_test)

    p = sub.add_parser("state-load", help="load persisted task progress (JSON on stdout)")
    p.set_defaults(func=cmd_state_load)

    p = sub.add_parser("state-save-demo", help="write a probe record to the state backend")
    p.add_argument("--task-id", default="state-probe")
    p.add_argument("--task", default="state backend connectivity probe")
    p.add_argument("--status", default="probe")
    p.set_defaults(func=cmd_state_save_demo)

    p = sub.add_parser("demo", help="run the full end-to-end verification")
    p.set_defaults(func=cmd_demo)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
