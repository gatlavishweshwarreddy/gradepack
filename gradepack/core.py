"""
Core helpers shared across CLI commands.
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
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


# Maximum bytes of pytest output we keep (prevents OOM from pathological output).
_OUTPUT_CAP = 256 * 1024  # 256 KB


class CandidateError(ValueError):
    """Raised when a candidate file fails security/integrity validation."""


def _validate_candidate_files(
    candidate_files: dict[str, str],
    allowed_names: set[str],
) -> None:
    """
    Reject candidate files that:
      - have a path separator or '..' in their name
      - are named 'conftest.py'
      - are not one of the existing starter file names
    Raises CandidateError with a descriptive message.
    """
    for name in candidate_files:
        if os.sep in name or "/" in name or "\\" in name:
            raise CandidateError(f"Rejected: path separator in filename {name!r}")
        if ".." in name.split("/"):
            raise CandidateError(f"Rejected: '..' in filename {name!r}")
        if name == "conftest.py":
            raise CandidateError("Rejected: 'conftest.py' is not allowed")
        if name not in allowed_names:
            raise CandidateError(
                f"Rejected: {name!r} is not an existing starter file "
                f"(allowed: {sorted(allowed_names)})"
            )


def overlay_dir(src_dir: pathlib.Path, dest_starter: pathlib.Path) -> None:
    """
    Copy every *file* directly inside src_dir over dest_starter/.
    Validates filenames against the existing starter contents.
    """
    allowed = {p.name for p in dest_starter.iterdir() if p.is_file()}
    candidate_files = {
        item.name: item.read_text(errors="replace")
        for item in src_dir.iterdir()
        if item.is_file()
    }
    _validate_candidate_files(candidate_files, allowed)
    for name, content in candidate_files.items():
        (dest_starter / name).write_text(content)


def overlay_dict(
    candidate_files: dict[str, str],
    dest_starter: pathlib.Path,
) -> None:
    """
    Write candidate_files (name -> content) into dest_starter/.
    Validates filenames against the existing starter contents.
    """
    allowed = {p.name for p in dest_starter.iterdir() if p.is_file()}
    _validate_candidate_files(candidate_files, allowed)
    for name, content in candidate_files.items():
        (dest_starter / name).write_text(content)


def run_pytest(grader_dir: pathlib.Path, timeout: int = 30) -> dict:
    """
    Run pytest on grader_dir using plain-text output.

    - Runs with a temp cwd (not the grader dir itself).
    - Strips the environment to PATH, HOME, and PYTHONPATH only.
    - Caps combined stdout+stderr at _OUTPUT_CAP bytes.
    - Uses -p no:cacheprovider.

    Returns:
        passed   int
        failed   int
        total    int
        failures list[str]   bare test function names that failed
        error    str | None  set when pytest could not run at all
    """
    # Minimal environment: only forward PATH, HOME, and PYTHONPATH.
    # Always include the directory of the current Python interpreter so that
    # `python -m pytest` resolves correctly even in virtual environments.
    safe_env: dict[str, str] = {}
    for key in ("PATH", "HOME", "PYTHONPATH"):
        val = os.environ.get(key)
        if val is not None:
            safe_env[key] = val

    python_dir = str(pathlib.Path(sys.executable).parent)
    existing_path = safe_env.get("PATH", "")
    if python_dir not in existing_path.split(os.pathsep):
        safe_env["PATH"] = python_dir + os.pathsep + existing_path

    # Use a fresh temp dir as cwd so pytest cannot pick up stray conftest.py files.
    try:
        with tempfile.TemporaryDirectory() as tmp_cwd:
            proc = subprocess.run(
                [
                    "python", "-m", "pytest",
                    str(grader_dir),
                    "-v",
                    "--tb=short",
                    "--no-header",
                    "-p", "no:cacheprovider",
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=tmp_cwd,
                env=safe_env,
            )
    except subprocess.TimeoutExpired as exc:
        # Pytest process timed out — classify as timeout, not runner_error.
        partial = ""
        if exc.stdout:
            partial = exc.stdout if isinstance(exc.stdout, str) else exc.stdout.decode(errors="replace")
        if exc.stderr:
            partial += exc.stderr if isinstance(exc.stderr, str) else exc.stderr.decode(errors="replace")
        return {
            "passed": 0, "failed": 0, "total": 0, "failures": [],
            "error": f"pytest timed out after {timeout}s",
            "timed_out": True,
            "_raw_output": partial[:_OUTPUT_CAP],
        }

    raw = proc.stdout + proc.stderr
    # Cap output size to avoid memory issues.
    if len(raw) > _OUTPUT_CAP:
        raw = raw[:_OUTPUT_CAP] + "\n[output truncated]\n"

    result = _parse_verbose_output(raw)
    result["_raw_output"] = raw
    return result


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
        # Per-test result lines — handle plain and parametrized names
        # e.g. "path::test_foo PASSED" or "path::test_foo[param] FAILED"
        m = re.match(r".*::(test_\S+?)\s+(PASSED|FAILED)", line)
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
