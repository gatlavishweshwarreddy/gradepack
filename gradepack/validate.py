"""
gradepack validate — check every task for required fields and structural integrity.

Usage:
    python -m gradepack validate
"""
import ast
import json
import pathlib
import sys

from gradepack import core

REQUIRED_FIELDS = ["id", "title", "language", "difficulty", "prompt", "grader",
                   "version", "tags", "estimated_minutes", "license"]
MIN_PROMPT_LEN = 200

# Difficulty consistency thresholds (test count, starter line count)
_DIFFICULTY_TEST_THRESHOLDS = {
    "easy":   (1, 8),    # (min_tests, max_tests)
    "medium": (5, 20),
    "hard":   (8, 9999),
}

_DIFFICULTY_STARTER_LINES = {
    "easy":   (1, 30),
    "medium": (15, 80),
    "hard":   (25, 9999),
}


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


def _count_test_functions(grader_dir: pathlib.Path) -> int:
    """Count test_ functions across all grader files."""
    count = 0
    for f in grader_dir.glob("test_*.py"):
        try:
            tree = ast.parse(f.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                    count += 1
        except SyntaxError:
            pass
    return count


def _count_starter_lines(starter_dir: pathlib.Path) -> int:
    """Count non-blank non-comment lines across all starter files."""
    total = 0
    for f in starter_dir.iterdir():
        if f.is_file() and f.suffix == ".py":
            for line in f.read_text().splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    total += 1
    return total


def difficulty_warnings(task_id: str) -> list[str]:
    """
    Return warning strings if the difficulty label seems inconsistent
    with the number of test functions or lines of starter code.
    Returns empty list if consistent or if no thresholds apply.
    """
    warnings: list[str] = []
    task_root = core.task_dir(task_id)
    json_path = task_root / "task.json"
    if not json_path.exists():
        return warnings
    try:
        with json_path.open() as f:
            meta = json.load(f)
    except Exception:
        return warnings

    difficulty = meta.get("difficulty", "")
    if difficulty not in _DIFFICULTY_TEST_THRESHOLDS:
        return warnings

    grader_dir = task_root / "grader"
    starter_dir = task_root / "starter"

    if grader_dir.is_dir():
        test_count = _count_test_functions(grader_dir)
        min_t, max_t = _DIFFICULTY_TEST_THRESHOLDS[difficulty]
        if not (min_t <= test_count <= max_t):
            warnings.append(
                f"[{task_id}] difficulty={difficulty!r} but has {test_count} test function(s) "
                f"(expected {min_t}–{max_t})"
            )

    if starter_dir.is_dir():
        starter_lines = _count_starter_lines(starter_dir)
        min_l, max_l = _DIFFICULTY_STARTER_LINES[difficulty]
        if not (min_l <= starter_lines <= max_l):
            warnings.append(
                f"[{task_id}] difficulty={difficulty!r} but starter has {starter_lines} code line(s) "
                f"(expected {min_l}–{max_l})"
            )

    return warnings


def cmd_validate() -> None:
    task_ids = core.all_task_ids()
    if not task_ids:
        print("No tasks found.")
        sys.exit(1)

    all_errors: list[str] = []
    for tid in task_ids:
        errs = validate_task(tid)
        all_errors.extend(errs)

    all_warnings: list[str] = []
    for tid in task_ids:
        all_warnings.extend(difficulty_warnings(tid))

    if all_errors:
        print(f"VALIDATION FAILED — {len(all_errors)} error(s):")
        for e in all_errors:
            print(f"  {e}")
        if all_warnings:
            print(f"\nWarnings ({len(all_warnings)}):")
            for w in all_warnings:
                print(f"  WARNING: {w}")
        sys.exit(1)
    else:
        if all_warnings:
            print(f"OK — all {len(task_ids)} tasks validated (with {len(all_warnings)} warning(s)):")
            for w in all_warnings:
                print(f"  WARNING: {w}")
        else:
            print(f"OK — all {len(task_ids)} tasks validated.")
