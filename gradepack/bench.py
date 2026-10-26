"""
gradepack bench — run a model against all tasks and record results.

Usage:
    python -m gradepack bench --model <name> [--attempts N] [--parallel M] [--mock]
"""
import concurrent.futures
import json
import os
import pathlib
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request

from gradepack import core


# ---------------------------------------------------------------------------
# Failure reason categorisation
# ---------------------------------------------------------------------------

def _categorise(result: dict) -> str:
    if result["total"] == 0:
        return "import_error"
    if result["failed"] == 0:
        return "none"
    return "test_failure"


# ---------------------------------------------------------------------------
# Mock model
# ---------------------------------------------------------------------------

def _mock_fixed_files(task_id: str) -> dict[str, str]:
    """Return the solution files for the task (used in mock mode)."""
    sol_dir = core.task_dir(task_id) / "solution"
    files = {}
    for p in sol_dir.iterdir():
        if p.is_file() and p.suffix == ".py":
            files[p.name] = p.read_text()
    return files


def _mock_broken_files(task_id: str) -> dict[str, str]:
    """Return the starter files unchanged (simulates a bad model response)."""
    starter_dir = core.task_dir(task_id) / "starter"
    files = {}
    for p in starter_dir.iterdir():
        if p.is_file() and p.suffix == ".py":
            files[p.name] = p.read_text()
    return files


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


def _call_model(prompt: str, starter_files: dict[str, str]) -> dict[str, str]:
    """Send prompt+starter to the chat completions endpoint and parse response."""
    base_url = os.environ.get("BASE_URL", "https://api.openai.com/v1")
    api_key  = os.environ.get("API_KEY", "")
    model    = os.environ.get("MODEL", "gpt-4o-mini")

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
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())

    content = data["choices"][0]["message"]["content"]
    return _parse_model_response(content)


def _parse_model_response(content: str) -> dict[str, str]:
    """Parse the strict === filename.py === format from model output."""
    import re
    files: dict[str, str] = {}
    # Split on headers like '=== something.py ==='
    parts = re.split(r"^===\s*(.+?)\s*===$", content, flags=re.MULTILINE)
    # parts: [before_first, name1, body1, name2, body2, ...]
    it = iter(parts[1:])
    for name, body in zip(it, it):
        files[name.strip()] = body.strip("\n")
    return files


# ---------------------------------------------------------------------------
# Single-task bench run
# ---------------------------------------------------------------------------

def _bench_task(task_id: str, attempt: int, mock: bool, mock_pass: bool) -> dict:
    meta = core.load_task_json(task_id)
    prompt = meta.get("prompt", "")

    starter_dir = core.task_dir(task_id) / "starter"
    starter_files = {
        p.name: p.read_text()
        for p in starter_dir.iterdir()
        if p.is_file() and p.suffix == ".py"
    }

    t0 = time.monotonic()
    error_msg = None
    candidate_files: dict[str, str] = {}

    if mock:
        candidate_files = _mock_fixed_files(task_id) if mock_pass else _mock_broken_files(task_id)
    else:
        try:
            candidate_files = _call_model(prompt, starter_files)
        except Exception as exc:
            error_msg = str(exc)

    elapsed = round(time.monotonic() - t0, 2)

    # Write candidate files to a temp dir and run the grader
    tmp_task = core.make_temp_copy(task_id)
    tmp_parent = tmp_task.parent
    try:
        for fname, content in candidate_files.items():
            (tmp_task / "starter" / fname).write_text(content)
        result = core.run_pytest(tmp_task / "grader")
    finally:
        shutil.rmtree(tmp_parent, ignore_errors=True)

    record = {
        "task_id":       task_id,
        "attempt":       attempt,
        "passed":        result["passed"],
        "failed":        result["failed"],
        "total":         result["total"],
        "score":         round(result["passed"] / result["total"], 4) if result["total"] else 0.0,
        "failing_tests": result["failures"],
        "failure_reason": _categorise(result),
        "elapsed_s":     elapsed,
    }
    if error_msg:
        record["error"] = error_msg
        record["failure_reason"] = "model_error"
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

    results_file = results_dir / f"{model}.json"
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
            pool.submit(_bench_task, tid, attempt, mock, mock_pass): (tid, attempt)
            for tid, attempt in jobs
        }
        for future in concurrent.futures.as_completed(futures):
            tid, attempt = futures[future]
            try:
                record = future.result()
            except Exception as exc:
                record = {
                    "task_id": tid,
                    "attempt": attempt,
                    "error": str(exc),
                    "failure_reason": "runner_error",
                }
            new_records.append(record)
            print(
                f"  {record['task_id']} attempt={record['attempt']}  "
                f"score={record.get('score', '?')}  "
                f"reason={record.get('failure_reason', '?')}"
            )

    all_records = existing + new_records
    results_file.write_text(json.dumps(all_records, indent=2))
    print(f"\nResults written to {results_file}")
