"""``e2e`` CLI — run a structured case set against a live SUT and emit ``verdict.json``.

Makes the engine a usable tool: load ``case.yaml`` → build a runner from config/flags → fire
each case through it → write the cross-harness ``verdict.json`` + a stdout summary, and exit
non-zero on a non-pass run (a CI gate). The judgment is *data* (``judge.e2e.assert``); this only
wires that data to a SUT. ``python -m e2e_harness run …`` or the ``e2e`` console script.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from spec_case.model import load_caseset, validate
from harness_common.run import run_dir_for
from harness_common.verdict import RunVerdict, write_verdict
from e2e_harness.core.env import Env, load_env
from e2e_harness.engine import run_cases
from e2e_harness.runner.base import BaseRunner
from e2e_harness.runner.json_runner import JSONRunner
from e2e_harness.runner.sse_runner import SSERunner


def make_run_id() -> str:
    """Sortable run id ``YYYYMMDD-HHMMSS`` (local time) — one invocation = one run dir."""
    return time.strftime("%Y%m%d-%H%M%S")


def run_files(
    case_paths: list[str],
    runner: BaseRunner,
    *,
    runs_dir: str,
    run_id: str,
    scope: str | None = None,
) -> tuple[RunVerdict, Path]:
    """Load case.yaml file(s) → run every case through ``runner`` → write ``verdict.json``.

    The runner is injected so this core is unit-testable with a mock-transport runner; the CLI
    builds the real one from Env. ``scope`` defaults to the first case set's name. Returns the
    run verdict and the path written.
    """
    cases = []
    for p in case_paths:
        cs = load_caseset(p)
        validate(cs)  # fail fast on a malformed case file
        cases.extend(cs.cases)
        scope = scope or cs.caseset
    if not cases:
        raise SystemExit("e2e: no cases found in the given file(s)")
    rv = run_cases(cases, runner, scope=scope or "e2e", run_id=run_id)
    path = write_verdict(run_dir_for(runs_dir, rv.scope, rv.run_id), rv)
    return rv, path


def _build_env(config: str | None, base_url: str | None) -> Env:
    env = load_env(config) if config else Env()
    if base_url:
        env.service.base_url = base_url.rstrip("/")
    if not env.service.base_url:
        raise SystemExit(
            "e2e: no SUT base_url — pass --base-url or set service.base_url in --config"
        )
    return env


def _runner(env: Env, protocol: str) -> BaseRunner:
    if protocol == "json":
        return JSONRunner(env)
    if protocol == "sse":
        return SSERunner(env)
    raise SystemExit(f"e2e: unknown protocol {protocol!r}")


def _summary(rv: RunVerdict, path: Path) -> str:
    s = rv.summary
    lines = [
        f"e2e: {rv.scope}  {rv.status.upper()}  ({s['pass']}/{s['total']} passed)  → {path}"
    ]
    if rv.status != "pass":  # surface the offending cases (the why), not just the count
        lines += [
            f"  {c.status} {c.case_id}: {c.reason or ''}"
            for c in rv.cases
            if c.status != "pass"
        ]
    return "\n".join(lines)


def cmd_run(args: argparse.Namespace) -> int:
    runner = _runner(_build_env(args.config, args.base_url), args.protocol)
    rv, path = run_files(
        args.cases,
        runner,
        runs_dir=args.runs_dir,
        run_id=args.run_id or make_run_id(),
        scope=args.scope,
    )
    print(_summary(rv, path))
    return 0 if rv.status == "pass" else 1  # CI gate: non-pass → non-zero


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="e2e", description="Run structured e2e cases against a SUT."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser(
        "run", help="run case.yaml file(s) against a SUT → verdict.json"
    )
    run.add_argument("cases", nargs="+", help="case.yaml file(s)")
    run.add_argument("--base-url", help="SUT base url (overrides --config)")
    run.add_argument("--config", help="config.yaml for Env (base_url / auth / timeout)")
    run.add_argument(
        "--protocol",
        default="json",
        choices=["json", "sse"],
        help="runner protocol: json | sse (default: json)",
    )
    run.add_argument(
        "--runs-dir", default="./runs", help="parent runs dir (default: ./runs)"
    )
    run.add_argument("--scope", help="run scope (default: the case set name)")
    run.add_argument("--run-id", help="run id (default: timestamp)")
    run.set_defaults(func=cmd_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
