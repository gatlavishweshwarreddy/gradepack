"""
gradepack factory — draft and review new tasks using a model.

Usage:
    python -m gradepack factory --n N [--mock]

Each call:
  1. Reads the last 10 lessons from LESSONS.md.
  2. Sends a drafting prompt to the model (one call per task idea).
  3. Parses the response into task.json, starter/<file>, grader/<file>, solution/<file>.
  4. Runs verify on the draft.
  5. Sends a separate review prompt to the model (fresh request, no shared history).
  6. Records verdict + reason in drafts/<id>/review.json.
  7. If rejected: appends the rejection reason as a lesson to LESSONS.md.

Accepted drafts stay in drafts/ until manually moved into tasks/.
Mock mode works fully offline.
"""
import datetime
import json
import pathlib
import re
import shutil
import sys
import tempfile

from gradepack import api as _api
from gradepack import core

_REPO = core._repo_root()
_DRAFTS_DIR = _REPO / "drafts"
_LESSONS_FILE = _REPO / "LESSONS.md"
_DEFAULT_MODEL = _api._DEFAULT_MODEL

# ---------------------------------------------------------------------------
# Lessons
# ---------------------------------------------------------------------------

def _load_last_lessons(n: int = 10) -> list[str]:
    if not _LESSONS_FILE.exists():
        return []
    text = _LESSONS_FILE.read_text()
    # Extract bullet lines after the HTML comment marker
    after = text.split("<!-- lessons below")[1] if "<!-- lessons below" in text else text
    items = [line.lstrip("- •").strip() for line in after.splitlines()
             if line.strip().startswith(("-", "•"))]
    return items[-n:]


def _append_lesson(reason: str) -> None:
    lesson = reason.strip().rstrip(".")
    line = f"\n- {lesson}."
    with _LESSONS_FILE.open("a") as f:
        f.write(line)


# ---------------------------------------------------------------------------
# Mock task generation
# ---------------------------------------------------------------------------

_MOCK_TASK_COUNTER = [100]  # starts from 100 to avoid collisions with real tasks


def _mock_draft() -> dict:
    _MOCK_TASK_COUNTER[0] += 1
    n = _MOCK_TASK_COUNTER[0]
    task_id = f"mock-{n:03d}-example"
    return {
        "task.json": json.dumps({
            "id": task_id,
            "title": f"Mock task {n}: fix the broken adder",
            "language": "python",
            "difficulty": "easy",
            "prompt": (
                f"The function add(a, b) in starter/adder.py returns a - b instead of a + b. "
                f"Fix it so that add(1, 2) == 3, add(0, 0) == 0, add(-1, 5) == 4, "
                f"add(100, 200) == 300, and add(-3, -7) == -10. (mock task {n})"
            ),
            "grader": "pytest",
            "version": "1.0",
            "tags": ["arithmetic", "mock"],
            "estimated_minutes": 5,
            "license": "MIT",
        }, indent=2),
        "starter/adder.py": "def add(a, b):\n    return a - b  # BUG\n",
        "grader/test_adder.py": (
            "import os, sys, pytest\n"
            "sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'starter'))\n"
            "from adder import add\n\n"
            "@pytest.mark.parametrize('a,b,expected', [\n"
            "    (1, 2, 3), (0, 0, 0), (-1, 5, 4), (100, 200, 300), (-3, -7, -10)\n"
            "])\n"
            "def test_add(a, b, expected):\n"
            "    assert add(a, b) == expected\n"
        ),
        "solution/adder.py": "def add(a, b):\n    return a + b\n",
    }


# ---------------------------------------------------------------------------
# Real model drafting / review
# ---------------------------------------------------------------------------

_DRAFT_SYSTEM = """\
You are a task author for a Python coding benchmark. \
Create one original debugging task in the following STRICT format. \
Do NOT add prose outside the file blocks.

=== task.json ===
{json with id, title, language, difficulty, prompt, grader, version, tags, estimated_minutes, license}

=== starter/<filename>.py ===
{buggy python file}

=== grader/test_<name>.py ===
{pytest test file with sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'starter'))}

=== solution/<filename>.py ===
{corrected python file}

Rules:
- difficulty must be "hard"
- prompt must be ≥ 200 characters and describe EVERYTHING the tests check
- starter must fail ≥ 1 grader test, solution must pass ALL grader tests
- grader must include parametrized tests and a seeded random reference
- id must be a unique slug like "019-your-title"
- no network calls, no external dependencies beyond Python stdlib + pytest
"""

_REVIEW_SYSTEM = """\
You are a task quality reviewer for a Python coding benchmark. \
You will be given a draft task (task.json, starter, grader, solution). \
Evaluate whether it meets the benchmark standards.

Reply with a JSON object ONLY (no markdown) with:
  verdict           "accept" or "reject"
  fair              true/false
  fully_specified   true/false
  issues            list of strings (empty if none)
  summary           one sentence
"""


def _chat(system: str, user: str) -> str:
    resp_data = _api.chat(system, user, temperature=0.7, max_tokens=4096, timeout=180)
    content = _api.extract_content(resp_data)
    if not content:
        raise RuntimeError("Model returned empty content")
    return content


def _parse_file_blocks(content: str) -> dict[str, str]:
    """Parse '=== path/file.py ===' blocks from model output."""
    files: dict[str, str] = {}
    parts = re.split(r"^===\s*(.+?)\s*===$", content, flags=re.MULTILINE)
    it = iter(parts[1:])
    for name, body in zip(it, it):
        files[name.strip()] = body.strip("\n")
    return files


def _model_draft(lessons: list[str]) -> dict[str, str]:
    lesson_text = "\n".join(f"- {l}" for l in lessons) if lessons else "(none yet)"
    user = (
        f"Create a new hard Python debugging task.\n\n"
        f"Lessons from previously rejected drafts (avoid these mistakes):\n{lesson_text}"
    )
    raw = _chat(_DRAFT_SYSTEM, user)
    return _parse_file_blocks(raw)


def _model_review(draft_dir: pathlib.Path) -> dict:
    parts = []
    for fname in ["task.json", "starter", "grader", "solution"]:
        p = draft_dir / fname
        if p.is_file():
            parts.append(f"=== {fname} ===\n{p.read_text()}")
        elif p.is_dir():
            for f in sorted(p.iterdir()):
                if f.is_file():
                    parts.append(f"=== {fname}/{f.name} ===\n{f.read_text()}")
    user = "\n\n".join(parts)
    raw = _chat(_REVIEW_SYSTEM, user)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Try to extract JSON from the response
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            return json.loads(m.group())
        return {"verdict": "reject", "issues": ["Could not parse review response"], "summary": raw[:200]}


# ---------------------------------------------------------------------------
# Draft materialisation
# ---------------------------------------------------------------------------

def _materialise_draft(files: dict[str, str], draft_root: pathlib.Path) -> str | None:
    """
    Write files to draft_root. Returns error string on failure, None on success.
    """
    task_json_text = files.get("task.json")
    if not task_json_text:
        return "No task.json in draft"
    try:
        meta = json.loads(task_json_text)
    except json.JSONDecodeError as exc:
        return f"task.json is not valid JSON: {exc}"

    task_id = meta.get("id", "")
    if not task_id:
        return "task.json has no 'id' field"

    draft_root.mkdir(parents=True, exist_ok=True)
    (draft_root / "task.json").write_text(task_json_text)

    for path_str, content in files.items():
        if path_str == "task.json":
            continue
        # Normalise: 'starter/adder.py' → starter/adder.py
        p = pathlib.PurePosixPath(path_str)
        dest = draft_root
        for part in p.parts:
            dest = dest / part
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)

    return None


# ---------------------------------------------------------------------------
# Single draft pipeline
# ---------------------------------------------------------------------------

def _run_factory_once(mock: bool, lessons: list[str]) -> dict:
    """Draft one task, verify it, review it. Returns a result record."""
    # 1. Draft
    if mock:
        files = _mock_draft()
    else:
        try:
            files = _model_draft(lessons)
        except Exception as exc:
            return {"status": "error", "stage": "draft", "reason": str(exc)}

    # 2. Materialise into a temp draft dir to run verify
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        task_json_text = files.get("task.json", "{}")
        try:
            meta = json.loads(task_json_text)
        except Exception:
            meta = {}
        task_id = meta.get("id", f"draft-{datetime.datetime.utcnow().strftime('%H%M%S')}")
        tmp_task = tmp_path / task_id
        err = _materialise_draft(files, tmp_task)
        if err:
            return {"status": "error", "stage": "parse", "reason": err, "task_id": task_id}

        # 3. Verify (using temp dir as tasks root)
        verify_ok = False
        verify_reason = ""
        try:
            # Temporarily patch tasks_dir to point to tmp
            orig_tasks_dir = core.tasks_dir
            orig_task_dir  = core.task_dir
            core.tasks_dir = lambda: tmp_path
            core.task_dir  = lambda tid: tmp_path / tid
            # Run grader against starter
            starter_result = core.run_pytest(tmp_task / "grader")
            if starter_result["failed"] == 0:
                verify_reason = f"starter has no failing tests (all {starter_result['total']} pass)"
            else:
                # Overlay solution
                sol_dir = tmp_task / "solution"
                tmp_grader_copy = pathlib.Path(tempfile.mkdtemp())
                try:
                    shutil.copytree(str(tmp_task), str(tmp_grader_copy / task_id))
                    task_copy = tmp_grader_copy / task_id
                    for f in sol_dir.iterdir():
                        if f.is_file():
                            shutil.copy2(f, task_copy / "starter" / f.name)
                    sol_result = core.run_pytest(task_copy / "grader")
                    if sol_result["failed"] != 0:
                        verify_reason = f"solution fails: {sol_result['failures']}"
                    else:
                        verify_ok = True
                finally:
                    shutil.rmtree(tmp_grader_copy, ignore_errors=True)
        except Exception as exc:
            verify_reason = str(exc)
        finally:
            core.tasks_dir = orig_tasks_dir
            core.task_dir  = orig_task_dir

    if not verify_ok:
        # Don't save; return early
        return {"status": "rejected_verify", "task_id": task_id, "reason": verify_reason}

    # 4. Save draft
    draft_dir = _DRAFTS_DIR / task_id
    _materialise_draft(files, draft_dir)

    # 5. Review (fresh request, no shared history)
    if mock:
        review = {
            "verdict": "accept",
            "fair": True,
            "fully_specified": True,
            "issues": [],
            "summary": "[mock] Draft accepted.",
        }
    else:
        try:
            review = _model_review(draft_dir)
        except Exception as exc:
            review = {"verdict": "reject", "issues": [str(exc)], "summary": str(exc)}

    review["task_id"] = task_id
    review["date"]    = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    (draft_dir / "review.json").write_text(json.dumps(review, indent=2))

    verdict = review.get("verdict", "reject")
    if verdict != "accept":
        issues = review.get("issues", [])
        reason = review.get("summary", "no reason given")
        _append_lesson(reason)
        return {"status": "rejected_review", "task_id": task_id, "reason": reason, "issues": issues}

    return {"status": "accepted", "task_id": task_id, "draft_dir": str(draft_dir)}


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def cmd_factory(n: int = 1, mock: bool = False) -> None:
    _DRAFTS_DIR.mkdir(exist_ok=True)
    lessons = _load_last_lessons(10)

    print(f"gradepack factory: generating {n} task draft(s)  [mock={mock}]")
    if lessons:
        print(f"  Using {len(lessons)} lesson(s) from LESSONS.md")

    for i in range(n):
        print(f"\n--- Draft {i+1}/{n} ---")
        result = _run_factory_once(mock=mock, lessons=lessons)
        status = result.get("status", "error")
        task_id = result.get("task_id", "?")

        if status == "accepted":
            print(f"  ACCEPTED  {task_id}")
            print(f"  Draft saved to: {result['draft_dir']}")
            print(f"  Move to tasks/ when ready.")
        elif status == "rejected_review":
            print(f"  REJECTED (review)  {task_id}")
            print(f"  Reason: {result['reason']}")
            print(f"  Lesson appended to LESSONS.md")
        elif status == "rejected_verify":
            print(f"  REJECTED (verify)  {task_id}")
            print(f"  Reason: {result['reason']}")
        else:
            print(f"  ERROR at stage={result.get('stage','?')}: {result.get('reason','?')}")

        # Update lessons for next iteration
        lessons = _load_last_lessons(10)
