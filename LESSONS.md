# LESSONS.md

Lessons learned from rejected task drafts. The most recent 10 lessons are
automatically included in the next drafting prompt.

<!-- lessons below — managed by `python -m gradepack factory` -->

- Starter leaks bug locations and grader misses key invariants (RUNNING non-cancellable, token cap, FAILED) allowing spec-violating solution to pass.
- Task 040-throttled-workflow-engine was too easy: model solved all 3 probes — full specification lets the model rewrite from scratch; shorten the prompt, add interacting constraints, or use a performance limit.