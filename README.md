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

# Agentic mode: up to 3 turns; failed turns send back test names + pytest output
gradepack bench --model gpt-4o --agentic --max-turns 3 --attempts 1

# Agentic offline smoke test (fail turn 1, pass turn 2):
gradepack bench --model mock-agentic --mock-agentic --task 001-pagination-off-by-one

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
| `--agentic` | off | Enable multi-turn agentic mode |
| `--max-turns N` | 3 | Max turns per task in agentic mode |
| `--mock-agentic` | off | Agentic mock: fail turn 1, pass turn 2 (offline test) |
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

`raw_output_path` is stored relative to the repo root in all result files.

**Agentic mode** records additionally include: `agentic: true`, `turns_used`, `solved_at_turn` (null if not solved), `max_turns`. The summary printed after a run shows `pass@1` (turn 1 only), `solved-within-N-turns`, and average turns.

`failure_reason` values: `none` · `wrong_answer` · `test_failure_parametrized` · `invalid_output` · `no_answer` · `timeout` · `runner_error` · `api_error`

---

### Comparing several models

To compare models, run each with a different `--model` label and then view the leaderboard:

```bash
# Run three models
BASE_URL=... API_KEY=... MODEL=gpt-4o       gradepack bench --model gpt-4o       --attempts 3 --parallel 4 --publish
BASE_URL=... API_KEY=... MODEL=gpt-4o-mini  gradepack bench --model gpt-4o-mini  --attempts 3 --parallel 4 --publish
BASE_URL=... API_KEY=... MODEL=claude-3-5   gradepack bench --model claude-3-5   --attempts 3 --parallel 4 --publish

# Summarise all models
gradepack report

# Open the leaderboard
open docs/index.html
```

Each `results/<model>.json` is independent; `report` reads all JSON files and prints one section per model. The leaderboard at `docs/index.html` reads from `docs/results/index.json` and renders a sortable table.

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

### `factory [--help]`

```bash
# Help
gradepack factory --help

# Mock (offline) — probes always pass → too_easy drafts
gradepack factory --n 3 --mock

# Mock with probes failing → discriminating drafts
gradepack factory --n 3 --mock --mock-probe-fail

# Real run: keep drafting until 2 discriminating tasks found (cap 20 attempts)
BASE_URL=... API_KEY=... gradepack factory --target-kept 2 --max-drafts 20

# Real run: 5 parallel workers, 3 probe attempts each, 28k token draft budget
BASE_URL=... API_KEY=... gradepack factory --n 10 --parallel 5 --probe-attempts 3 --draft-max-tokens 28000
```

All flags:

| Flag | Default | Description |
|---|---|---|
| `--n N` | 1 | Total drafts to attempt |
| `--target-kept N` | off | Stop when N discriminating drafts found |
| `--max-drafts M` | same as `--n` | Hard cap on total attempts (overrides `--n` when `--target-kept` is set) |
| `--probe-attempts K` | 3 | Times to probe each judge-accepted draft |
| `--parallel P` | 2 | Concurrent draft workers |
| `--draft-max-tokens N` | 24000 | `max_tokens` for the draft API call; retry doubles this (cap 32768) |
| `--mock` | off | Use mock drafts (offline); mock probes always pass → too_easy |
| `--mock-probe-fail` | off | Mock probes always fail → discriminating (for offline testing) |

**Pipeline per draft:**
1. Reads the last 10 lessons from `LESSONS.md` (rejections *and* too-easy lessons).
2. Sends a drafting prompt with `--draft-max-tokens` tokens. If `finish_reason==length` and content is empty, retries **once** with `min(tokens×2, 32768)`. Records `draft_retried=true` per draft.
3. Parses the response robustly: strips markdown code fences from `task.json`, finds the largest top-level JSON object, and classifies failures as `empty_content` | `truncated_json` | `invalid_json`.
4. Runs `verify` on the draft locally (each call uses its own unique temp directory; parallel runs cannot collide).
5. Sends a **separate** review request (no shared history) → judge verdict.
6. **Probe stage**: runs the model against the draft `--probe-attempts` times (each probe uses its own unique temp directory).
   - All probes pass → `too_easy` → saved under `drafts/too_easy/`, lesson appended.
   - ≥ 1 probe fails → `discriminating` → saved under `drafts/accepted/`.
   - Judge rejected → saved under `drafts/rejected/`.
7. Writes `factory_stats.json` after each draft.
8. Prints a funnel summary at the end.

**Drafts are never promoted automatically.** Use `gradepack promote <id>` to move a discriminating draft into `tasks/`.

#### `factory_stats.json`

Written after each draft run with counts: `drafted`, `failed_draft_stage`, `failed_verify`, `judge_rejected`, `judge_accepted`, `probed`, `too_easy`, `discriminating`, plus:
- `draft_fail_reasons`: breakdown of draft-stage failures (`empty_content`, `truncated_json`, `invalid_json`, `other`)
- Per-draft entry: `probe_results`, `probe_solve_count`, `draft_retried`

---

### `promote <draft-id> [--help]`

```bash
gradepack promote 037-my-task
```

Moves a discriminating draft from `drafts/accepted/<id>/` into `tasks/<id>/`:
1. Verifies that `task.json`'s `id` matches the directory name.
2. Runs `verify` (starter must fail ≥ 1 test; solution must pass all). Refuses on failure.
3. Copies the draft into `tasks/<id>/`.
4. Moves `review.json` to `reviews/<id>.json`.
5. Removes the draft from `drafts/accepted/`.

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

### `doctor [--dry-run]`

```bash
gradepack doctor           # check env vars, make a tiny test request
gradepack doctor --dry-run # check env vars only, no network request
```

Prints `set` or `missing` for each env var (never the key value). Reports `status`, `finish_reason`, whether `content` or `reasoning_content` was returned, and warns if only `reasoning_content` is present (gradepack uses `content` only).

---

### `bench --dry-run`

```bash
gradepack bench --model gpt-4o --dry-run --task 001-pagination-off-by-one
```

Prints the first request body for one task with the API key redacted. Makes no API calls.

---

### `gen-registry [--site]`

```bash
gradepack gen-registry          # tasks/index.json + llms.txt
gradepack gen-registry --site   # also writes docs/api/ for GitHub Pages
```

---

## Results management

By default, each `bench` run **replaces** the previous `results/<model>.json` file (moving it to `results/history/<model>-<run_id>.json`, git-ignored). Use `--append` to accumulate records instead.

Every record includes a `run_id` (UTC timestamp) and `raw_output_path` (relative to the repo root).

```bash
gradepack bench --model gpt-4o --mock            # replaces previous results
gradepack bench --model gpt-4o --mock --append   # accumulates
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
gradepack factory --n N [--mock] [--probe-attempts K]
    │
    ├─ draft request  →  model  →  task.json + starter + grader + solution
    ├─ auto-assign id (next free NNN- number, never collides with tasks/ or drafts/)
    ├─ verify locally (starter must fail, solution must pass)
    ├─ review request  →  model (fresh, no shared history)  →  verdict
    │     ├─ REJECTED  → drafts/rejected/<id>/   + lesson → LESSONS.md
    │     └─ ACCEPTED  → probe stage
    ├─ probe K times against draft task
    │     ├─ all pass  → TOO EASY → drafts/too_easy/<id>/  + lesson → LESSONS.md
    │     └─ ≥1 fails  → DISCRIMINATING → drafts/accepted/<id>/
    │
    └─ factory_stats.json updated after every draft

gradepack promote <id>
    │
    ├─ verify (refuses if fails)
    ├─ move drafts/accepted/<id>/ → tasks/<id>/
    └─ move review.json → reviews/<id>.json
```
