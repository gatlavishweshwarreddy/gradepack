"""
gradepack bench — run a model against all tasks and record results.

Usage (--help for full options):
    python -m gradepack bench --help
    python -m gradepack bench --model mock --mock
    python -m gradepack bench --model gpt-4o --attempts 3 --parallel 4

Environment variables required for real runs:
    BASE_URL   Chat completions base URL
    API_KEY    API key (never printed)
    MODEL      Model name (default: meta-models/muse-spark-open-1026)
"""
import argparse
import concurrent.futures
import datetime
import json
import os
import pathlib
import shutil
import sys
import time

from gradepack import api as _api
from gradepack import core

_DEFAULT_MODEL = _api._DEFAULT_MODEL

# ---------------------------------------------------------------------------
# Failure reason taxonomy
# ---------------------------------------------------------------------------
# Values: none | wrong_answer | test_failure_parametrized | invalid_output |
#         no_answer | timeout | runner_error | api_error

def _categorise(
    result: dict,
    error_msg: str | None = None,
    finish_reason: str = "",
    had_candidate: bool = True,
) -> str:
    if error_msg:
        if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
            return "timeout"
        if any(k in error_msg.lower() for k in ("http", "api", "429", "5")):
            return "api_error"
        return "runner_error"
    if not had_candidate:
        if finish_reason in ("length", "max_tokens"):
            return "no_answer"
        return "invalid_output"
    if result["total"] == 0:
        return "invalid_output"
    if result["failed"] == 0:
        return "none"
    failures = result.get("failures", [])
    if any("[" in f for f in failures):
        return "test_failure_parametrized"
    return "wrong_answer"


# ---------------------------------------------------------------------------
# pass@k computation
# ---------------------------------------------------------------------------

def compute_pass_at_k(records: list[dict], k: int = 1) -> dict[str, float]:
    from math import comb
    by_task: dict[str, list[dict]] = {}
    for r in records:
        by_task.setdefault(r.get("task_id", ""), []).append(r)
    results: dict[str, float] = {}
    for tid, recs in by_task.items():
        n = len(recs)
        c = sum(1 for r in recs if r.get("score", 0) >= 1.0)
        if n == 0:
            results[tid] = 0.0
        elif k == 1:
            results[tid] = round(c / n, 4)
        else:
            results[tid] = round(1.0 - comb(n - c, k) / comb(n, k), 4) if n >= k else round(c / n, 4)
    return results


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

def _mock_fixed_files(task_id: str) -> dict[str, str]:
    sol_dir = core.task_dir(task_id) / "solution"
    return {p.name: p.read_text() for p in sol_dir.iterdir() if p.is_file() and p.suffix == ".py"}


def _mock_broken_files(task_id: str) -> dict[str, str]:
    starter_dir = core.task_dir(task_id) / "starter"
    return {p.name: p.read_text() for p in starter_dir.iterdir() if p.is_file() and p.suffix == ".py"}


# ---------------------------------------------------------------------------
# Single-task bench run
# ---------------------------------------------------------------------------

def _bench_task(
    task_id: str,
    attempt: int,
    *,
    mock: bool,
    mock_pass: bool,
    raw_output_dir: pathlib.Path,
    provider: str,
    model_name: str,
    max_tokens: int,
    temperature: float,
) -> dict:
    meta = core.load_task_json(task_id)
    prompt = meta.get("prompt", "")

    starter_dir = core.task_dir(task_id) / "starter"
    starter_files = {
        p.name: p.read_text()
        for p in starter_dir.iterdir()
        if p.is_file() and p.suffix == ".py"
    }
    allowed = set(starter_files)

    t0 = time.monotonic()
    error_msg: str | None = None
    candidate_files: dict[str, str] = {}
    raw_response: str = ""
    finish_reason: str = ""
    token_usage: dict | None = None

    if mock:
        candidate_files = _mock_fixed_files(task_id) if mock_pass else _mock_broken_files(task_id)
        raw_response = "[mock]"
        finish_reason = "stop"
    else:
        try:
            user_msg = _api.build_coding_prompt(prompt, starter_files)
            resp_data = _api.chat(
                _api._SYSTEM_CODING,
                user_msg,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=180,
            )
            raw_response  = _api.extract_content(resp_data)
            finish_reason = _api.extract_finish_reason(resp_data)
            token_usage   = _api.extract_usage(resp_data)
            if raw_response:
                candidate_files = _api.parse_coding_response(raw_response, allowed)
        except Exception as exc:
            error_msg = str(exc)

    elapsed = round(time.monotonic() - t0, 2)

    # Save raw model output
    raw_path: str | None = None
    if raw_response:
        raw_output_dir.mkdir(parents=True, exist_ok=True)
        safe_id = task_id.replace("/", "_")
        raw_file = raw_output_dir / f"{safe_id}_attempt{attempt}.txt"
        raw_file.write_text(raw_response)
        raw_path = str(raw_file)

    # Run grader
    had_candidate = bool(candidate_files)
    tmp_task = core.make_temp_copy(task_id)
    tmp_parent = tmp_task.parent
    try:
        if had_candidate:
            try:
                core.overlay_dict(candidate_files, tmp_task / "starter")
            except core.CandidateError as exc:
                error_msg = str(exc)
                had_candidate = False
        result = core.run_pytest(tmp_task / "grader")
    finally:
        shutil.rmtree(tmp_parent, ignore_errors=True)

    # A failed/invalid answer always scores 0.0
    if not had_candidate or error_msg:
        score = 0.0
        passed = 0
        failed = result.get("total", 0)
    else:
        total  = result["total"]
        passed = result["passed"]
        failed = result["failed"]
        score  = round(passed / total, 4) if total else 0.0

    reason = _categorise(result, error_msg, finish_reason, had_candidate)

    record: dict = {
        "task_id":         task_id,
        "attempt":         attempt,
        "provider":        provider,
        "model":           model_name,
        "date":            datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "passed":          passed,
        "failed":          failed,
        "total":           result.get("total", 0),
        "score":           score,
        "failing_tests":   result.get("failures", []),
        "failure_reason":  reason,
        "finish_reason":   finish_reason,
        "elapsed_s":       elapsed,
        "raw_output_path": raw_path,
    }
    if token_usage:
        record["token_usage"] = token_usage
    if error_msg:
        record["error"] = error_msg
    return record


# ---------------------------------------------------------------------------
# Publish helpers
# ---------------------------------------------------------------------------

def _publish(results_file: pathlib.Path, include_mock: bool) -> None:
    """Copy results_file to docs/results/ and update docs/results/index.json."""
    name = results_file.name  # e.g. "mock.json" or "gpt-4o.json"
    stem = results_file.stem  # model name
    if stem.startswith("mock") and not include_mock:
        print(f"  Skipping {name} (mock file; pass --include-mock to publish)")
        return

    docs_results = core._repo_root() / "docs" / "results"
    docs_results.mkdir(parents=True, exist_ok=True)

    dest = docs_results / name
    shutil.copy2(results_file, dest)
    print(f"  Published {dest}")

    # Update index.json
    idx_path = docs_results / "index.json"
    index: list[str] = []
    if idx_path.exists():
        try:
            index = json.loads(idx_path.read_text())
        except json.JSONDecodeError:
            index = []
    if name not in index:
        index.append(name)
    idx_path.write_text(json.dumps(sorted(index), indent=2))
    print(f"  Updated {idx_path}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gradepack bench",
        description="Benchmark a model against all gradepack tasks.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--model",          required=True,   help="Label for the results file (results/<model>.json)")
    p.add_argument("--attempts",       type=int, default=1, help="Attempts per task (default: 1)")
    p.add_argument("--parallel",       type=int, default=1, help="Thread concurrency (default: 1)")
    p.add_argument("--mock",           action="store_true", help="Use solution files (no API call)")
    p.add_argument("--mock-fail",      action="store_true", help="Use starter files unchanged (simulates broken model)")
    p.add_argument("--task",           action="append", dest="tasks", metavar="TASK_ID",
                   help="Restrict to this task (repeatable)")
    p.add_argument("--max-tokens",     type=int, default=8192, help="max_tokens for API requests (default: 8192)")
    p.add_argument("--temperature",    type=float, default=0.7, help="Temperature (default: 0.7)")
    p.add_argument("--provider-label", default="",  help="Human-readable provider label stored in records")
    p.add_argument("--publish",        action="store_true", help="Copy results to docs/results/ after run")
    p.add_argument("--include-mock",   action="store_true", help="Allow publishing mock result files")
    return p


def cmd_bench_argv(argv: list[str]) -> None:
    """Parse argv and run bench. Supports --help."""
    parser = build_parser()
    args = parser.parse_args(argv)
    cmd_bench(
        model=args.model,
        attempts=args.attempts,
        parallel=args.parallel,
        mock=args.mock,
        mock_pass=not args.mock_fail,
        task_filter=args.tasks,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        provider_label=args.provider_label,
        publish=args.publish,
        include_mock=args.include_mock,
    )


def cmd_bench(
    model: str,
    attempts: int = 1,
    parallel: int = 1,
    mock: bool = False,
    mock_pass: bool = True,
    task_filter: list[str] | None = None,
    max_tokens: int = 8192,
    temperature: float = 0.7,
    provider_label: str = "",
    publish: bool = False,
    include_mock: bool = False,
) -> None:
    results_dir = core._repo_root() / "results"
    results_dir.mkdir(exist_ok=True)

    if mock:
        provider = provider_label or "mock"
        model_name = model
    else:
        provider = provider_label or os.environ.get("BASE_URL", "").rstrip("/")
        model_name = _api.get_model()

    raw_output_dir = results_dir / "raw" / model
    results_file   = results_dir / f"{model}.json"

    existing: list[dict] = []
    if results_file.exists():
        try:
            existing = json.loads(results_file.read_text())
        except json.JSONDecodeError:
            existing = []

    task_ids = task_filter if task_filter else core.all_task_ids()
    jobs = [(tid, attempt) for tid in task_ids for attempt in range(1, attempts + 1)]

    new_records: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
        futures = {
            pool.submit(
                _bench_task, tid, attempt,
                mock=mock, mock_pass=mock_pass,
                raw_output_dir=raw_output_dir,
                provider=provider, model_name=model_name,
                max_tokens=max_tokens, temperature=temperature,
            ): (tid, attempt)
            for tid, attempt in jobs
        }
        for future in concurrent.futures.as_completed(futures):
            tid, attempt = futures[future]
            try:
                record = future.result()
            except Exception as exc:
                record = {
                    "task_id": tid, "attempt": attempt,
                    "error": str(exc), "failure_reason": "runner_error",
                    "provider": provider, "model": model_name,
                    "date": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "score": 0.0, "passed": 0, "failed": 0, "total": 0,
                }
            new_records.append(record)
            print(
                f"  {record['task_id']} attempt={record['attempt']}  "
                f"score={record.get('score', '?')}  "
                f"reason={record.get('failure_reason', '?')}"
            )

    all_records = existing + new_records
    results_file.write_text(json.dumps(all_records, indent=2))

    k = attempts
    p1 = compute_pass_at_k(new_records, k=1)
    pk = compute_pass_at_k(new_records, k=k)
    avg_p1 = round(sum(p1.values()) / len(p1), 4) if p1 else 0.0
    avg_pk = round(sum(pk.values()) / len(pk), 4) if pk else 0.0
    print(f"\nResults written to {results_file}")
    print(f"pass@1 (avg): {avg_p1:.1%}   pass@{k} (avg): {avg_pk:.1%}")

    if publish:
        print("\nPublishing…")
        _publish(results_file, include_mock=include_mock)
