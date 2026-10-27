"""
gradepack review — judge task quality via a model.

Usage:
    python -m gradepack review <task-id> [--mock]
"""
import json
import re

from gradepack import api as _api
from gradepack import core

_DEFAULT_MODEL = _api._DEFAULT_MODEL

_REVIEW_SYSTEM = """\
You are a task quality reviewer for a coding benchmark. \
You will be given a task description, its starter code, grader tests, and a reference solution. \
Evaluate whether the task is fair and fully specified.

Reply with a JSON object (no markdown, no fences) with these keys:
  verdict       "pass" or "fail"
  fair          true/false
  fully_specified  true/false
  issues        list of strings (empty list if none)
  summary       one sentence summary
"""


def _mock_verdict(task_id: str) -> dict:
    return {
        "task_id": task_id,
        "verdict": "pass",
        "fair": True,
        "fully_specified": True,
        "issues": [],
        "summary": "[mock] Task appears fair and fully specified.",
        "mock": True,
    }


def _parse_json_from_content(content: str) -> dict:
    """Extract JSON from content, stripping optional markdown fences."""
    text = content.strip()
    # Remove ```json ... ``` or ``` ... ``` fences
    text = re.sub(r"^```[^\n]*\n", "", text)
    text = re.sub(r"\n```$", "", text.rstrip())
    return json.loads(text)


def cmd_review(task_id: str, mock: bool = False) -> None:
    task_root = core.task_dir(task_id)
    if not task_root.exists():
        print(json.dumps({"error": f"task '{task_id}' not found"}))
        return

    if mock:
        result = _mock_verdict(task_id)
        print(json.dumps(result, indent=2))
        return

    meta = core.load_task_json(task_id)

    def _read_dir(subdir: str) -> str:
        d = task_root / subdir
        if not d.exists():
            return ""
        parts = []
        for p in sorted(d.iterdir()):
            if p.is_file():
                parts.append(f"=== {subdir}/{p.name} ===\n{p.read_text()}")
        return "\n\n".join(parts)

    user_text = (
        f"Task ID: {task_id}\n"
        f"Prompt: {meta.get('prompt', '')}\n\n"
        f"{_read_dir('starter')}\n\n"
        f"{_read_dir('grader')}\n\n"
        f"{_read_dir('solution')}"
    )

    try:
        resp_data = _api.chat(_REVIEW_SYSTEM, user_text, temperature=0, max_tokens=1024)
        content = _api.extract_content(resp_data)
        verdict = _parse_json_from_content(content)
        verdict["task_id"] = task_id
    except Exception as exc:
        verdict = {"task_id": task_id, "error": str(exc)}

    print(json.dumps(verdict, indent=2))
