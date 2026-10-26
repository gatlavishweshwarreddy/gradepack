"""
Generate tasks/index.json and llms.txt registry files.
"""
import json

from gradepack import core


def generate_index() -> None:
    """Write tasks/index.json."""
    index = []
    for tid in core.all_task_ids():
        meta = core.load_task_json(tid)
        index.append({
            "id":         meta.get("id", tid),
            "title":      meta.get("title", ""),
            "difficulty": meta.get("difficulty", ""),
            "language":   meta.get("language", ""),
        })
    out = core.tasks_dir() / "index.json"
    out.write_text(json.dumps(index, indent=2))
    print(f"Wrote {out}")


def generate_llms_txt() -> None:
    """Write llms.txt — a plain-text catalogue for LLM consumption."""
    lines = [
        "# gradepack task registry",
        "",
        "A collection of realistic Python debugging tasks with automated graders.",
        "Each task has a starter file with a bug and a grader with pytest tests.",
        "",
        "## Tasks",
        "",
    ]
    for tid in core.all_task_ids():
        meta = core.load_task_json(tid)
        lines.append(f"### {meta.get('id', tid)}")
        lines.append(f"Title: {meta.get('title', '')}")
        lines.append(f"Difficulty: {meta.get('difficulty', '')}")
        lines.append(f"Prompt: {meta.get('prompt', '')}")
        lines.append("")

    out = core._repo_root() / "llms.txt"
    out.write_text("\n".join(lines))
    print(f"Wrote {out}")


def cmd_gen_registry() -> None:
    generate_index()
    generate_llms_txt()
