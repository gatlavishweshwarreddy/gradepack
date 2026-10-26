"""
Generate registry files for GitHub Pages and LLM consumption.

Usage:
    python -m gradepack gen-registry          # tasks/index.json + llms.txt
    python -m gradepack gen-registry --site   # also writes docs/api/
"""
import json
import pathlib

from gradepack import core

_SITE_BASE = "https://gatlavishweshwarreddy.github.io/gradepack"


def generate_index() -> None:
    """Write tasks/index.json."""
    index = []
    for tid in core.all_task_ids():
        meta = core.load_task_json(tid)
        index.append({
            "id":                meta.get("id", tid),
            "title":             meta.get("title", ""),
            "difficulty":        meta.get("difficulty", ""),
            "language":          meta.get("language", ""),
            "tags":              meta.get("tags", []),
            "estimated_minutes": meta.get("estimated_minutes"),
            "version":           meta.get("version", "1.0"),
        })
    out = core.tasks_dir() / "index.json"
    out.write_text(json.dumps(index, indent=2))
    print(f"Wrote {out}")


def generate_llms_txt(dest: pathlib.Path | None = None) -> None:
    """Write llms.txt — a plain-text catalogue for LLM consumption."""
    lines = [
        "# gradepack task registry",
        "",
        f"Static API: {_SITE_BASE}/api/tasks/<id>.json",
        "",
        "A collection of realistic Python debugging tasks with automated graders.",
        "Each task has a starter file with a deliberate bug and a grader with pytest tests.",
        "",
        "## Tasks",
        "",
    ]
    for tid in core.all_task_ids():
        meta = core.load_task_json(tid)
        lines.append(f"### {meta.get('id', tid)}")
        lines.append(f"Title: {meta.get('title', '')}")
        lines.append(f"Difficulty: {meta.get('difficulty', '')}")
        lines.append(f"Tags: {', '.join(meta.get('tags', []))}")
        lines.append(f"Estimated minutes: {meta.get('estimated_minutes', '?')}")
        lines.append(f"Prompt: {meta.get('prompt', '')}")
        lines.append("")

    out = dest or (core._repo_root() / "llms.txt")
    out.write_text("\n".join(lines))
    print(f"Wrote {out}")


def _read_dir_files(subdir: pathlib.Path) -> dict[str, str]:
    if not subdir.exists():
        return {}
    return {p.name: p.read_text() for p in sorted(subdir.iterdir()) if p.is_file()}


def generate_site_api() -> None:
    """
    Write docs/api/index.json and docs/api/tasks/<id>.json.
    Solution files are never written. docs/llms.txt is also written.
    """
    api_dir = core._repo_root() / "docs" / "api"
    tasks_api_dir = api_dir / "tasks"
    tasks_api_dir.mkdir(parents=True, exist_ok=True)

    index = []
    for tid in core.all_task_ids():
        meta = core.load_task_json(tid)
        task_root = core.task_dir(tid)

        summary = {
            "id":                meta.get("id", tid),
            "title":             meta.get("title", ""),
            "difficulty":        meta.get("difficulty", ""),
            "language":          meta.get("language", ""),
            "tags":              meta.get("tags", []),
            "estimated_minutes": meta.get("estimated_minutes"),
            "version":           meta.get("version", "1.0"),
            "url":               f"{_SITE_BASE}/api/tasks/{tid}.json",
        }
        index.append(summary)

        detail = {
            **summary,
            "prompt":        meta.get("prompt", ""),
            "starter_files": _read_dir_files(task_root / "starter"),
            "grader_files":  _read_dir_files(task_root / "grader"),
            # solution intentionally omitted
        }
        task_out = tasks_api_dir / f"{tid}.json"
        task_out.write_text(json.dumps(detail, indent=2))

    idx_out = api_dir / "index.json"
    idx_out.write_text(json.dumps(index, indent=2))
    print(f"Wrote {idx_out}  ({len(index)} tasks)")
    print(f"Wrote {tasks_api_dir}/<id>.json  ({len(index)} files)")

    # docs/llms.txt
    generate_llms_txt(dest=core._repo_root() / "docs" / "llms.txt")


def cmd_gen_registry(site: bool = False) -> None:
    generate_index()
    generate_llms_txt()
    if site:
        generate_site_api()
