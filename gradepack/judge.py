"""
gradepack review — judge task quality via a model.

Usage:
    python -m gradepack review <task-id> [--mock]
"""
import json
import os
import urllib.request

from gradepack import core


_REVIEW_SYSTEM = """\
You are a task quality reviewer for a coding benchmark. \
You will be given a task description, its starter code, grader tests, and a reference solution. \
Evaluate whether the task is fair and fully specified.

Reply with a JSON object (no markdown) with these keys:
  verdict       "pass" or "fail"
  fair          true/false — does the task have a clear, unambiguous correct answer?
  fully_specified  true/false — does the prompt describe everything the tests check?
  issues        list of strings describing any problems (empty list if none)
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


def _call_model_review(prompt: str) -> dict:
    base_url = os.environ.get("BASE_URL", "https://api.openai.com/v1")
    api_key  = os.environ.get("API_KEY", "")
    model    = os.environ.get("MODEL", "gpt-4o-mini")

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": _REVIEW_SYSTEM},
            {"role": "user",   "content": prompt},
        ],
        "temperature": 0,
    }).encode()

    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())

    content = data["choices"][0]["message"]["content"]
    return json.loads(content)


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

    prompt_text = (
        f"Task ID: {task_id}\n"
        f"Prompt: {meta.get('prompt', '')}\n\n"
        f"{_read_dir('starter')}\n\n"
        f"{_read_dir('grader')}\n\n"
        f"{_read_dir('solution')}"
    )

    try:
        verdict = _call_model_review(prompt_text)
        verdict["task_id"] = task_id
    except Exception as exc:
        verdict = {"task_id": task_id, "error": str(exc)}

    print(json.dumps(verdict, indent=2))
