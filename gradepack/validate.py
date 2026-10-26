"""
gradepack validate — check every task for required fields and structural integrity.

Usage:
    python -m gradepack validate
"""
import json
import pathlib
import sys

from gradepack import core

REQUIRED_FIELDS = ["id", "title", "language", "difficulty", "prompt", "grader",
                   "version", "tags", "estimated_minutes", "license"]
MIN_PROMPT_LEN = 200


def validate_task(task_id: str) -> list[str]:
    """Return a list of error strings for the given task. Empty list = OK."""
    errors: list[str] = []
    task_root = core.task_dir(task_id)

    # task.json exists and is valid JSON
    json_path = task_root / "task.json"
    if not json_path.exists():
        return [f"[{task_id}] task.json missing"]
    try:
        with json_path.open() as f:
            meta = json.load(f)
    except json.JSONDecodeError as exc:
        return [f"[{task_id}] task.json is not valid JSON: {exc}"]

    # id matches directory name
    if meta.get("id") != task_id:
        errors.append(
            f"[{task_id}] id field {meta.get('id')!r} does not match directory name"
        )

    # required fields present and non-empty
    for field in REQUIRED_FIELDS:
        val = meta.get(field)
        if val is None:
            errors.append(f"[{task_id}] missing required field: {field!r}")
        elif isinstance(val, str) and not val.strip():
            errors.append(f"[{task_id}] field {field!r} is empty")

    # prompt length
    prompt = meta.get("prompt", "")
    if isinstance(prompt, str) and len(prompt) < MIN_PROMPT_LEN:
        errors.append(
            f"[{task_id}] prompt is too short ({len(prompt)} chars, min {MIN_PROMPT_LEN})"
        )

    # starter/ directory and files
    starter_dir = task_root / "starter"
    if not starter_dir.is_dir():
        errors.append(f"[{task_id}] starter/ directory missing")
    elif not any(starter_dir.iterdir()):
        errors.append(f"[{task_id}] starter/ directory is empty")

    # grader/ directory with at least one test file
    grader_dir = task_root / "grader"
    if not grader_dir.is_dir():
        errors.append(f"[{task_id}] grader/ directory missing")
    else:
        test_files = list(grader_dir.glob("test_*.py"))
        if not test_files:
            errors.append(f"[{task_id}] grader/ has no test_*.py files")

    # solution/ directory
    solution_dir = task_root / "solution"
    if not solution_dir.is_dir():
        errors.append(f"[{task_id}] solution/ directory missing")
    elif not any(solution_dir.iterdir()):
        errors.append(f"[{task_id}] solution/ directory is empty")

    return errors


def cmd_validate() -> None:
    task_ids = core.all_task_ids()
    if not task_ids:
        print("No tasks found.")
        sys.exit(1)

    all_errors: list[str] = []
    for tid in task_ids:
        errs = validate_task(tid)
        all_errors.extend(errs)

    if all_errors:
        print(f"VALIDATION FAILED — {len(all_errors)} error(s):")
        for e in all_errors:
            print(f"  {e}")
        sys.exit(1)
    else:
        print(f"OK — all {len(task_ids)} tasks validated.")
