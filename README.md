# gradepack

Installable registry of realistic software tasks with automated graders for testing AI coding agents.

Built during the Meta Global AI Developer Hackathon (Oct 26 to Nov 4, 2026).

---

## Install

```bash
pip install pytest mcp   # runtime dependencies
```

No build step. Run directly from the repo root:

```bash
cd gradepack
python -m gradepack <command>
```

---

## Commands

### `list` — show all tasks

```bash
python -m gradepack list
```

Prints every task ID with its title and difficulty.

---

### `verify <task-id>` — validate a task

```bash
python -m gradepack verify 001-pagination-off-by-one
```

Copies the task into a temp directory, runs the grader against the unmodified starter
(expects ≥ 1 failing test), then overlays `solution/` and runs the grader again (expects
all tests to pass). Prints `PASS` or `FAIL` with a reason.

---

### `run <task-id> --candidate <dir>` — grade a candidate solution

```bash
python -m gradepack run 001-pagination-off-by-one \
  --candidate tasks/001-pagination-off-by-one/solution
```

Copies the task, overlays the files from `<dir>` onto `starter/`, runs the grader,
and prints JSON:

```json
{
  "task_id": "001-pagination-off-by-one",
  "passed": 7,
  "failed": 0,
  "total": 7,
  "score": 1.0,
  "failing_tests": []
}
```

---

### `bench --model <name>` — benchmark a model on all tasks

```bash
# Mock run (uses solution files as the model response — no API call)
python -m gradepack bench --model mock --mock --attempts 1 --parallel 4

# Real run (requires BASE_URL, API_KEY, MODEL env vars)
BASE_URL=https://api.openai.com/v1 \
API_KEY=sk-... \
MODEL=gpt-4o-mini \
python -m gradepack bench --model gpt-4o-mini --attempts 3 --parallel 2
```

Flags:
- `--model <name>` — label for the results file (saved to `results/<name>.json`)
- `--attempts N` — number of attempts per task (default: 1)
- `--parallel M` — thread concurrency (default: 1)
- `--mock` — use solution files instead of calling a model
- `--mock-fail` — use starter files (simulates a fully broken model)

Environment variables (for real runs):
| Variable | Default |
|---|---|
| `BASE_URL` | `https://api.openai.com/v1` |
| `API_KEY` | *(required)* |
| `MODEL` | `gpt-4o-mini` |

---

### `review <task-id>` — judge task quality

```bash
# Mock review
python -m gradepack review 001-pagination-off-by-one --mock

# Real review (uses BASE_URL / API_KEY / MODEL)
python -m gradepack review 001-pagination-off-by-one
```

Sends the prompt, starter, grader, and solution to the model and records a structured
verdict (`fair`, `fully_specified`, `issues`, `summary`).

---

### `serve` — read-only HTTP API

```bash
python -m gradepack serve --port 8000
```

Endpoints (no solution files are ever exposed):
- `GET /tasks` — list all tasks
- `GET /tasks/<id>` — task detail with starter and grader file contents

---

### `mcp` — MCP server (stdio)

```bash
python -m gradepack mcp
```

Exposes three tools over the MCP stdio transport:
- `list_tasks` — list all task IDs
- `get_task(task_id)` — return prompt and starter files
- `run_candidate(task_id, files)` — grade a dict of filename → content

---

### `gen-registry` — regenerate index files

```bash
python -m gradepack gen-registry
```

Writes `tasks/index.json` and `llms.txt` from the current task set.

---

## Leaderboard

Open `docs/index.html` in a browser (served from the repo root, e.g. with
`python -m http.server` in `docs/`). It reads `results/*.json` with plain
JavaScript — no build step.

---

## Task format

Each task lives under `tasks/<id>/`:

```
tasks/<id>/
  task.json          id, title, language, difficulty, prompt, grader
  starter/           one or more .py files with a deliberate bug
  grader/            pytest tests (test_*.py); never edit these
  solution/          corrected files that make all tests pass
```

`task.json` fields:

| Field | Description |
|---|---|
| `id` | unique slug matching the directory name |
| `title` | short human-readable title |
| `language` | `python` |
| `difficulty` | `easy`, `medium`, or `hard` |
| `prompt` | full task description given to the agent; must describe everything the tests check |
| `grader` | `pytest` |

### Grader contract

- The grader's `sys.path.insert(0, '../starter')` loads from starter.
- Tests are never edited.
- The starter must fail ≥ 1 test; the solution must pass all tests.
- Grading uses the temp-copy approach: copy the task dir, overlay candidate files onto `starter/`, run pytest.
