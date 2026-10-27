"""
gradepack CLI commands.

Usage:
    python -m gradepack list
    python -m gradepack verify <task-id>
    python -m gradepack run <task-id> --candidate <dir>
    python -m gradepack bench --model <name> [--attempts N] [--parallel M] [--mock]
    python -m gradepack factory [--help]
    python -m gradepack promote <draft-id> [--help]
    python -m gradepack review <task-id> [--mock]
    python -m gradepack serve [--port N]
    python -m gradepack mcp
"""
import argparse
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
        try:
            core.overlay_dir(candidate, tmp_task / "starter")
        except core.CandidateError as exc:
            _print_json_error(task_id, str(exc))
            shutil.rmtree(tmp_parent, ignore_errors=True)
            sys.exit(1)
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


# ---------------------------------------------------------------------------
# promote
# ---------------------------------------------------------------------------

def _build_promote_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gradepack promote",
        description=(
            "Move a discriminating draft from drafts/accepted/<id> into tasks/<id>. "
            "Runs verify before promoting; refuses if verify fails. "
            "Moves review.json to reviews/<id>.json."
        ),
    )
    p.add_argument("draft_id", help="Draft id, e.g. 037-my-task")
    return p


def cmd_promote_argv(argv: list[str]) -> None:
    """Parse argv and run promote. Supports --help."""
    parser = _build_promote_parser()
    args = parser.parse_args(argv)
    cmd_promote(args.draft_id)


def cmd_promote(draft_id: str) -> None:
    from gradepack import factory as _factory

    repo = core._repo_root()
    accepted_dir = repo / "drafts" / "accepted"
    draft_dir = accepted_dir / draft_id

    if not draft_dir.exists():
        # Also accept plain drafts/ for backwards compat
        fallback = repo / "drafts" / draft_id
        if fallback.exists():
            draft_dir = fallback
        else:
            print(f"FAIL: draft '{draft_id}' not found in drafts/accepted/ or drafts/")
            sys.exit(1)

    # 1. Load task.json to confirm id matches directory name
    task_json_path = draft_dir / "task.json"
    if not task_json_path.exists():
        print(f"FAIL: no task.json in {draft_dir}")
        sys.exit(1)
    try:
        meta = json.loads(task_json_path.read_text())
    except Exception as exc:
        print(f"FAIL: cannot parse task.json: {exc}")
        sys.exit(1)

    task_id = meta.get("id", "")
    if task_id != draft_id:
        print(f"FAIL: id in task.json ({task_id!r}) does not match directory name ({draft_id!r})")
        sys.exit(1)

    # 2. Run verify on the draft
    solution_dir = draft_dir / "solution"
    if not solution_dir.exists():
        print(f"FAIL: no solution/ directory found in draft {draft_id}")
        sys.exit(1)

    # Use _verify_draft_files to verify without touching tasks/
    files = {}
    files["task.json"] = task_json_path.read_text()
    for subdir in ("starter", "grader", "solution"):
        d = draft_dir / subdir
        if d.exists():
            for f in d.iterdir():
                if f.is_file():
                    files[f"{subdir}/{f.name}"] = f.read_text()

    ok, reason = _factory._verify_draft_files(files, task_id)
    if not ok:
        print(f"FAIL: verify failed — {reason}")
        sys.exit(1)

    # 3. Check target directory does not already exist
    dest = core.tasks_dir() / task_id
    if dest.exists():
        print(f"FAIL: tasks/{task_id} already exists; cannot overwrite")
        sys.exit(1)

    # 4. Move draft into tasks/
    shutil.copytree(str(draft_dir), str(dest))
    shutil.rmtree(str(draft_dir), ignore_errors=True)

    # 5. Move review.json to reviews/
    reviews_dir = repo / "reviews"
    reviews_dir.mkdir(exist_ok=True)
    review_src = dest / "review.json"
    if review_src.exists():
        shutil.move(str(review_src), str(reviews_dir / f"{task_id}.json"))

    print(f"PROMOTED  {task_id}")
    print(f"  tasks/{task_id}/")
    if (reviews_dir / f"{task_id}.json").exists():
        print(f"  reviews/{task_id}.json")


def _print_json_error(task_id: str, message: str) -> None:
    print(json.dumps({"task_id": task_id, "error": message}, indent=2))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main_entry() -> None:
    """Console-script entry point (installed as `gradepack`)."""
    main(sys.argv[1:])


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
        # Delegate to argparse-based parser (supports --help)
        _bench.cmd_bench_argv(argv[1:])

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
        site = "--site" in argv[1:]
        _registry.cmd_gen_registry(site=site)

    elif command == "validate":
        from gradepack import validate as _validate
        _validate.cmd_validate()

    elif command == "factory":
        from gradepack import factory as _factory
        _factory.cmd_factory_argv(argv[1:])

    elif command == "promote":
        cmd_promote_argv(argv[1:])

    elif command == "report":
        from gradepack import report as _report
        rest = argv[1:]
        model = _get_flag(rest, "--model")
        _report.cmd_report(model_filter=model)

    elif command == "demo":
        if len(argv) < 2:
            print("Usage: python -m gradepack demo <task-id> [--mock]")
            sys.exit(1)
        from gradepack import demo as _demo
        task_id = argv[1]
        rest = argv[2:]
        mock = "--mock" in rest
        _demo.cmd_demo(task_id, mock=mock)

    elif command == "doctor":
        from gradepack import doctor as _doctor
        dry_run_mode = "--dry-run" in argv[1:]
        _doctor.cmd_doctor(dry_run=dry_run_mode)

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
        "  python -m gradepack bench --model <name> [--help]\n"
        "  python -m gradepack factory [--help]\n"
        "  python -m gradepack promote <draft-id> [--help]\n"
        "  python -m gradepack review <task-id> [--mock]\n"
        "  python -m gradepack serve [--port N]\n"
        "  python -m gradepack mcp\n"
    )
