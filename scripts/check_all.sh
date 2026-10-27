#!/usr/bin/env bash
# scripts/check_all.sh — run all quality checks and print a one-line summary.
#
# Usage:
#   cd gradepack          # run from the repo root
#   bash scripts/check_all.sh
#
# Exit code: 0 if everything passes, 1 if any step fails.

set -euo pipefail
cd "$(dirname "$0")/.."   # always run from repo root

PASS=0
FAIL=0
WARN=0
ERRORS=""

_step() {
    local label="$1"
    shift
    if "$@" > /tmp/check_step.log 2>&1; then
        echo "  OK    $label"
        PASS=$((PASS + 1))
    else
        echo "  FAIL  $label"
        cat /tmp/check_step.log | head -40
        FAIL=$((FAIL + 1))
        ERRORS="$ERRORS\n  FAIL: $label"
    fi
}

echo "=== gradepack check_all ==="
echo

# 1. Validate all tasks
_step "validate" python -m gradepack validate

# 2. Test suite
_step "pytest" python -m pytest tests/ -q --tb=short -p no:cacheprovider

# 3. Verify each task individually
echo "  Verifying tasks..."
VERIFY_PASS=0
VERIFY_FAIL=0
for task_dir in tasks/*/; do
    task_id=$(basename "$task_dir")
    if python -m gradepack verify "$task_id" > /tmp/verify_task.log 2>&1; then
        VERIFY_PASS=$((VERIFY_PASS + 1))
    else
        echo "    FAIL  verify $task_id"
        cat /tmp/verify_task.log
        VERIFY_FAIL=$((VERIFY_FAIL + 1))
        FAIL=$((FAIL + 1))
        ERRORS="$ERRORS\n  FAIL: verify $task_id"
    fi
done
if [ "$VERIFY_FAIL" -eq 0 ]; then
    echo "  OK    verify ($VERIFY_PASS tasks)"
    PASS=$((PASS + 1))
fi

# 4. Lint drafts (read-only, warnings only — never causes a failure)
echo "  Running lint-drafts..."
python -m gradepack lint-drafts > /tmp/lint_drafts.log 2>&1 || true
LINT_FAIL=$(grep -c "^FAIL" /tmp/lint_drafts.log 2>/dev/null || echo 0)
LINT_PASS=$(grep -c "^PASS" /tmp/lint_drafts.log 2>/dev/null || echo 0)
echo "  NOTE  lint-drafts: ${LINT_PASS} PASS, ${LINT_FAIL} FAIL (warnings only)"
if [ "$LINT_FAIL" -gt 0 ]; then
    WARN=$((WARN + 1))
fi

echo
echo "─────────────────────────────────────"
if [ "$FAIL" -eq 0 ]; then
    printf "SUMMARY: ALL PASS  (steps=%d, verify=%d tasks" "$PASS" "$VERIFY_PASS"
    [ "$WARN" -gt 0 ] && printf ", lint-warnings=%d" "$WARN"
    printf ")\n"
    exit 0
else
    printf "SUMMARY: FAIL  (pass=%d, fail=%d, warn=%d)\n" "$PASS" "$FAIL" "$WARN"
    printf "%b\n" "$ERRORS"
    exit 1
fi
