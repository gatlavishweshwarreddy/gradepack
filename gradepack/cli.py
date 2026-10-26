"""
gradepack CLI commands.

Usage:
    python -m gradepack list
    python -m gradepack verify <task-id>
    python -m gradepack run <task-id> --candidate <dir>
    python -m gradepack bench --model <name> [--attempts N] [--parallel M] [--mock]
    python -m gradepack review <task-id> [--mock]
    python -m gradepack serve [--port N]
    python -m gradepack mcp
"""
import json
import pathlib
import shutil
import sys

from gradepack import core


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

def cmd_list() -> None:
    ids = core.all_task_ids()
    if not ids:
        print("No tasks found.")
        return
    for tid in ids:
        try:
            meta = core.load_task_json(tid)
        except Exception as exc:
            print(f"  {tid}  (could not read task.json: {exc})")
            continue
        title      = meta.get("title", "(no title)")
        difficulty = meta.get("difficulty", "(unknown)")
        print(f"  {tid}  |  {difficulty:8s}  |  {title}")


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

def cmd_verify(task_id: str) -> None:
    task_root = core.task_dir(task_id)
    if not task_root.exists():
        print(f"FAIL: task '{task_id}' not found under tasks/")
        sys.exit(1)

    solution_dir = task_root / "solution"
    if not solution_dir.exists():
        print(f"FAIL: no solution/ directory found for task '{task_id}'")
        sys.exit(1)

    tmp_task = core.make_temp_copy(task_id)
    tmp_parent = tmp_task.parent
    try:
        grader_dir = tmp_task / "grader"

        # Step 1 — unmodified starter must have at least one failing test.
        result_starter = core.run_pytest(grader_dir)
        if result_starter["failed"] == 0:
            print(
                f"FAIL: starter has no failing tests "
                f"(expected at least one). "
                f"All {result_starter['total']} tests passed."
            )
            sys.exit(1)

        # Step 2 — overlay solution and require all tests to pass.
        core.overlay_dir(solution_dir, tmp_task / "starter")
        result_solution = core.run_pytest(grader_dir)
        if result_solution["failed"] != 0:
            failing = ", ".join(result_solution["failures"]) or "(unknown)"
            print(
                f"FAIL: solution does not pass all tests. "
                f"Failing: {failing}"
            )
            sys.exit(1)

        print(
            f"PASS  "
            f"starter failures: {result_starter['failures']}  |  "
            f"solution: {result_solution['passed']}/{result_solution['total']} passed"
        )
    finally:
        shutil.rmtree(tmp_parent, ignore_errors=True)


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

def cmd_run(task_id: str, candidate_dir: str) -> None:
    task_root = core.task_dir(task_id)
    if not task_root.exists():
        _print_json_error(task_id, f"task '{task_id}' not found")
        sys.exit(1)

    candidate = pathlib.Path(candidate_dir).resolve()
    if not candidate.exists():
        _print_json_error(task_id, f"candidate directory '{candidate_dir}' not found")
        sys.exit(1)

    tmp_task = core.make_temp_copy(task_id)
    tmp_parent = tmp_task.parent
    try:
        core.overlay_dir(candidate, tmp_task / "starter")
        result = core.run_pytest(tmp_task / "grader")

        total  = result["total"]
        passed = result["passed"]
        score  = round(passed / total, 4) if total > 0 else 0.0

        output = {
            "task_id":      task_id,
            "passed":       passed,
            "failed":       result["failed"],
            "total":        total,
            "score":        score,
            "failing_tests": result["failures"],
        }
        print(json.dumps(output, indent=2))
    finally:
        shutil.rmtree(tmp_parent, ignore_errors=True)


def _print_json_error(task_id: str, message: str) -> None:
    print(json.dumps({"task_id": task_id, "error": message}, indent=2))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str]) -> None:
    if not argv:
        _usage()
        sys.exit(1)

    command = argv[0]

    if command == "list":
        cmd_list()

    elif command == "verify":
        if len(argv) < 2:
            print("Usage: python -m gradepack verify <task-id>")
            sys.exit(1)
        cmd_verify(argv[1])

    elif command == "run":
        if len(argv) < 2:
            print("Usage: python -m gradepack run <task-id> --candidate <dir>")
            sys.exit(1)
        task_id = argv[1]
        candidate_dir = None
        rest = argv[2:]
        for i, arg in enumerate(rest):
            if arg == "--candidate" and i + 1 < len(rest):
                candidate_dir = rest[i + 1]
                break
        if candidate_dir is None:
            print("Usage: python -m gradepack run <task-id> --candidate <dir>")
            sys.exit(1)
        cmd_run(task_id, candidate_dir)

    elif command == "bench":
        from gradepack import bench as _bench
        rest = argv[1:]
        model = _get_flag(rest, "--model") or "mock"
        attempts = int(_get_flag(rest, "--attempts") or "1")
        parallel = int(_get_flag(rest, "--parallel") or "1")
        mock = "--mock" in rest
        mock_pass = "--mock-fail" not in rest
        _bench.cmd_bench(
            model=model,
            attempts=attempts,
            parallel=parallel,
            mock=mock,
            mock_pass=mock_pass,
        )

    elif command == "review":
        if len(argv) < 2:
            print("Usage: python -m gradepack review <task-id> [--mock]")
            sys.exit(1)
        from gradepack import judge as _judge
        mock = "--mock" in argv[2:]
        _judge.cmd_review(argv[1], mock=mock)

    elif command == "serve":
        from gradepack import server as _server
        rest = argv[1:]
        port = int(_get_flag(rest, "--port") or "8000")
        _server.cmd_serve(port=port)

    elif command == "mcp":
        from gradepack import mcp_server as _mcp
        _mcp.cmd_mcp()

    elif command == "gen-registry":
        from gradepack import registry as _registry
        _registry.cmd_gen_registry()

    else:
        print(f"Unknown command: {command!r}")
        _usage()
        sys.exit(1)


def _get_flag(argv: list[str], flag: str) -> str | None:
    """Return the value after `flag` in argv, or None."""
    for i, arg in enumerate(argv):
        if arg == flag and i + 1 < len(argv):
            return argv[i + 1]
    return None


def _usage() -> None:
    print(
        "Usage:\n"
        "  python -m gradepack list\n"
        "  python -m gradepack verify <task-id>\n"
        "  python -m gradepack run <task-id> --candidate <dir>\n"
        "  python -m gradepack bench --model <name> [--attempts N] [--parallel M] [--mock]\n"
        "  python -m gradepack review <task-id> [--mock]\n"
        "  python -m gradepack serve [--port N]\n"
        "  python -m gradepack mcp\n"
    )
