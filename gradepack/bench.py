"""
gradepack bench — run a model against all tasks and record results.

Usage:
    python -m gradepack bench --model <name> [--attempts N] [--parallel M] [--mock]

Environment variables required for real runs (no defaults to prevent silent failures):
    BASE_URL   Chat completions base URL
    API_KEY    API key (never printed)
    MODEL      Model name (default: meta-models/muse-spark-open-1026)
"""
import concurrent.futures
import datetime
import json
import os
import pathlib
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request

from gradepack import core

_DEFAULT_MODEL = "meta-models/muse-spark-open-1026"

# ---------------------------------------------------------------------------
# Failure reason categorisation
# ---------------------------------------------------------------------------

_REASON_PRIORITY = [
    "model_error", "import_error", "parse_error", "test_failure", "none"
]


def _categorise(result: dict, error_msg: str | None = None) -> str:
    if error_msg:
        return "model_error"
    if result["total"] == 0:
        return "import_error"
    if result["failed"] == 0:
        return "none"
    # Classify by failure pattern
    failures = result.get("failures", [])
    if any("parametrized" in f or "[" in f for f in failures):
        return "test_failure_parametrized"
    return "test_failure"


# ---------------------------------------------------------------------------
# pass@k computation
# ---------------------------------------------------------------------------

def compute_pass_at_k(records: list[dict], k: int = 1) -> dict[str, float]:
    """
    Compute pass@k per task.
    pass@1: fraction of first attempts that passed.
    pass@k: probability that at least one of k attempts passes (unbiased estimator).
    """
    from math import comb

    # Group by task_id
    by_task: dict[str, list[dict]] = {}
    for r in records:
        tid = r.get("task_id", "")
        by_task.setdefault(tid, []).append(r)

    results: dict[str, float] = {}
    for tid, task_records in by_task.items():
        n = len(task_records)
        c = sum(1 for r in task_records if r.get("score", 0) >= 1.0)
        if n == 0:
            results[tid] = 0.0
        elif k == 1:
            results[tid] = round(c / n, 4)
        else:
            # Unbiased estimator: 1 - C(n-c, k) / C(n, k)
            if n < k:
                results[tid] = round(c / n, 4)
            else:
                results[tid] = round(1.0 - comb(n - c, k) / comb(n, k), 4)
    return results


# ---------------------------------------------------------------------------
# Mock model
# ---------------------------------------------------------------------------

def _mock_fixed_files(task_id: str) -> dict[str, str]:
    """Return the solution files for the task (used in mock mode)."""
    sol_dir = core.task_dir(task_id) / "solution"
    return {
        p.name: p.read_text()
        for p in sol_dir.iterdir()
        if p.is_file() and p.suffix == ".py"
    }


def _mock_broken_files(task_id: str) -> dict[str, str]:
    """Return the starter files unchanged (simulates a bad model response)."""
    starter_dir = core.task_dir(task_id) / "starter"
    return {
        p.name: p.read_text()
        for p in starter_dir.iterdir()
        if p.is_file() and p.suffix == ".py"
    }


# ---------------------------------------------------------------------------
# Real model call
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a Python debugging assistant. You will be given a task description and \
one or more buggy Python source files. Reply with ONLY the corrected file(s) in \
the following strict format — no prose, no markdown fences:

=== filename.py ===
<full corrected file content>

Repeat the block for each file that needs changing."""


def _get_env_or_fail(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        print(f"ERROR: environment variable {key!r} is not set.", file=sys.stderr)
        sys.exit(1)
    return val


def _call_model(prompt: str, starter_files: dict[str, str]) -> tuple[dict[str, str], str]:
    """
    Send prompt+starter to the chat completions endpoint and parse response.
    Returns (candidate_files, raw_response_text).
    """
    base_url = _get_env_or_fail("BASE_URL")
    api_key  = _get_env_or_fail("API_KEY")
    model    = os.environ.get("MODEL", _DEFAULT_MODEL)

    file_block = "\n\n".join(
        f"=== {name} ===\n{content}"
        for name, content in starter_files.items()
    )
    user_message = f"{prompt}\n\n{file_block}"

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": user_message},
        ],
        "temperature": 0,
    }).encode()

    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=payload,
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())

    raw_content = data["choices"][0]["message"]["content"]
    return _parse_model_response(raw_content), raw_content


def _parse_model_response(content: str) -> dict[str, str]:
    """Parse the strict === filename.py === format from model output."""
    files: dict[str, str] = {}
    parts = re.split(r"^===\s*(.+?)\s*===$", content, flags=re.MULTILINE)
    it = iter(parts[1:])
    for name, body in zip(it, it):
        files[name.strip()] = body.strip("\n")
    return files


# ---------------------------------------------------------------------------
# Single-task bench run
# ---------------------------------------------------------------------------

def _bench_task(
    task_id: str,
    attempt: int,
    mock: bool,
    mock_pass: bool,
    raw_output_dir: pathlib.Path,
    provider: str,
    model_name: str,
) -> dict:
    meta = core.load_task_json(task_id)
    prompt = meta.get("prompt", "")

    starter_dir = core.task_dir(task_id) / "starter"
    starter_files = {
        p.name: p.read_text()
        for p in starter_dir.iterdir()
        if p.is_file() and p.suffix == ".py"
    }

    t0 = time.monotonic()
    error_msg: str | None = None
    candidate_files: dict[str, str] = {}
    raw_response: str = ""

    if mock:
        candidate_files = _mock_fixed_files(task_id) if mock_pass else _mock_broken_files(task_id)
        raw_response = "[mock]"
    else:
        try:
            candidate_files, raw_response = _call_model(prompt, starter_files)
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

    # Write candidate files to a temp dir and run the grader
    tmp_task = core.make_temp_copy(task_id)
    tmp_parent = tmp_task.parent
    try:
        if candidate_files:
            try:
                core.overlay_dict(candidate_files, tmp_task / "starter")
            except core.CandidateError as exc:
                error_msg = str(exc)
                candidate_files = {}
        result = core.run_pytest(tmp_task / "grader")
    finally:
        shutil.rmtree(tmp_parent, ignore_errors=True)

    total  = result["total"]
    passed = result["passed"]
    record: dict = {
        "task_id":        task_id,
        "attempt":        attempt,
        "provider":       provider,
        "model":          model_name,
        "date":           datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "passed":         passed,
        "failed":         result["failed"],
        "total":          total,
        "score":          round(passed / total, 4) if total else 0.0,
        "failing_tests":  result["failures"],
        "failure_reason": _categorise(result, error_msg),
        "elapsed_s":      elapsed,
        "raw_output_path": raw_path,
    }
    if error_msg:
        record["error"] = error_msg
    return record


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def cmd_bench(
    model: str,
    attempts: int = 1,
    parallel: int = 1,
    mock: bool = False,
    mock_pass: bool = True,
    task_filter: list[str] | None = None,
) -> None:
    results_dir = core._repo_root() / "results"
    results_dir.mkdir(exist_ok=True)

    # Determine provider and model_name
    if mock:
        provider = "mock"
        model_name = model
    else:
        # BASE_URL / MODEL validated inside _call_model / _get_env_or_fail
        provider = os.environ.get("BASE_URL", "").rstrip("/")
        model_name = os.environ.get("MODEL", _DEFAULT_MODEL)

    raw_output_dir = results_dir / "raw" / model
    results_file   = results_dir / f"{model}.json"

    existing: list[dict] = []
    if results_file.exists():
        try:
            existing = json.loads(results_file.read_text())
        except json.JSONDecodeError:
            existing = []

    task_ids = task_filter if task_filter else core.all_task_ids()
    jobs: list[tuple[str, int]] = [
        (tid, attempt)
        for tid in task_ids
        for attempt in range(1, attempts + 1)
    ]

    new_records: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
        futures = {
            pool.submit(
                _bench_task, tid, attempt, mock, mock_pass,
                raw_output_dir, provider, model_name
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
                }
            new_records.append(record)
            print(
                f"  {record['task_id']} attempt={record['attempt']}  "
                f"score={record.get('score', '?')}  "
                f"reason={record.get('failure_reason', '?')}"
            )

    all_records = existing + new_records
    results_file.write_text(json.dumps(all_records, indent=2))

    # Print summary pass@1 and pass@k
    k = attempts
    p1 = compute_pass_at_k(all_records, k=1)
    pk = compute_pass_at_k(all_records, k=k)
    avg_p1 = round(sum(p1.values()) / len(p1), 4) if p1 else 0.0
    avg_pk = round(sum(pk.values()) / len(pk), 4) if pk else 0.0
    print(f"\nResults written to {results_file}")
    print(f"pass@1 (avg over tasks): {avg_p1:.1%}   pass@{k} (avg): {avg_pk:.1%}")
