"""
Core helpers shared across CLI commands.
"""
import json
import pathlib
import re
import shutil
import subprocess
import tempfile


# ---------------------------------------------------------------------------
# Repo layout helpers
# ---------------------------------------------------------------------------

def _repo_root() -> pathlib.Path:
    """Return the absolute path to the repo root (contains tasks/)."""
    return pathlib.Path(__file__).resolve().parent.parent


def tasks_dir() -> pathlib.Path:
    return _repo_root() / "tasks"


def task_dir(task_id: str) -> pathlib.Path:
    return tasks_dir() / task_id


def load_task_json(task_id: str) -> dict:
    p = task_dir(task_id) / "task.json"
    with p.open() as f:
        return json.load(f)


def all_task_ids() -> list[str]:
    td = tasks_dir()
    return sorted(
        d.name
        for d in td.iterdir()
        if d.is_dir() and (d / "task.json").exists()
    )


# ---------------------------------------------------------------------------
# Temp-copy / pytest runner
# ---------------------------------------------------------------------------

def make_temp_copy(task_id: str) -> pathlib.Path:
    """
    Copy the whole task directory into a fresh temp directory.
    Returns the path to the copied task root (tmp/<task-id>/).
    Caller is responsible for deleting the parent tempdir when done.
    """
    src = task_dir(task_id)
    tmp_parent = pathlib.Path(tempfile.mkdtemp())
    shutil.copytree(src, tmp_parent / task_id)
    return tmp_parent / task_id


def overlay_dir(src_dir: pathlib.Path, dest_starter: pathlib.Path) -> None:
    """Copy every *file* directly inside src_dir over dest_starter/."""
    for item in src_dir.iterdir():
        if item.is_file():
            shutil.copy2(item, dest_starter / item.name)


def run_pytest(grader_dir: pathlib.Path, timeout: int = 30) -> dict:
    """
    Run pytest on grader_dir using plain-text output.

    Returns:
        passed   int
        failed   int
        total    int
        failures list[str]   bare test function names that failed
        error    str | None  set when pytest could not run at all
    """
    proc = subprocess.run(
        [
            "python", "-m", "pytest",
            str(grader_dir),
            "-v",
            "--tb=no",
            "--no-header",
            "-p", "no:cacheprovider",
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return _parse_verbose_output(proc.stdout + proc.stderr)


def _parse_verbose_output(text: str) -> dict:
    """
    Parse pytest -v output.

    Recognises lines like:
        path/test_foo.py::test_name PASSED
        path/test_foo.py::test_name FAILED
    and the summary line:
        1 failed, 6 passed in 0.02s
        7 passed in 0.01s
    """
    passed = failed = total = 0
    failures: list[str] = []

    for line in text.splitlines():
        # Per-test result lines
        m = re.match(r".*::(\w+)\s+(PASSED|FAILED)", line)
        if m:
            name, outcome = m.group(1), m.group(2)
            if outcome == "FAILED":
                failures.append(name)
            continue

        # Summary line
        if re.search(r"\d+ (passed|failed)", line):
            mp = re.search(r"(\d+) passed", line)
            mf = re.search(r"(\d+) failed", line)
            if mp or mf:
                passed = int(mp.group(1)) if mp else 0
                failed = int(mf.group(1)) if mf else 0
                total  = passed + failed

    return {
        "passed": passed,
        "failed": failed,
        "total": total,
        "failures": failures,
        "error": None,
    }
