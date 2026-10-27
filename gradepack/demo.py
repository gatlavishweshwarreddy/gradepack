"""
gradepack demo — interactive task walkthrough for screen recordings.

Usage:
    python -m gradepack demo <task-id> [--mock]
"""
import json
import shutil

from gradepack import api as _api
from gradepack import bench as _bench
from gradepack import core


_SEP = "─" * 60


def cmd_demo(task_id: str, mock: bool = False) -> None:
    task_root = core.task_dir(task_id)
    if not task_root.exists():
        print(f"ERROR: task '{task_id}' not found")
        return

    meta = core.load_task_json(task_id)

    # ── 1. Print the prompt ────────────────────────────────────────────
    print(_SEP)
    print(f"  TASK  {task_id}")
    print(f"  {meta.get('difficulty','?').upper()}  |  {meta.get('title','')}")
    print(_SEP)
    print()
    print("PROMPT")
    print(meta.get("prompt", ""))
    print()

    # ── 2. Run grader against unmodified starter ───────────────────────
    tmp_task = core.make_temp_copy(task_id)
    tmp_parent = tmp_task.parent
    try:
        starter_result = core.run_pytest(tmp_task / "grader")
    finally:
        shutil.rmtree(tmp_parent, ignore_errors=True)

    print(_SEP)
    print("STARTER FAILURES")
    if starter_result["failures"]:
        for f in starter_result["failures"]:
            print(f"  ✗  {f}")
    else:
        print("  (none — starter already passes all tests)")
    print()

    # ── 3. Get model response ──────────────────────────────────────────
    starter_dir = task_root / "starter"
    starter_files = {
        p.name: p.read_text()
        for p in starter_dir.iterdir()
        if p.is_file() and p.suffix == ".py"
    }
    allowed = set(starter_files)

    if mock:
        candidate_files = _bench._mock_fixed_files(task_id)
        raw_response = "[mock — solution files used]"
        finish_reason = "stop"
    else:
        prompt = meta.get("prompt", "")
        user_msg = _api.build_coding_prompt(prompt, starter_files)
        print(_SEP)
        print("CALLING MODEL…")
        print()
        try:
            resp_data = _api.chat(
                _api._SYSTEM_CODING,
                user_msg,
                temperature=0.7,
                max_tokens=8192,
                timeout=180,
            )
            raw_response  = _api.extract_content(resp_data)
            finish_reason = _api.extract_finish_reason(resp_data)
            candidate_files = _api.parse_coding_response(raw_response, allowed)
        except Exception as exc:
            print(f"  ERROR: {exc}")
            return

    # ── 4. Print model output ──────────────────────────────────────────
    print(_SEP)
    print(f"MODEL OUTPUT  (finish_reason={finish_reason})")
    print()
    if candidate_files:
        for fname, content in candidate_files.items():
            print(f"── {fname} " + "─" * max(0, 50 - len(fname)))
            for line in content.splitlines()[:40]:
                print(f"  {line}")
            if len(content.splitlines()) > 40:
                print(f"  … ({len(content.splitlines()) - 40} more lines)")
            print()
    else:
        print("  (no parseable files in response)")
        print()
        print("  RAW (first 400 chars):")
        print("  " + raw_response[:400].replace("\n", "\n  "))
        print()

    # ── 5. Grade and print result ──────────────────────────────────────
    had_candidate = bool(candidate_files)
    tmp_task2 = core.make_temp_copy(task_id)
    tmp_parent2 = tmp_task2.parent
    error_msg = None
    try:
        if had_candidate:
            try:
                core.overlay_dict(candidate_files, tmp_task2 / "starter")
            except core.CandidateError as exc:
                error_msg = str(exc)
                had_candidate = False
        result = core.run_pytest(tmp_task2 / "grader")
    finally:
        shutil.rmtree(tmp_parent2, ignore_errors=True)

    if not had_candidate or error_msg:
        score = 0.0
        passed = 0
    else:
        total = result["total"]
        passed = result["passed"]
        score = round(passed / total, 4) if total else 0.0

    reason = _bench._categorise(result, error_msg, finish_reason, had_candidate)

    print(_SEP)
    print("RESULT")
    print(f"  score:          {score:.0%}")
    print(f"  passed:         {passed}/{result.get('total', 0)}")
    print(f"  failure_reason: {reason}")
    if result.get("failures"):
        print("  failing tests:")
        for f in result["failures"]:
            print(f"    ✗  {f}")
    if error_msg:
        print(f"  error: {error_msg}")
    print(_SEP)
    print()
