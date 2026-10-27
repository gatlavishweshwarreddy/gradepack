"""
gradepack factory — draft and review new tasks using a model.

Usage (--help for full options):
    python -m gradepack factory --help
    python -m gradepack factory --n 3 --mock
    python -m gradepack factory --target-kept 2 --max-drafts 10 --mock

Pipeline per draft:
  1. Reads the last 10 lessons from LESSONS.md (including too-easy lessons).
  2. Assigns a domain round-robin (14 domains) and sends a drafting prompt.
     - If finish_reason=="length" and content is empty/truncated, retries once
       with max_tokens doubled (cap 32768); records retried=true in stats.
  3. Extracts file blocks robustly: strips code fences, finds the largest
     top-level JSON object, falls back gracefully on truncated/invalid JSON.
  4. Runs lint_draft() — rejects drafts that leak bugs in comments/strings,
     use time assertions, access private attributes, etc.
  5. Runs verify on the draft (each run uses its own unique temp directory).
  6. Sends a separate review prompt to the model (fresh request, no shared history).
  7. Records verdict + reason in drafts/<category>/<id>/review.json.
  8. Probe stage: runs the model against the draft --probe-attempts times.
     - All probes pass  → "too_easy" → saved under drafts/too_easy/  + lesson appended
     - ≥1 probe fails   → "discriminating" → saved under drafts/accepted/
     - Judge rejected   → saved under drafts/rejected/
  9. Writes factory_stats.json after each draft.
 10. Writes drafts/_progress.json after each draft (--resume skips finished ids).

Draft-stage failure reasons tracked in stats:
  empty_content   — finish_reason length, content empty even after retry
  truncated_json  — task.json appears truncated (no closing brace)
  invalid_json    — task.json present but not valid JSON
  other           — any other draft-stage error

Lint-stage failure reasons (lint_rejected stage):
  private_attr    — grader accesses private attr not in prompt/starter docstrings
  bug_comment     — starter contains revealing bug hints (BUG, FIXME, TODO fix, etc.)
  short_title     — title missing or shorter than 8 characters
  time_assertion  — grader uses time.time() / time.sleep() for assertions
  prompt_too_long — prompt exceeds 1500 characters
  few_tests       — fewer than 6 test functions in the grader

Accepted (discriminating) drafts stay in drafts/accepted/ until promoted via:
    python -m gradepack promote <draft-id>

Mock mode works fully offline. --parallel N drafts concurrently (default 2).
"""
import argparse
import ast
import concurrent.futures
import datetime
import json
import pathlib
import re
import shutil
import sys
import tempfile
import threading as _threading

from gradepack import api as _api
from gradepack import core

_REPO = core._repo_root()
_DRAFTS_DIR      = _REPO / "drafts"
_ACCEPTED_DIR    = _DRAFTS_DIR / "accepted"
_REJECTED_DIR    = _DRAFTS_DIR / "rejected"
_TOO_EASY_DIR    = _DRAFTS_DIR / "too_easy"
_LESSONS_FILE    = _REPO / "LESSONS.md"
_STATS_FILE      = _REPO / "factory_stats.json"
# _PROGRESS_FILE is computed at call time so tests can patch _DRAFTS_DIR
def _get_progress_file() -> pathlib.Path:
    return _DRAFTS_DIR / "_progress.json"
_DEFAULT_MODEL   = _api._DEFAULT_MODEL

_DEFAULT_DRAFT_MAX_TOKENS = 24000

# Protects the final save step (assign id + copytree + stats update)
# so parallel workers don't race on numbering or stat writes.
_SAVE_LOCK = _threading.Lock()

# ---------------------------------------------------------------------------
# Domain rotation — 14 domains, round-robin
# ---------------------------------------------------------------------------

_DOMAINS = [
    "string processing",
    "date and time arithmetic",
    "data structures (trees, graphs)",
    "file I/O and parsing",
    "numerical algorithms",
    "sorting and searching",
    "state machines",
    "caching and memoisation",
    "serialisation / deserialisation",
    "iterator and generator protocols",
    "class invariants and object lifecycle",
    "recursion and dynamic programming",
    "concurrency primitives (locks, semaphores)",
    "cryptographic utilities (hashing, encoding)",
]

_DOMAIN_COUNTER_LOCK = _threading.Lock()
_domain_counter = 0   # module-level counter; protected by _DOMAIN_COUNTER_LOCK


def _next_domain() -> str:
    global _domain_counter
    with _DOMAIN_COUNTER_LOCK:
        domain = _DOMAINS[_domain_counter % len(_DOMAINS)]
        _domain_counter += 1
    return domain


# ---------------------------------------------------------------------------
# Lint gate — runs before verify, before judge
# ---------------------------------------------------------------------------

_BUG_HINT_PATTERN = re.compile(
    r"\b(BUG|bug here|intentionally|FIXME|TODO fix|wrong|should be)\b",
    re.IGNORECASE,
)

_FORBIDDEN_DOMAINS_IN_PROMPT = [
    "rate limiter", "rate-limiter", "token bucket", "scheduler",
    "workflow engine", "workflow-engine",
]


def _collect_docstring_names(source: str) -> set[str]:
    """
    Return all identifiers mentioned in any docstring in the source.
    We tokenise words from docstrings so the grader can legitimately access
    a private attr if it is documented in the starter.
    """
    names: set[str] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return names
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            docstring = ast.get_docstring(node)
            if docstring:
                for word in re.findall(r"[A-Za-z_]\w*", docstring):
                    names.add(word)
    return names


def _grader_private_attrs(grader_source: str) -> set[str]:
    """
    Return all private (underscore-prefixed, non-dunder) attribute/method
    names accessed in the grader source via attribute lookup.
    """
    attrs: set[str] = set()
    try:
        tree = ast.parse(grader_source)
    except SyntaxError:
        return attrs
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            name = node.attr
            if name.startswith("_") and not (name.startswith("__") and name.endswith("__")):
                attrs.add(name)
    return attrs


def lint_draft(files: dict[str, str]) -> list[str]:
    """
    Lint a draft files dict.  Returns a list of problem strings.
    Empty list means the draft passes all checks.

    Checks (each with a short reason prefix for stats):
    1. private_attr  — grader accesses private attr not in prompt/starter docstrings
    2. bug_comment   — starter has revealing hints (BUG, bug here, intentionally, ...)
    3. short_title   — task.json title missing or < 8 chars
    4. time_assertion — grader uses time.time() / time.sleep() in assertions
    5. prompt_too_long — prompt > 1500 chars
    6. few_tests     — grader has < 6 test functions
    """
    problems: list[str] = []

    # Parse task.json for metadata
    meta: dict = {}
    raw_task = files.get("task.json", "")
    if raw_task:
        parsed, _ = _extract_json_robust(raw_task)
        if parsed:
            meta = parsed

    prompt: str = meta.get("prompt", "")
    title: str = meta.get("title", "")

    # ── 3. short_title ───────────────────────────────────────────────────────
    if not title or len(title.strip()) < 8:
        problems.append(
            f"short_title: title is missing or shorter than 8 characters (got {len(title.strip())} chars)"
        )

    # ── 5. prompt_too_long ───────────────────────────────────────────────────
    if len(prompt) > 1500:
        problems.append(
            f"prompt_too_long: prompt is {len(prompt)} chars (max 1500)"
        )

    # Collect starter sources and docstring-mentioned names
    starter_sources: list[str] = []
    for path, content in files.items():
        if path.startswith("starter/") and path.endswith(".py"):
            starter_sources.append(content)

    # Names mentioned in prompt words + starter docstrings
    allowed_private: set[str] = set()
    for word in re.findall(r"[A-Za-z_]\w*", prompt):
        if word.startswith("_") and not (word.startswith("__") and word.endswith("__")):
            allowed_private.add(word)
    for src in starter_sources:
        allowed_private |= _collect_docstring_names(src)

    # ── 2. bug_comment ───────────────────────────────────────────────────────
    for path, content in files.items():
        if path.startswith("starter/") and path.endswith(".py"):
            if _BUG_HINT_PATTERN.search(content):
                problems.append(
                    f"bug_comment: starter file {path!r} contains a revealing hint "
                    f"(BUG/bug here/intentionally/FIXME/TODO fix/wrong/should be)"
                )
                break  # one report per draft is enough

    # Collect grader sources
    grader_sources: dict[str, str] = {}
    for path, content in files.items():
        if path.startswith("grader/") and path.endswith(".py"):
            grader_sources[path] = content

    # ── 1. private_attr ──────────────────────────────────────────────────────
    for gpath, gsrc in grader_sources.items():
        private_attrs = _grader_private_attrs(gsrc)
        leaking = private_attrs - allowed_private
        if leaking:
            problems.append(
                f"private_attr: grader {gpath!r} accesses private attributes "
                f"not in prompt/docstrings: {sorted(leaking)}"
            )

    # ── 4. time_assertion ────────────────────────────────────────────────────
    for gpath, gsrc in grader_sources.items():
        if re.search(r"\btime\.(time|sleep)\s*\(", gsrc):
            problems.append(
                f"time_assertion: grader {gpath!r} uses time.time() or time.sleep() "
                f"which creates flaky timing-dependent assertions"
            )
            break

    # ── 6. few_tests ─────────────────────────────────────────────────────────
    test_count = 0
    for gsrc in grader_sources.values():
        try:
            tree = ast.parse(gsrc)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                    test_count += 1
        except SyntaxError:
            pass
    if test_count < 6:
        problems.append(
            f"few_tests: grader has only {test_count} test function(s), need ≥ 6"
        )

    return problems


# ---------------------------------------------------------------------------
# Lint reason taxonomy
# ---------------------------------------------------------------------------

_LINT_REASONS = ("private_attr", "bug_comment", "short_title",
                 "time_assertion", "prompt_too_long", "few_tests")

_LINT_LESSONS = {
    "private_attr":    "Do not access private attributes of the object under test unless they are named in the prompt or starter docstrings",
    "bug_comment":     "Never put BUG/FIXME/TODO fix/intentionally/wrong/should be comments or strings in the starter — they reveal the bug location",
    "short_title":     "Task title must be at least 8 characters long",
    "time_assertion":  "Do not use time.time() or time.sleep() in grader assertions — they are inherently flaky",
    "prompt_too_long": "Keep the prompt under 1500 characters so the model must read the code rather than rewrite from spec",
    "few_tests":       "Include at least 6 test functions in the grader for adequate coverage",
}


def _extract_lint_reason(problem: str) -> str:
    """Extract the reason prefix from a lint problem string."""
    for r in _LINT_REASONS:
        if problem.startswith(r + ":"):
            return r
    return "other"


# ---------------------------------------------------------------------------
# Lessons
# ---------------------------------------------------------------------------

def _load_last_lessons(n: int = 10) -> list[str]:
    if not _LESSONS_FILE.exists():
        return []
    text = _LESSONS_FILE.read_text()
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
# Auto-numbering: next free task number (never collides with tasks/ or drafts/)
# ---------------------------------------------------------------------------

def _existing_numbers() -> set[int]:
    """Return all numeric prefixes already used in tasks/ or any drafts/ subdirectory."""
    nums: set[int] = set()
    for base_dir in [core.tasks_dir(), _ACCEPTED_DIR, _REJECTED_DIR, _TOO_EASY_DIR, _DRAFTS_DIR]:
        if not base_dir.exists():
            continue
        for d in base_dir.iterdir():
            if not d.is_dir():
                continue
            m = re.match(r"^(\d+)-", d.name)
            if m:
                nums.add(int(m.group(1)))
    return nums


def _next_task_number() -> int:
    """Return the next free three-digit task number (037 and up)."""
    used = _existing_numbers()
    n = 37
    while n in used:
        n += 1
    return n


def _assign_id(files: dict[str, str]) -> tuple[dict[str, str], str]:
    """
    Rewrite the id in task.json to use the next free numeric prefix.
    The slug part (everything after NNN-) is kept; if no slug, uses 'task'.
    Returns (modified_files, new_id).
    """
    task_json_text = files.get("task.json", "{}")
    try:
        meta = json.loads(task_json_text)
    except Exception:
        meta = {}

    old_id = meta.get("id", "")
    slug_match = re.match(r"^\d+-(.+)$", old_id)
    slug = slug_match.group(1) if slug_match else (old_id or "task")

    num = _next_task_number()
    new_id = f"{num:03d}-{slug}"
    meta["id"] = new_id

    new_files = dict(files)
    new_files["task.json"] = json.dumps(meta, indent=2)
    return new_files, new_id


# ---------------------------------------------------------------------------
# Mock task generation
# ---------------------------------------------------------------------------

_MOCK_TASK_SLUG = "example"


def _mock_draft(domain: str | None = None) -> dict:
    used_domain = domain or "arithmetic"
    return {
        "task.json": json.dumps({
            "id": f"000-{_MOCK_TASK_SLUG}",   # will be renumbered by _assign_id
            "title": "Fix the broken adder",
            "language": "python",
            "difficulty": "hard",
            "prompt": (
                "The function add(a, b) in starter/adder.py returns the wrong result. "
                "Fix it so all grader tests pass. The function should perform basic "
                "integer addition. Check edge cases including negative numbers, zero, "
                "and large values. The grader will run parametrized tests. "
                "Do not change the function signature. (mock task)"
            ),
            "grader": "pytest",
            "version": "1.0",
            "tags": [used_domain, "mock"],
            "estimated_minutes": 5,
            "license": "MIT",
        }, indent=2),
        "starter/adder.py": "def add(a, b):\n    return a - b\n",
        "grader/test_adder.py": (
            "import os, sys\n"
            "sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'starter'))\n"
            "from adder import add\n\n"
            "def test_add_basic():\n    assert add(1, 2) == 3\n\n"
            "def test_add_zeros():\n    assert add(0, 0) == 0\n\n"
            "def test_add_negative():\n    assert add(-1, 5) == 4\n\n"
            "def test_add_large():\n    assert add(100, 200) == 300\n\n"
            "def test_add_both_negative():\n    assert add(-3, -7) == -10\n\n"
            "def test_add_identity():\n    assert add(999, 1) == 1000\n"
        ),
        "solution/adder.py": "def add(a, b):\n    return a + b\n",
    }


# ---------------------------------------------------------------------------
# Real model drafting / review
# ---------------------------------------------------------------------------

_DRAFT_SYSTEM = """\
You are a task author for a Python coding benchmark.
Create one original debugging task in the following STRICT format.
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
- starter must fail ≥ 1 grader test, solution must pass ALL grader tests
- no network calls, no external dependencies beyond Python stdlib + pytest
- id must be a unique slug like "000-your-title" (the system will assign a real number)
- the grader must include at least 6 test functions
- do NOT add BUG, FIXME, TODO, or "intentionally wrong" comments to the starter
- do NOT use time.time() or time.sleep() in the grader

Guidance for making hard, discriminating tasks that a model cannot easily solve:
- Do NOT enumerate the expected behaviour exhaustively in the prompt; keep the prompt
  shorter than the code, so the model must read the code to understand the contract
- Require reading several files or tracing multiple interacting code paths
- Use interacting constraints (two bugs that each look innocent but combine wrongly)
- Include deterministic concurrency, state-machine, or ordering invariants
- Use operation-count or asymptotic performance limits (the grader instruments calls)
- Do NOT list every test case in the prompt — the model should not be able to rewrite
  from scratch using only the prompt
- Do NOT add rate limiters, token buckets, schedulers, or workflow engines
"""

_REVIEW_SYSTEM = """\
You are a task quality reviewer for a Python coding benchmark.
You will be given a draft task (task.json, starter, grader, solution).
Evaluate whether it meets the benchmark standards.

Reply with a JSON object ONLY (no markdown) with:
  verdict           "accept" or "reject"
  fair              true/false
  fully_specified   true/false
  issues            list of strings (empty if none)
  summary           one sentence
"""


def _extract_json_robust(text: str) -> tuple[dict | None, str]:
    """
    Extract the first/largest top-level JSON object from text.

    Strips:
      - leading/trailing whitespace
      - markdown code fences (```json ... ``` or ``` ... ```)
      - leading prose before the first '{'
      - trailing prose after the last '}'

    Returns (parsed_dict, failure_reason).
    failure_reason is "" on success, one of:
      "empty_content"   — text is empty or only whitespace
      "truncated_json"  — looks like JSON but has no closing '}'
      "invalid_json"    — has braces but json.loads fails
    """
    if not text or not text.strip():
        return None, "empty_content"

    # Strip markdown code fences
    stripped = text.strip()
    stripped = re.sub(r"^```[a-zA-Z]*\n?", "", stripped)
    stripped = re.sub(r"\n?```$", "", stripped.rstrip())
    stripped = stripped.strip()

    # Find the first '{' and last '}' to isolate the JSON object
    start = stripped.find("{")
    end   = stripped.rfind("}")

    if start == -1:
        return None, "invalid_json"

    if end == -1 or end < start:
        return None, "truncated_json"

    candidate = stripped[start:end + 1]

    try:
        return json.loads(candidate), ""
    except json.JSONDecodeError:
        # Check if it just looks truncated (no closing brace on last line)
        if not stripped.rstrip().endswith("}"):
            return None, "truncated_json"
        return None, "invalid_json"


def _chat_draft(
    system: str,
    user: str,
    max_tokens: int,
    timeout: int = 180,
) -> tuple[str, bool]:
    """
    Call the model for draft generation.

    Returns (content, retried).

    If finish_reason is "length" and content is empty/unusably short,
    retries once with max_tokens doubled (cap 32768).
    """
    resp_data = _api.chat(system, user, temperature=0.7, max_tokens=max_tokens, timeout=timeout)
    content      = _api.extract_content(resp_data)
    finish_reason = _api.extract_finish_reason(resp_data)
    retried = False

    # Retry on truncation: empty or very short content on a length finish
    if finish_reason in ("length", "max_tokens") and not content:
        doubled = min(max_tokens * 2, 32768)
        resp2         = _api.chat(system, user, temperature=0.7, max_tokens=doubled, timeout=timeout)
        content       = _api.extract_content(resp2)
        finish_reason = _api.extract_finish_reason(resp2)
        retried = True

    return content, retried


def _chat(system: str, user: str, max_tokens: int = 16384) -> str:
    """Simple chat call for review (no retry needed)."""
    resp_data = _api.chat(system, user, temperature=0.7, max_tokens=max_tokens, timeout=180)
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


def _extract_task_json(files: dict[str, str]) -> tuple[dict | None, str]:
    """
    Parse task.json from the files dict, handling code fences and truncation.
    Returns (meta_dict, failure_reason).  failure_reason="" on success.
    """
    raw = files.get("task.json", "")
    return _extract_json_robust(raw)


def _model_draft(
    lessons: list[str],
    domain: str | None = None,
    max_tokens: int = _DEFAULT_DRAFT_MAX_TOKENS,
) -> tuple[dict[str, str], bool, str]:
    """
    Draft a task via the model.

    Returns (files_dict, retried, failure_reason).
    failure_reason is "" on success, otherwise one of:
      empty_content | truncated_json | invalid_json | other
    """
    lesson_text = "\n".join(f"- {l}" for l in lessons) if lessons else "(none yet)"
    domain_line = f"\nUse the domain: **{domain}**." if domain else ""
    user = (
        f"Create a new hard Python debugging task.{domain_line}\n\n"
        f"Lessons from previous drafts (avoid these mistakes):\n{lesson_text}"
    )
    try:
        content, retried = _chat_draft(_DRAFT_SYSTEM, user, max_tokens=max_tokens)
    except Exception as exc:
        return {}, False, f"other: {exc}"

    if not content:
        return {}, retried, "empty_content"

    files = _parse_file_blocks(content)

    # Check task.json parses
    if "task.json" in files:
        _, fail_reason = _extract_task_json(files)
        if fail_reason:
            # Try to repair: rewrite task.json key with the extracted raw text
            files["task.json"] = files["task.json"]  # keep as-is; caller will handle
            return files, retried, fail_reason

    return files, retried, ""


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
    # Try direct parse, then robust extraction
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        parsed, _ = _extract_json_robust(raw)
        if parsed is not None:
            return parsed
        return {"verdict": "reject", "issues": ["Could not parse review response"], "summary": raw[:200]}


# ---------------------------------------------------------------------------
# Draft materialisation
# ---------------------------------------------------------------------------

def _materialise_draft(files: dict[str, str], draft_root: pathlib.Path) -> str | None:
    """
    Write files to draft_root. Returns error string on failure, None on success.
    task.json is extracted robustly (strips code fences etc.) before writing.
    """
    raw_task_json = files.get("task.json")
    if not raw_task_json:
        return "No task.json in draft"

    # Robustly parse task.json
    meta, fail_reason = _extract_json_robust(raw_task_json)
    if meta is None:
        return f"task.json parse failed ({fail_reason}): {raw_task_json[:200]}"

    task_id = meta.get("id", "")
    if not task_id:
        return "task.json has no 'id' field"

    draft_root.mkdir(parents=True, exist_ok=True)
    # Write the cleaned-up task.json
    (draft_root / "task.json").write_text(json.dumps(meta, indent=2))

    for path_str, content in files.items():
        if path_str == "task.json":
            continue
        p = pathlib.PurePosixPath(path_str)
        dest = draft_root
        for part in p.parts:
            dest = dest / part
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)

    return None


# ---------------------------------------------------------------------------
# Verify helper (reusable) — uses its own unique temp directory per call
# ---------------------------------------------------------------------------

def _verify_draft_files(files: dict[str, str], task_id: str) -> tuple[bool, str]:
    """
    Materialise files to a freshly-created unique temp dir, run verify.
    Cleans up in a finally block regardless of outcome.
    Returns (ok, reason).
    """
    tmp_base = pathlib.Path(tempfile.mkdtemp())
    try:
        tmp_task = tmp_base / task_id
        err = _materialise_draft(files, tmp_task)
        if err:
            return False, err

        # Run grader against starter
        starter_result = core.run_pytest(tmp_task / "grader")
        if starter_result.get("timed_out"):
            return False, "starter grader timed out"
        if starter_result["failed"] == 0:
            return False, (
                f"starter has no failing tests "
                f"(all {starter_result['total']} pass)"
            )

        # Overlay solution and verify all pass
        sol_dir = tmp_task / "solution"
        tmp2 = pathlib.Path(tempfile.mkdtemp())
        try:
            shutil.copytree(str(tmp_task), str(tmp2 / task_id))
            task_copy = tmp2 / task_id
            # Remove stale __pycache__ so the solution .py files are compiled fresh
            for pycache in (task_copy / "starter").rglob("__pycache__"):
                shutil.rmtree(pycache, ignore_errors=True)
            for f in sol_dir.iterdir():
                if f.is_file():
                    shutil.copy2(f, task_copy / "starter" / f.name)
            sol_result = core.run_pytest(task_copy / "grader")
            if sol_result.get("timed_out"):
                return False, "solution grader timed out"
            if sol_result["failed"] != 0:
                return False, f"solution fails: {sol_result['failures']}"
            return True, ""
        finally:
            shutil.rmtree(str(tmp2), ignore_errors=True)
    finally:
        shutil.rmtree(str(tmp_base), ignore_errors=True)


# ---------------------------------------------------------------------------
# Probe stage — each call uses its own unique temp directory
# ---------------------------------------------------------------------------

def _probe_once(files: dict[str, str], mock: bool) -> bool:
    """
    Run the model once against this draft task (one-shot, same logic as bench).
    Returns True if the model solves it, False otherwise.
    In mock mode, always returns True (simulate an easy task for testing).

    Uses a freshly-created unique temp directory; cleans up in a finally block.
    """
    if mock:
        return True

    tmp_base = pathlib.Path(tempfile.mkdtemp())
    try:
        # Use a fixed subdirectory name within the unique temp base
        tmp_task = tmp_base / "probe-task"
        err = _materialise_draft(files, tmp_task)
        if err:
            return False

        meta_text = files.get("task.json", "{}")
        meta, _ = _extract_json_robust(meta_text)
        if meta is None:
            try:
                meta = json.loads(meta_text)
            except Exception:
                meta = {}
        prompt = meta.get("prompt", "")

        starter_dir = tmp_task / "starter"
        if not starter_dir.exists():
            return False
        starter_files = {
            p.name: p.read_text()
            for p in starter_dir.iterdir()
            if p.is_file() and p.suffix == ".py"
        }
        allowed = set(starter_files)

        try:
            user_msg = _api.build_coding_prompt(prompt, starter_files)
            resp_data = _api.chat(
                _api._SYSTEM_CODING,
                user_msg,
                temperature=0.7,
                max_tokens=8192,
                timeout=180,
            )
            raw = _api.extract_content(resp_data)
            if not raw:
                return False
            candidate_files = _api.parse_coding_response(raw, allowed)
            if not candidate_files:
                return False
        except Exception:
            return False

        # Run grader in a separate unique temp copy
        tmp3 = pathlib.Path(tempfile.mkdtemp())
        try:
            shutil.copytree(str(tmp_task), str(tmp3 / "probe-task"))
            task_copy = tmp3 / "probe-task"
            try:
                core.overlay_dict(candidate_files, task_copy / "starter")
            except core.CandidateError:
                return False
            result = core.run_pytest(task_copy / "grader")
            return result["failed"] == 0 and result["total"] > 0
        finally:
            shutil.rmtree(str(tmp3), ignore_errors=True)
    finally:
        shutil.rmtree(str(tmp_base), ignore_errors=True)


def _probe_draft(
    files: dict[str, str],
    probe_attempts: int,
    mock: bool,
    mock_probe_fail: bool = False,
) -> tuple[str, list[bool]]:
    """
    Run the model probe_attempts times against the draft.

    Returns (classification, probe_results):
      classification: "discriminating" | "too_easy"
      probe_results:  list of bool (True = model solved it)

    mock mode:         all probes return True  → too_easy
    mock_probe_fail:   all probes return False → discriminating
    """
    probe_results: list[bool] = []
    for _ in range(probe_attempts):
        if mock_probe_fail:
            solved = False
        else:
            solved = _probe_once(files, mock=mock)
        probe_results.append(solved)

    classification = "too_easy" if all(probe_results) else "discriminating"
    return classification, probe_results


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

_DRAFT_FAIL_REASONS = ("empty_content", "truncated_json", "invalid_json", "other")


def _load_stats() -> dict:
    if _STATS_FILE.exists():
        try:
            return json.loads(_STATS_FILE.read_text())
        except Exception:
            pass
    base = {
        "drafted": 0,
        "failed_draft_stage": 0,
        "lint_rejected": 0,
        "failed_verify": 0,
        "judge_rejected": 0,
        "judge_accepted": 0,
        "probed": 0,
        "too_easy": 0,
        "discriminating": 0,
        "draft_fail_reasons": {r: 0 for r in _DRAFT_FAIL_REASONS},
        "lint_fail_reasons": {r: 0 for r in _LINT_REASONS},
        "drafts": {},
    }
    return base


def _ensure_draft_fail_reasons(stats: dict) -> None:
    """Back-fill draft_fail_reasons key on old stats files."""
    if "draft_fail_reasons" not in stats:
        stats["draft_fail_reasons"] = {r: 0 for r in _DRAFT_FAIL_REASONS}
    if "lint_fail_reasons" not in stats:
        stats["lint_fail_reasons"] = {r: 0 for r in _LINT_REASONS}
    if "lint_rejected" not in stats:
        stats["lint_rejected"] = 0


def _save_stats(stats: dict) -> None:
    _STATS_FILE.write_text(json.dumps(stats, indent=2))


def _print_funnel(stats: dict) -> None:
    dfr = stats.get("draft_fail_reasons", {})
    lfr = stats.get("lint_fail_reasons", {})
    print("\n── Factory funnel ──────────────────────────────")
    print(f"  drafted            : {stats['drafted']}")
    print(f"  failed draft stage : {stats['failed_draft_stage']}")
    if dfr:
        for reason in _DRAFT_FAIL_REASONS:
            count = dfr.get(reason, 0)
            if count:
                print(f"    {reason:<18s}: {count}")
    print(f"  lint rejected      : {stats.get('lint_rejected', 0)}")
    if lfr:
        for reason in _LINT_REASONS:
            count = lfr.get(reason, 0)
            if count:
                print(f"    {reason:<18s}: {count}")
    print(f"  failed verify      : {stats['failed_verify']}")
    print(f"  judge rejected     : {stats['judge_rejected']}")
    print(f"  judge accepted     : {stats['judge_accepted']}")
    print(f"  probed             : {stats['probed']}")
    print(f"  too easy           : {stats['too_easy']}")
    print(f"  discriminating     : {stats['discriminating']}")
    print("────────────────────────────────────────────────")


# ---------------------------------------------------------------------------
# Progress file (resume support)
# ---------------------------------------------------------------------------

def _load_progress() -> dict:
    """Load _progress.json; returns empty dict on failure."""
    p = _get_progress_file()
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {"completed": [], "kept": 0}


def _save_progress(progress: dict) -> None:
    _DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    _get_progress_file().write_text(json.dumps(progress, indent=2))


# ---------------------------------------------------------------------------
# Lint a draft already saved on disk (for lint-drafts command)
# ---------------------------------------------------------------------------

def lint_draft_dir(draft_dir: pathlib.Path) -> list[str]:
    """
    Read files from an on-disk draft directory and run lint_draft.
    Returns list of problem strings.
    """
    files: dict[str, str] = {}
    task_json_path = draft_dir / "task.json"
    if task_json_path.exists():
        files["task.json"] = task_json_path.read_text()
    for subdir in ("starter", "grader", "solution"):
        d = draft_dir / subdir
        if d.is_dir():
            for f in d.iterdir():
                if f.is_file():
                    files[f"{subdir}/{f.name}"] = f.read_text()
    return lint_draft(files)


def cmd_lint_drafts() -> None:
    """
    Lint every directory under drafts/accepted and drafts/too_easy.
    Prints PASS or the list of problems per draft. Read-only.
    """
    checked = 0
    failed = 0
    for base in (_ACCEPTED_DIR, _TOO_EASY_DIR):
        if not base.exists():
            continue
        for d in sorted(base.iterdir()):
            if not d.is_dir():
                continue
            problems = lint_draft_dir(d)
            if problems:
                print(f"FAIL  {d.name}")
                for p in problems:
                    print(f"      {p}")
                failed += 1
            else:
                print(f"PASS  {d.name}")
            checked += 1
    if checked == 0:
        print("No drafts found in drafts/accepted/ or drafts/too_easy/")
    else:
        print(f"\n{checked} draft(s) checked, {failed} with problems.")


# ---------------------------------------------------------------------------
# Single draft pipeline
# ---------------------------------------------------------------------------

def _run_factory_once(
    mock: bool,
    lessons: list[str],
    probe_attempts: int,
    mock_probe_fail: bool = False,
    draft_max_tokens: int = _DEFAULT_DRAFT_MAX_TOKENS,
    domain: str | None = None,
) -> dict:
    """Draft one task, lint, verify, review, probe. Returns a result record."""

    # 1. Draft ----------------------------------------------------------------
    retried_draft = False
    if mock:
        files = _mock_draft(domain=domain)
        fail_reason = ""
    else:
        files, retried_draft, fail_reason = _model_draft(
            lessons, domain=domain, max_tokens=draft_max_tokens
        )

    if fail_reason:
        with _SAVE_LOCK:
            stats = _load_stats()
            _ensure_draft_fail_reasons(stats)
            stats["drafted"] += 1
            stats["failed_draft_stage"] += 1
            bucket = fail_reason.split(":")[0].strip()
            if bucket not in _DRAFT_FAIL_REASONS:
                bucket = "other"
            stats["draft_fail_reasons"][bucket] += 1
            _save_stats(stats)
        return {"status": "error", "stage": "draft", "reason": fail_reason}

    if not files:
        # Empty files dict (no === blocks found)
        with _SAVE_LOCK:
            stats = _load_stats()
            _ensure_draft_fail_reasons(stats)
            stats["drafted"] += 1
            stats["failed_draft_stage"] += 1
            stats["draft_fail_reasons"]["empty_content"] += 1
            _save_stats(stats)
        return {"status": "error", "stage": "draft", "reason": "no file blocks in response"}

    # Embed domain into task.json tags if not already there
    if domain:
        try:
            meta = json.loads(files.get("task.json", "{}"))
            tags = meta.get("tags", [])
            if domain not in tags:
                tags = [domain] + [t for t in tags if t != domain]
                meta["tags"] = tags
            files["task.json"] = json.dumps(meta, indent=2)
        except Exception:
            pass

    # 2. Lint gate ─────────────────────────────────────────────────────────────
    lint_problems = lint_draft(files)
    if lint_problems:
        with _SAVE_LOCK:
            stats = _load_stats()
            _ensure_draft_fail_reasons(stats)
            stats["drafted"] += 1
            stats["lint_rejected"] += 1
            lfr = stats.setdefault("lint_fail_reasons", {r: 0 for r in _LINT_REASONS})
            seen_reasons: set[str] = set()
            for prob in lint_problems:
                r = _extract_lint_reason(prob)
                lfr[r] = lfr.get(r, 0) + 1
                if r not in seen_reasons:
                    seen_reasons.add(r)
                    lesson = _LINT_LESSONS.get(r, prob[:120])
                    _append_lesson(lesson)
            _save_stats(stats)
        return {
            "status": "rejected_lint",
            "stage": "lint",
            "problems": lint_problems,
            "reason": "; ".join(lint_problems[:2]),
        }

    # 3. Verify — uses a unique temp dir internally; no shared name
    tmp_task_id = "000-tmp-verify"
    verify_ok, verify_reason = _verify_draft_files(files, tmp_task_id)

    if not verify_ok:
        with _SAVE_LOCK:
            stats = _load_stats()
            _ensure_draft_fail_reasons(stats)
            stats["drafted"] += 1
            stats["failed_verify"] += 1
            _save_stats(stats)
        return {"status": "rejected_verify", "task_id": tmp_task_id, "reason": verify_reason}

    # 4. Staging: materialise + review + probe (all unlocked, run in parallel)
    staging_base = pathlib.Path(tempfile.mkdtemp())
    try:
        staging_dir = staging_base / "draft"
        _materialise_draft(files, staging_dir)

        # 5. Review -----------------------------------------------------------
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
                review = _model_review(staging_dir)
            except Exception as exc:
                review = {"verdict": "reject", "issues": [str(exc)], "summary": str(exc)}

        review["date"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if retried_draft:
            review["draft_retried"] = True
        if domain:
            review["domain"] = domain

        verdict = review.get("verdict", "reject")

        if verdict != "accept":
            # Judge rejected — do everything under the lock
            with _SAVE_LOCK:
                files, task_id = _assign_id(files)
                review["task_id"] = task_id
                _REJECTED_DIR.mkdir(parents=True, exist_ok=True)
                dest = _REJECTED_DIR / task_id
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(str(staging_dir), str(dest))
                (dest / "review.json").write_text(json.dumps(review, indent=2))
                reason = review.get("summary", "no reason given")
                _append_lesson(reason)
                stats = _load_stats()
                _ensure_draft_fail_reasons(stats)
                stats["drafted"] += 1
                stats["judge_rejected"] += 1
                if domain:
                    stats["drafts"][task_id] = {"domain": domain, "classification": "rejected"}
                _save_stats(stats)
            return {
                "status": "rejected_review",
                "task_id": task_id,
                "reason": reason,
                "issues": review.get("issues", []),
            }

        # Judge accepted — run probes outside the lock (they can be slow).
        # _probe_once uses its own unique temp dirs; no shared name.
        classification, probe_results = _probe_draft(
            files, probe_attempts, mock=mock, mock_probe_fail=mock_probe_fail
        )

        # 6. Save result under the lock ---------------------------------------
        with _SAVE_LOCK:
            files, task_id = _assign_id(files)
            review["task_id"] = task_id
            review["probe_results"] = probe_results

            if classification == "too_easy":
                _TOO_EASY_DIR.mkdir(parents=True, exist_ok=True)
                dest = _TOO_EASY_DIR / task_id
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(str(staging_dir), str(dest))
                review["classification"] = "too_easy"
                (dest / "review.json").write_text(json.dumps(review, indent=2))
                lesson = (
                    f"Task {task_id} was too easy: model solved all {probe_attempts} probes "
                    f"— full specification lets the model rewrite from scratch; "
                    f"shorten the prompt, add interacting constraints, or use a performance limit"
                )
                _append_lesson(lesson)
                stats = _load_stats()
                _ensure_draft_fail_reasons(stats)
                stats["drafted"] += 1
                stats["judge_accepted"] += 1
                stats["probed"] += 1
                stats["too_easy"] += 1
                stats["drafts"][task_id] = {
                    "classification": "too_easy",
                    "probe_results": probe_results,
                    "probe_solve_count": sum(probe_results),
                    "draft_retried": retried_draft,
                    "domain": domain,
                }
                _save_stats(stats)

            else:
                _ACCEPTED_DIR.mkdir(parents=True, exist_ok=True)
                dest = _ACCEPTED_DIR / task_id
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(str(staging_dir), str(dest))
                review["classification"] = "discriminating"
                (dest / "review.json").write_text(json.dumps(review, indent=2))
                stats = _load_stats()
                _ensure_draft_fail_reasons(stats)
                stats["drafted"] += 1
                stats["judge_accepted"] += 1
                stats["probed"] += 1
                stats["discriminating"] += 1
                stats["drafts"][task_id] = {
                    "classification": "discriminating",
                    "probe_results": probe_results,
                    "probe_solve_count": sum(probe_results),
                    "draft_retried": retried_draft,
                    "domain": domain,
                }
                _save_stats(stats)

        if classification == "too_easy":
            return {
                "status": "too_easy",
                "task_id": task_id,
                "probe_results": probe_results,
                "draft_dir": str(dest),
                "domain": domain,
            }
        return {
            "status": "accepted",
            "task_id": task_id,
            "probe_results": probe_results,
            "draft_dir": str(dest),
            "domain": domain,
        }
    finally:
        shutil.rmtree(str(staging_base), ignore_errors=True)


# ---------------------------------------------------------------------------
# CLI entry point (argparse)
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gradepack factory",
        description="Draft, verify, review, and probe new task candidates.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Draft pipeline: draft → lint → verify → judge review → probe → accepted/too_easy/rejected\n"
            "Accepted (discriminating) drafts go to drafts/accepted/.\n"
            "Promote with: python -m gradepack promote <draft-id>"
        ),
    )
    p.add_argument("--n",                type=int, default=1,
                   help="Number of drafts to attempt (default: 1)")
    p.add_argument("--target-kept",      type=int, default=None,
                   help="Stop when this many discriminating drafts are found")
    p.add_argument("--max-drafts",       type=int, default=None,
                   help="Hard cap on total drafts attempted (overrides --n if set)")
    p.add_argument("--probe-attempts",   type=int, default=3,
                   help="Times to probe each judge-accepted draft (default: 3)")
    p.add_argument("--parallel",         type=int, default=2,
                   help="Concurrent draft workers (default: 2)")
    p.add_argument("--draft-max-tokens", type=int, default=_DEFAULT_DRAFT_MAX_TOKENS,
                   help=f"max_tokens for draft API call (default: {_DEFAULT_DRAFT_MAX_TOKENS}); "
                        "retry doubles this (cap 32768)")
    p.add_argument("--mock",             action="store_true",
                   help="Use mock drafts (offline); mock probes always pass → too_easy")
    p.add_argument("--mock-probe-fail",  action="store_true",
                   help="Mock probes always fail → discriminating (for testing)")
    p.add_argument("--resume",           action="store_true",
                   help="Resume a stopped run using drafts/_progress.json")
    return p


def cmd_factory_argv(argv: list[str]) -> None:
    """Parse argv and run factory. Supports --help."""
    parser = build_parser()
    args = parser.parse_args(argv)

    n          = args.n
    target     = args.target_kept
    max_drafts = args.max_drafts if args.max_drafts is not None else n

    if target is not None and args.max_drafts is None:
        max_drafts = max(n, target * 5)

    cmd_factory(
        n=max_drafts,
        target_kept=target,
        probe_attempts=args.probe_attempts,
        parallel=args.parallel,
        draft_max_tokens=args.draft_max_tokens,
        mock=args.mock,
        mock_probe_fail=args.mock_probe_fail,
        resume=args.resume,
    )


def cmd_factory(
    n: int = 1,
    target_kept: int | None = None,
    probe_attempts: int = 3,
    parallel: int = 2,
    draft_max_tokens: int = _DEFAULT_DRAFT_MAX_TOKENS,
    mock: bool = False,
    mock_probe_fail: bool = False,
    resume: bool = False,
) -> None:
    for d in (_ACCEPTED_DIR, _REJECTED_DIR, _TOO_EASY_DIR):
        d.mkdir(parents=True, exist_ok=True)

    lessons = _load_last_lessons(10)

    # Resume: load progress and skip already-completed drafts
    progress = _load_progress() if resume else {"completed": [], "kept": 0}
    kept    = progress.get("kept", 0)
    drafted = 0

    print(
        f"gradepack factory: up to {n} draft(s), "
        f"probe_attempts={probe_attempts}, parallel={parallel}, "
        f"draft_max_tokens={draft_max_tokens}  [mock={mock}]"
    )
    if target_kept is not None:
        print(f"  Stopping when {target_kept} discriminating draft(s) found")
    if lessons:
        print(f"  Using {len(lessons)} lesson(s) from LESSONS.md")
    if resume and progress.get("completed"):
        print(f"  Resuming: {len(progress['completed'])} draft(s) already completed, kept={kept}")

    # Domain counter: start after any already-completed drafts
    global _domain_counter
    with _DOMAIN_COUNTER_LOCK:
        _domain_counter = len(progress.get("completed", []))

    def _one_draft(draft_index: int) -> dict:
        domain = _next_domain()
        return _run_factory_once(
            mock=mock,
            lessons=_load_last_lessons(10),
            probe_attempts=probe_attempts,
            mock_probe_fail=mock_probe_fail,
            draft_max_tokens=draft_max_tokens,
            domain=domain,
        )

    remaining = n - len(progress.get("completed", []))
    while remaining > 0:
        batch = min(remaining, parallel)
        with concurrent.futures.ThreadPoolExecutor(max_workers=batch) as pool:
            futures = [pool.submit(_one_draft, i) for i in range(batch)]
            for future in concurrent.futures.as_completed(futures):
                drafted += 1
                remaining -= 1
                try:
                    result = future.result()
                except Exception as exc:
                    result = {"status": "error", "stage": "unknown", "reason": str(exc)}

                status  = result.get("status", "error")
                task_id = result.get("task_id", "?")

                if status == "accepted":
                    kept += 1
                    probes = result.get("probe_results", [])
                    solved = sum(probes)
                    print(
                        f"  DISCRIMINATING  {task_id}  "
                        f"probe_solved={solved}/{len(probes)}"
                        + (f"  domain={result.get('domain','?')}" if result.get("domain") else "")
                    )
                    print(f"    Draft → {result['draft_dir']}")
                elif status == "too_easy":
                    probes = result.get("probe_results", [])
                    print(
                        f"  TOO EASY        {task_id}  "
                        f"probe_solved={len(probes)}/{len(probes)}  (all probes passed)"
                    )
                    print(f"    Draft → {result['draft_dir']}")
                    print(f"    Lesson appended to LESSONS.md")
                elif status == "rejected_review":
                    print(f"  REJECTED (judge) {task_id}")
                    print(f"    Reason: {result['reason']}")
                    print(f"    Lesson appended to LESSONS.md")
                elif status == "rejected_verify":
                    print(f"  REJECTED (verify) {task_id}")
                    print(f"    Reason: {result['reason']}")
                elif status == "rejected_lint":
                    print(f"  REJECTED (lint)")
                    for prob in result.get("problems", [])[:3]:
                        print(f"    {prob}")
                else:
                    print(f"  ERROR  stage={result.get('stage','?')}: {result.get('reason','?')}")

                # Update progress after each draft
                progress_entry = {
                    "status": status,
                    "task_id": task_id,
                }
                progress["completed"].append(progress_entry)
                progress["kept"] = kept
                with _SAVE_LOCK:
                    _save_progress(progress)

                if target_kept is not None and kept >= target_kept:
                    for f in futures:
                        f.cancel()
                    remaining = 0
                    break

    stats = _load_stats()
    _print_funnel(stats)
