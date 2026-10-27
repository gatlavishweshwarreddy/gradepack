# gradepack

Installable registry of realistic software tasks with automated graders for testing AI coding agents.

Built during the Meta Global AI Developer Hackathon (Oct 26 to Nov 4, 2026).

---

## Built with

IBM Bob wrote the majority of the code in this repository — runner, tasks, CLI, bench, factory, server, MCP server, leaderboard, and CI. Task design, difficulty calibration, and review decisions are mine.

---

## Install

```bash
pip install pytest mcp   # runtime dependencies
pip install -e .         # install gradepack + console script
```

After install, the `gradepack` command is available directly:

```bash
gradepack list
gradepack verify 001-pagination-off-by-one
```

Or run without installing:

```bash
cd gradepack
python -m gradepack <command>
```

---

## Static API (GitHub Pages)

```
https://gatlavishweshwarreddy.github.io/gradepack/api/index.json
https://gatlavishweshwarreddy.github.io/gradepack/api/tasks/<id>.json
```

Regenerate with:

```bash
python -m gradepack gen-registry --site
```

---

## Commands

### `list`

```bash
gradepack list
```

Prints every task ID with title and difficulty.

---

### `verify <task-id>`

```bash
gradepack verify 001-pagination-off-by-one
```

Copies the task to a temp directory, runs the grader against the unmodified starter (expects ≥ 1 failing test), overlays `solution/`, reruns (expects all passing). Prints `PASS` or `FAIL`.

---

### `run <task-id> --candidate <dir>`

```bash
gradepack run 001-pagination-off-by-one \
  --candidate tasks/001-pagination-off-by-one/solution
```

Overlays `<dir>` onto the starter and grades it. JSON output:

```json
{
  "task_id": "001-pagination-off-by-one",
  "passed": 7, "failed": 0, "total": 7,
  "score": 1.0, "failing_tests": []
}
```

---

### `validate`

```bash
gradepack validate
```

Checks every task for required `task.json` fields (`version`, `tags`, `estimated_minutes`, `license`, etc.), matching id/directory, prompt length ≥ 200 chars, and existing starter/grader/solution directories.

---

### `bench --model <name>` — benchmark + publish

```bash
# Mock run (uses solution files, no API call)
gradepack bench --model mock --mock --attempts 2 --parallel 4

# Real run
BASE_URL=https://api.openai.com/v1 \
API_KEY=sk-... \
MODEL=gpt-4o-mini \
gradepack bench --model gpt-4o-mini --attempts 3 --parallel 2

# Publish results to docs/results/ (for GitHub Pages leaderboard)
gradepack bench --model gpt-4o-mini ... --publish
# Mock files are skipped unless --include-mock is added

# Help
gradepack bench --help
```

All flags:

| Flag | Default | Description |
|---|---|---|
| `--model` | *(required)* | Label for `results/<model>.json` |
| `--attempts N` | 1 | Attempts per task |
| `--parallel M` | 1 | Thread concurrency |
| `--mock` | off | Use solution files, no API call |
| `--mock-fail` | off | Use starter files (simulates broken model) |
| `--task <id>` | all | Restrict to one task (repeatable) |
| `--max-tokens N` | 8192 | API max_tokens |
| `--temperature F` | 0.7 | Sampling temperature |
| `--provider-label` | auto | Human-readable label stored in records |
| `--publish` | off | Copy results to `docs/results/` |
| `--include-mock` | off | Allow publishing mock result files |

Required env vars for real runs (`BASE_URL` and `API_KEY` have no defaults):

| Variable | Description |
|---|---|
| `BASE_URL` | Chat completions endpoint base URL |
| `API_KEY` | API key (never logged) |
| `MODEL` | Model name (default: `meta-models/muse-spark-open-1026`) |

Records per attempt: `provider`, `model`, `date`, `elapsed_s`, `finish_reason`, `failure_reason`, `token_usage`, `raw_output_path`. Computes `pass@1` and `pass@k`. Retries HTTP 429/5xx with exponential backoff (max 4 tries). File names from model responses are normalised (leading `starter/` stripped) before the integrity check.

`failure_reason` values: `none` · `wrong_answer` · `test_failure_parametrized` · `invalid_output` · `no_answer` · `timeout` · `runner_error` · `api_error`

---

### `review <task-id>`

```bash
gradepack review 001-pagination-off-by-one --mock
```

Sends the task to the model for a fairness/specification review. Returns JSON with `verdict`, `fair`, `fully_specified`, `issues`, `summary`.

---

### `report [--model <name>]`

```bash
gradepack report              # all models
gradepack report --model mock
```

Prints a plain-text table per model: `pass@1`, `pass@k`, breakdown by difficulty, failure reason counts, and the five hardest tasks.

---

### `demo <task-id> [--mock]`

```bash
gradepack demo 001-pagination-off-by-one --mock   # offline, uses solution
gradepack demo 001-pagination-off-by-one           # real model call
```

Prints the task prompt, the failing starter tests, the model's response, and the graded result. Designed for screen recordings and demos.

---

### `factory --n N`

```bash
# Mock (offline)
gradepack factory --n 3 --mock

# Real
BASE_URL=... API_KEY=... gradepack factory --n 5
```

For each of N task ideas:
1. Sends a drafting prompt (includes the last 10 lessons from `LESSONS.md`).
2. Runs `verify` on the draft.
3. Sends a **separate** review request (no shared history).
4. Records `accepted` or `rejected` with the reason in `drafts/<id>/review.json`.
5. Appends rejection reasons as lessons to `LESSONS.md`.

**Accepted drafts stay in `drafts/` until you manually move them into `tasks/`.** They are never published automatically.

---

### `serve [--port N]`

```bash
gradepack serve --port 8000
```

Read-only HTTP API (no solution files exposed):

- `GET /tasks` — list all tasks
- `GET /tasks/<id>` — task detail with starter and grader files

---

### `mcp`

```bash
gradepack mcp
```

MCP stdio server with three tools: `list_tasks`, `get_task(task_id)`, `run_candidate(task_id, files)`.

---

### `gen-registry [--site]`

```bash
gradepack gen-registry          # tasks/index.json + llms.txt
gradepack gen-registry --site   # also writes docs/api/ for GitHub Pages
```

---

## Task format

```
tasks/<id>/
  task.json          metadata (see fields below)
  starter/           one or more .py files with a deliberate bug
  grader/            pytest tests (test_*.py); never edit these
  solution/          corrected files that make all tests pass
```

`task.json` fields:

| Field | Type | Description |
|---|---|---|
| `id` | string | unique slug matching directory name |
| `title` | string | short human-readable title |
| `language` | string | `"python"` |
| `difficulty` | string | `"easy"`, `"medium"`, or `"hard"` |
| `prompt` | string | full description (≥ 200 chars); must cover everything the tests check |
| `grader` | string | `"pytest"` |
| `version` | string | e.g. `"1.0"` |
| `tags` | list | topic tags, e.g. `["datetime", "timezone"]` |
| `estimated_minutes` | int | rough time for a competent developer |
| `license` | string | `"MIT"` |

### Grader contract

- The grader inserts `../starter` into `sys.path` and imports from there.
- Tests are never edited.
- Starter must fail ≥ 1 test; solution must pass all.
- Grading uses the temp-copy approach: copy task dir, overlay candidate files onto `starter/`, run pytest.
- Candidate filenames are validated: path separators, `..`, and `conftest.py` are all rejected.

### Factory flow

```
gradepack factory --n N [--mock]
    │
    ├─ draft request  →  model  →  task.json + starter + grader + solution
    ├─ verify locally (starter must fail, solution must pass)
    ├─ review request  →  model (fresh, no shared history)  →  verdict
    │
    ├─ ACCEPTED → drafts/<id>/  (manual review required before moving to tasks/)
    └─ REJECTED → lesson appended to LESSONS.md → included in next draft prompt
```
