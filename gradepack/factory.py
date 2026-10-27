"""
gradepack factory — draft and review new tasks using a model.

Usage (--help for full options):
    python -m gradepack factory --help
    python -m gradepack factory --n 3 --mock
    python -m gradepack factory --target-kept 2 --max-drafts 10 --mock

Pipeline per draft:
  1. Reads the last 10 lessons from LESSONS.md (including too-easy lessons).
  2. Sends a drafting prompt to the model (one call per task idea).
  3. Parses the response into task.json, starter/<file>, grader/<file>, solution/<file>.
  4. Runs verify on the draft.
  5. Sends a separate review prompt to the model (fresh request, no shared history).
  6. Records verdict + reason in drafts/<category>/<id>/review.json.
  7. Probe stage: runs the model against the draft --probe-attempts times.
     - All probes pass  → "too_easy" → saved under drafts/too_easy/  + lesson appended
     - ≥1 probe fails   → "discriminating" → saved under drafts/accepted/
     - Judge rejected   → saved under drafts/rejected/
  8. Writes factory_stats.json after each draft.

Accepted (discriminating) drafts stay in drafts/accepted/ until promoted via:
    python -m gradepack promote <draft-id>

Mock mode works fully offline. --parallel N drafts concurrently (default 2).
"""
import argparse
import concurrent.futures
import datetime
import json
import pathlib
import re
import shutil
import sys
import tempfile

from gradepack import api as _api
from gradepack import core

import threading as _threading

_REPO = core._repo_root()
_DRAFTS_DIR      = _REPO / "drafts"
_ACCEPTED_DIR    = _DRAFTS_DIR / "accepted"
_REJECTED_DIR    = _DRAFTS_DIR / "rejected"
_TOO_EASY_DIR    = _DRAFTS_DIR / "too_easy"
_LESSONS_FILE    = _REPO / "LESSONS.md"
_STATS_FILE      = _REPO / "factory_stats.json"
_DEFAULT_MODEL   = _api._DEFAULT_MODEL

# Protects the final save step (assign id + copytree + stats update)
# so parallel workers don't race on numbering or stat writes.
_SAVE_LOCK = _threading.Lock()

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


def _assign_id(files: dict[str, str]) -> dict[str, str]:
    """
    Rewrite the id in task.json to use the next free numeric prefix.
    The slug part (everything after NNN-) is kept; if no slug, uses 'task'.
    Returns a modified copy of files.
    """
    task_json_text = files.get("task.json", "{}")
    try:
        meta = json.loads(task_json_text)
    except Exception:
        meta = {}

    old_id = meta.get("id", "")
    # Extract slug part: strip any leading NNN- prefix
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


def _mock_draft() -> dict:
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

Guidance for making hard, discriminating tasks that a model cannot easily solve:
- Do NOT enumerate the expected behaviour exhaustively in the prompt; keep the prompt
  shorter than the code, so the model must read the code to understand the contract
- Require reading several files or tracing multiple interacting code paths
- Use interacting constraints (two bugs that each look innocent but combine wrongly)
- Include deterministic concurrency, state-machine, or ordering invariants
- Use operation-count or asymptotic performance limits (the grader instruments calls)
- Do NOT list every test case in the prompt — the model should not be able to rewrite
  from scratch using only the prompt
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


def _chat(system: str, user: str) -> str:
    resp_data = _api.chat(system, user, temperature=0.7, max_tokens=16384, timeout=180)
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
        f"Lessons from previous drafts (avoid these mistakes):\n{lesson_text}"
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
        p = pathlib.PurePosixPath(path_str)
        dest = draft_root
        for part in p.parts:
            dest = dest / part
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)

    return None


# ---------------------------------------------------------------------------
# Verify helper (reusable)
# ---------------------------------------------------------------------------

def _verify_draft_files(files: dict[str, str], task_id: str) -> tuple[bool, str]:
    """
    Materialise files to a temp dir, run verify.
    Returns (ok, reason).
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        tmp_task = tmp_path / task_id
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
            shutil.rmtree(tmp2, ignore_errors=True)


# ---------------------------------------------------------------------------
# Probe stage
# ---------------------------------------------------------------------------

def _probe_once(files: dict[str, str], task_id: str, mock: bool) -> bool:
    """
    Run the model once against this draft task (one-shot, same logic as bench).
    Returns True if the model solves it, False otherwise.
    In mock mode, always returns True (simulate an easy task for testing).
    mock_fail mode returns False.
    """
    if mock:
        # mock=True means simulate the probe always passing (too easy)
        return True

    # Write draft to a temp location so bench can run against it
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        tmp_task = tmp_path / task_id
        err = _materialise_draft(files, tmp_task)
        if err:
            return False

        meta_text = files.get("task.json", "{}")
        try:
            meta = json.loads(meta_text)
        except Exception:
            meta = {}
        prompt = meta.get("prompt", "")

        starter_dir = tmp_task / "starter"
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

        # Run grader in a separate temp copy
        tmp3 = pathlib.Path(tempfile.mkdtemp())
        try:
            shutil.copytree(str(tmp_task), str(tmp3 / task_id))
            task_copy = tmp3 / task_id
            try:
                core.overlay_dict(candidate_files, task_copy / "starter")
            except core.CandidateError:
                return False
            result = core.run_pytest(task_copy / "grader")
            return result["failed"] == 0 and result["total"] > 0
        finally:
            shutil.rmtree(tmp3, ignore_errors=True)


def _probe_draft(
    files: dict[str, str],
    task_id: str,
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
            solved = _probe_once(files, task_id, mock=mock)
        probe_results.append(solved)

    # Discriminating = at least one probe failed
    classification = "too_easy" if all(probe_results) else "discriminating"
    return classification, probe_results


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def _load_stats() -> dict:
    if _STATS_FILE.exists():
        try:
            return json.loads(_STATS_FILE.read_text())
        except Exception:
            pass
    return {
        "drafted": 0,
        "failed_draft_stage": 0,
        "failed_verify": 0,
        "judge_rejected": 0,
        "judge_accepted": 0,
        "probed": 0,
        "too_easy": 0,
        "discriminating": 0,
        "drafts": {},
    }


def _save_stats(stats: dict) -> None:
    _STATS_FILE.write_text(json.dumps(stats, indent=2))


def _print_funnel(stats: dict) -> None:
    print("\n── Factory funnel ──────────────────────────────")
    print(f"  drafted            : {stats['drafted']}")
    print(f"  failed draft stage : {stats['failed_draft_stage']}")
    print(f"  failed verify      : {stats['failed_verify']}")
    print(f"  judge rejected     : {stats['judge_rejected']}")
    print(f"  judge accepted     : {stats['judge_accepted']}")
    print(f"  probed             : {stats['probed']}")
    print(f"  too easy           : {stats['too_easy']}")
    print(f"  discriminating     : {stats['discriminating']}")
    print("────────────────────────────────────────────────")


# ---------------------------------------------------------------------------
# Single draft pipeline
# ---------------------------------------------------------------------------

def _run_factory_once(
    mock: bool,
    lessons: list[str],
    probe_attempts: int,
    mock_probe_fail: bool = False,
) -> dict:
    """Draft one task, verify, review, probe. Returns a result record."""

    # 1. Draft ----------------------------------------------------------------
    if mock:
        files = _mock_draft()
    else:
        try:
            files = _model_draft(lessons)
        except Exception as exc:
            with _SAVE_LOCK:
                stats = _load_stats()
                stats["failed_draft_stage"] += 1
                stats["drafted"] += 1
                _save_stats(stats)
            return {"status": "error", "stage": "draft", "reason": str(exc)}

    # 2. Verify (before assigning a real id — just check the structure) -------
    # Use a temporary slug for the verify step; real id assigned under lock below.
    tmp_task_id = "000-tmp-verify"
    verify_ok, verify_reason = _verify_draft_files(files, tmp_task_id)

    if not verify_ok:
        with _SAVE_LOCK:
            stats = _load_stats()
            stats["drafted"] += 1
            stats["failed_verify"] += 1
            _save_stats(stats)
        return {"status": "rejected_verify", "task_id": tmp_task_id, "reason": verify_reason}

    # 4. Save to a staging temp dir for review --------------------------------
    # 4. Staging: materialise + review + probe (all unlocked, can run in parallel)
    with tempfile.TemporaryDirectory() as staging_tmp:
        staging_dir = pathlib.Path(staging_tmp) / "draft"
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

        review["date"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

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
                stats["drafted"] += 1
                stats["judge_rejected"] += 1
                _save_stats(stats)
            return {
                "status": "rejected_review",
                "task_id": task_id,
                "reason": reason,
                "issues": review.get("issues", []),
            }

        # Judge accepted — run probes outside the lock (they can be slow)
        # Use a placeholder id for probe; real id assigned under lock when saving.
        probe_task_id = "000-probe-tmp"
        classification, probe_results = _probe_draft(
            files, probe_task_id, probe_attempts, mock=mock, mock_probe_fail=mock_probe_fail
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
                stats["drafted"] += 1
                stats["judge_accepted"] += 1
                stats["probed"] += 1
                stats["too_easy"] += 1
                stats["drafts"][task_id] = {
                    "classification": "too_easy",
                    "probe_results": probe_results,
                    "probe_solve_count": sum(probe_results),
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
                stats["drafted"] += 1
                stats["judge_accepted"] += 1
                stats["probed"] += 1
                stats["discriminating"] += 1
                stats["drafts"][task_id] = {
                    "classification": "discriminating",
                    "probe_results": probe_results,
                    "probe_solve_count": sum(probe_results),
                }
                _save_stats(stats)

        if classification == "too_easy":
            return {
                "status": "too_easy",
                "task_id": task_id,
                "probe_results": probe_results,
                "draft_dir": str(dest),
            }
        return {
            "status": "accepted",
            "task_id": task_id,
            "probe_results": probe_results,
            "draft_dir": str(dest),
        }


# ---------------------------------------------------------------------------
# CLI entry point (argparse)
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gradepack factory",
        description="Draft, verify, review, and probe new task candidates.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Draft pipeline: draft → verify → judge review → probe → accepted/too_easy/rejected\n"
            "Accepted (discriminating) drafts go to drafts/accepted/.\n"
            "Promote with: python -m gradepack promote <draft-id>"
        ),
    )
    p.add_argument("--n",              type=int, default=1,
                   help="Number of drafts to attempt (default: 1)")
    p.add_argument("--target-kept",    type=int, default=None,
                   help="Stop when this many discriminating drafts are found")
    p.add_argument("--max-drafts",     type=int, default=None,
                   help="Hard cap on total drafts attempted (overrides --n if set)")
    p.add_argument("--probe-attempts", type=int, default=3,
                   help="Times to probe each judge-accepted draft (default: 3)")
    p.add_argument("--parallel",       type=int, default=2,
                   help="Concurrent draft workers (default: 2)")
    p.add_argument("--mock",           action="store_true",
                   help="Use mock drafts (offline); mock probes always pass → too_easy")
    p.add_argument("--mock-probe-fail", action="store_true",
                   help="Mock probes always fail → discriminating (for testing)")
    return p


def cmd_factory_argv(argv: list[str]) -> None:
    """Parse argv and run factory. Supports --help."""
    parser = build_parser()
    args = parser.parse_args(argv)

    n          = args.n
    target     = args.target_kept
    max_drafts = args.max_drafts if args.max_drafts is not None else n

    # --target-kept overrides --n: keep drafting until target met
    if target is not None and args.max_drafts is None:
        max_drafts = max(n, target * 5)  # reasonable upper bound

    cmd_factory(
        n=max_drafts,
        target_kept=target,
        probe_attempts=args.probe_attempts,
        parallel=args.parallel,
        mock=args.mock,
        mock_probe_fail=args.mock_probe_fail,
    )


def cmd_factory(
    n: int = 1,
    target_kept: int | None = None,
    probe_attempts: int = 3,
    parallel: int = 2,
    mock: bool = False,
    mock_probe_fail: bool = False,
) -> None:
    for d in (_ACCEPTED_DIR, _REJECTED_DIR, _TOO_EASY_DIR):
        d.mkdir(parents=True, exist_ok=True)

    lessons = _load_last_lessons(10)
    kept    = 0
    drafted = 0

    print(
        f"gradepack factory: up to {n} draft(s), "
        f"probe_attempts={probe_attempts}, parallel={parallel}  [mock={mock}]"
    )
    if target_kept is not None:
        print(f"  Stopping when {target_kept} discriminating draft(s) found")
    if lessons:
        print(f"  Using {len(lessons)} lesson(s) from LESSONS.md")

    def _one_draft(_: int) -> dict:
        return _run_factory_once(
            mock=mock,
            lessons=_load_last_lessons(10),  # re-read so parallel workers see updates
            probe_attempts=probe_attempts,
            mock_probe_fail=mock_probe_fail,
        )

    # Submit drafts in batches of `parallel`; stop early if target_kept met
    remaining = n
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
                else:
                    print(f"  ERROR  stage={result.get('stage','?')}: {result.get('reason','?')}")

                if target_kept is not None and kept >= target_kept:
                    # Cancel remaining futures in this batch
                    for f in futures:
                        f.cancel()
                    remaining = 0
                    break

    stats = _load_stats()
    _print_funnel(stats)
