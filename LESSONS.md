# LESSONS.md

Lessons learned from rejected task drafts. The most recent 10 lessons are
automatically included in the next drafting prompt.

<!-- lessons below — managed by `python -m gradepack factory` -->

- Starter leaks bug locations and grader misses key invariants (RUNNING non-cancellable, token cap, FAILED) allowing spec-violating solution to pass.
- Task 040-throttled-workflow-engine was too easy: model solved all 3 probes — full specification lets the model rewrite from scratch; shorten the prompt, add interacting constraints, or use a performance limit.
- Well-designed invariants and comprehensive grader, but starter leaks solutions via BUG annotations and performance requirement is enforced via undocumented instrumentation.
- Do not access private attributes of the object under test unless they are named in the prompt or starter docstrings.
- Never put BUG/FIXME/TODO fix/intentionally/wrong/should be comments or strings in the starter — they reveal the bug location.
- Do not access private attributes of the object under test unless they are named in the prompt or starter docstrings.
- Never put BUG/FIXME/TODO fix/intentionally/wrong/should be comments or strings in the starter — they reveal the bug location.
- Do not access private attributes of the object under test unless they are named in the prompt or starter docstrings.
- Task title must be at least 8 characters long.
- Include at least 6 test functions in the grader for adequate coverage.
- Task 049-crypto-utils-fix was too easy: model solved all 3 probes — full specification lets the model rewrite from scratch; shorten the prompt, add interacting constraints, or use a performance limit.
- Do not access private attributes of the object under test unless they are named in the prompt or starter docstrings.
- Include at least 6 test functions in the grader for adequate coverage.
- Include at least 6 test functions in the grader for adequate coverage.
- Include at least 6 test functions in the grader for adequate coverage.