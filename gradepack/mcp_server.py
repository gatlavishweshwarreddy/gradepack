"""
gradepack mcp — MCP server exposing list_tasks, get_task, run_candidate.

Usage:
    python -m gradepack mcp
"""
import asyncio
import json
import pathlib
import shutil
import tempfile

from mcp.server.mcpserver import MCPServer

from gradepack import core


mcp = MCPServer("gradepack", version="0.1.0")


@mcp.tool()
def list_tasks() -> str:
    """List all available task IDs with title and difficulty."""
    tasks = []
    for tid in core.all_task_ids():
        meta = core.load_task_json(tid)
        tasks.append({
            "id":         meta.get("id", tid),
            "title":      meta.get("title", ""),
            "difficulty": meta.get("difficulty", ""),
        })
    return json.dumps(tasks, indent=2)


@mcp.tool()
def get_task(task_id: str) -> str:
    """Return the prompt and starter files for a task (no solution)."""
    task_root = core.task_dir(task_id)
    if not task_root.exists():
        return json.dumps({"error": f"task '{task_id}' not found"})

    meta = core.load_task_json(task_id)
    starter_dir = task_root / "starter"
    starter_files = {
        p.name: p.read_text()
        for p in sorted(starter_dir.iterdir())
        if p.is_file()
    } if starter_dir.exists() else {}

    return json.dumps({
        "id":            meta.get("id", task_id),
        "prompt":        meta.get("prompt", ""),
        "starter_files": starter_files,
    }, indent=2)


@mcp.tool()
def run_candidate(task_id: str, files: dict) -> str:
    """
    Grade a candidate solution.

    Parameters
    ----------
    task_id : str
        The task to grade.
    files : dict
        Mapping of filename -> file content to overlay onto the starter.

    Returns JSON with passed, failed, total, score, failing_tests.
    """
    task_root = core.task_dir(task_id)
    if not task_root.exists():
        return json.dumps({"error": f"task '{task_id}' not found"})

    tmp_task = core.make_temp_copy(task_id)
    tmp_parent = tmp_task.parent
    try:
        try:
            core.overlay_dict(files, tmp_task / "starter")
        except core.CandidateError as exc:
            return json.dumps({"error": str(exc)})
        result = core.run_pytest(tmp_task / "grader")
        total  = result["total"]
        passed = result["passed"]
        return json.dumps({
            "task_id":      task_id,
            "passed":       passed,
            "failed":       result["failed"],
            "total":        total,
            "score":        round(passed / total, 4) if total else 0.0,
            "failing_tests": result["failures"],
        }, indent=2)
    finally:
        shutil.rmtree(tmp_parent, ignore_errors=True)


def cmd_mcp() -> None:
    print("Starting gradepack MCP server (stdio)…")
    asyncio.run(mcp.run_stdio_async())
