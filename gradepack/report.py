"""
gradepack report — print a plain-text summary table per model.

Usage:
    python -m gradepack report [--model <name>]
"""
import json
import pathlib
from collections import Counter

from gradepack import bench as _bench
from gradepack import core


def _load_results(model_name: str) -> list[dict]:
    p = core._repo_root() / "results" / f"{model_name}.json"
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return []


def _print_model_report(model_name: str, records: list[dict]) -> None:
    if not records:
        print(f"\n[{model_name}] no records found")
        return

    task_index = {t["id"]: t for t in _load_task_meta()}
    attempts = max((r.get("attempt", 1) for r in records), default=1)
    p1 = _bench.compute_pass_at_k(records, k=1)
    pk = _bench.compute_pass_at_k(records, k=attempts)
    avg_p1 = sum(p1.values()) / len(p1) if p1 else 0.0
    avg_pk = sum(pk.values()) / len(pk) if pk else 0.0

    # Difficulty breakdown
    diff_p1: dict[str, list[float]] = {}
    for tid, score in p1.items():
        diff = task_index.get(tid, {}).get("difficulty", "unknown")
        diff_p1.setdefault(diff, []).append(score)
    diff_summary = {d: sum(v) / len(v) for d, v in diff_p1.items()}

    # Failure reason counts
    reason_counts: Counter = Counter(r.get("failure_reason", "unknown") for r in records)

    # Five hardest tasks (lowest pass@1)
    hardest = sorted(
        [(tid, s) for tid, s in p1.items()],
        key=lambda x: x[1]
    )[:5]

    width = 60
    print()
    print("=" * width)
    print(f"  Model: {model_name}")
    print("=" * width)
    print(f"  pass@1 (avg): {avg_p1:.1%}   pass@{attempts} (avg): {avg_pk:.1%}")
    print(f"  Tasks: {len(p1)}   Attempts per task: {attempts}")

    print()
    print("  By difficulty:")
    for diff in ("easy", "medium", "hard", "unknown"):
        if diff in diff_summary:
            print(f"    {diff:8s}  {diff_summary[diff]:.1%}")

    print()
    print("  Failure reasons:")
    for reason, count in sorted(reason_counts.items(), key=lambda x: -x[1]):
        print(f"    {reason:32s}  {count}")

    print()
    print("  Five hardest tasks (lowest pass@1):")
    for tid, score in hardest:
        print(f"    {score:.0%}  {tid}")
    print("=" * width)


def _load_task_meta() -> list[dict]:
    idx = core.tasks_dir() / "index.json"
    if idx.exists():
        try:
            return json.loads(idx.read_text())
        except json.JSONDecodeError:
            pass
    return [{"id": tid, "difficulty": "unknown"} for tid in core.all_task_ids()]


def cmd_report(model_filter: str | None = None) -> None:
    results_dir = core._repo_root() / "results"
    if not results_dir.exists():
        print("No results/ directory found.")
        return

    if model_filter:
        names = [model_filter]
    else:
        names = [p.stem for p in sorted(results_dir.glob("*.json"))]

    if not names:
        print("No result files found in results/.")
        return

    for name in names:
        records = _load_results(name)
        _print_model_report(name, records)
