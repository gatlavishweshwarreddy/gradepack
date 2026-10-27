"""
gradepack.api — shared HTTP client for chat completions with retry logic.

Used by bench, judge, and factory. Never makes real calls in mock mode.
Never logs API keys.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

_DEFAULT_MODEL = "meta-models/muse-spark-open-1026"
_MAX_TRIES = 4
_RETRY_STATUSES = {429, 500, 502, 503, 504}


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------

def get_env_or_fail(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        print(f"ERROR: environment variable {key!r} is not set.", file=sys.stderr)
        sys.exit(1)
    return val


def get_model() -> str:
    return os.environ.get("MODEL", _DEFAULT_MODEL)


# ---------------------------------------------------------------------------
# Retry-aware HTTP POST to chat completions
# ---------------------------------------------------------------------------

def chat(
    system: str,
    user: str,
    *,
    temperature: float = 0.7,
    max_tokens: int = 8192,
    timeout: int = 180,
) -> dict:
    """
    POST to BASE_URL/chat/completions with retry on 429/5xx.

    Returns the full API response dict.
    Raises RuntimeError on exhausted retries or non-retriable errors.
    Never logs the API key.
    """
    base_url = get_env_or_fail("BASE_URL")
    api_key  = get_env_or_fail("API_KEY")
    model    = get_model()

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "temperature": temperature,
        "max_tokens":  max_tokens,
    }).encode()

    url = f"{base_url.rstrip('/')}/chat/completions"
    delay = 2.0
    last_exc: Exception | None = None

    for attempt in range(1, _MAX_TRIES + 1):
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type":  "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code in _RETRY_STATUSES and attempt < _MAX_TRIES:
                time.sleep(delay)
                delay *= 2
                continue
            raise RuntimeError(f"HTTP {exc.code} from API: {exc.reason}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            last_exc = exc
            if attempt < _MAX_TRIES:
                time.sleep(delay)
                delay *= 2
                continue
            raise RuntimeError(f"Request failed after {_MAX_TRIES} tries: {exc}") from exc

    raise RuntimeError(f"Exhausted retries: {last_exc}")


def extract_content(data: dict) -> str:
    """
    Extract the assistant text from a chat completions response.
    Uses 'content' only — never 'reasoning_content'.
    Returns empty string if content is missing or None.
    """
    choices = data.get("choices", [])
    if not choices:
        return ""
    msg = choices[0].get("message", {})
    return msg.get("content") or ""


def extract_finish_reason(data: dict) -> str:
    choices = data.get("choices", [])
    if not choices:
        return ""
    return choices[0].get("finish_reason", "")


def extract_usage(data: dict) -> dict | None:
    return data.get("usage")


# ---------------------------------------------------------------------------
# Response format: fenced code blocks with bare filename label
# ---------------------------------------------------------------------------

_SYSTEM_CODING = """\
You are a Python debugging assistant.
You will be given a task description and one or more buggy Python source files.

Reply with ONLY the corrected file(s). Use this format for each file — \
the filename on a line by itself before the fence, bare name only (e.g. paginate.py), \
no directory prefix:

paginate.py
```python
<full corrected file content>
```

Repeat the block for each file that needs changing. No other prose."""

_SYSTEM_CODING_LEGACY = """\
You are a Python debugging assistant.
You will be given a task description and one or more buggy Python source files.

Reply with ONLY the corrected file(s) in this format:

=== paginate.py ===
<full corrected file content>

Use bare file names only — no 'starter/' prefix, no directory separators.
Repeat the block for each file that needs changing. No other prose."""


def build_coding_prompt(task_prompt: str, starter_files: dict[str, str]) -> str:
    """Build the user message for a coding task."""
    file_block = "\n\n".join(
        f"{name}\n```python\n{content}\n```"
        for name, content in starter_files.items()
    )
    return f"{task_prompt}\n\n{file_block}"


def normalise_filename(raw_name: str, allowed: set[str]) -> str | None:
    """
    Strip leading 'starter/', './', or any directory component.
    Return the basename if it is in `allowed`, else None.
    """
    # Remove common prefixes
    name = raw_name.strip()
    for prefix in ("starter/", "./starter/", "./"):
        if name.startswith(prefix):
            name = name[len(prefix):]
    # Take only the final path component
    name = name.replace("\\", "/").split("/")[-1]
    return name if name in allowed else None


def parse_coding_response(content: str, allowed: set[str]) -> dict[str, str]:
    """
    Parse the model response for a coding task.

    Accepts two formats:
      1. Fenced blocks:  filename.py\\n```python\\n...\\n```
      2. Legacy delims:  === filename.py ===\\n...

    Normalises filenames and silently drops any not in `allowed`.
    Returns {} if nothing could be parsed.
    """
    files: dict[str, str] = {}

    # Format 1: fenced blocks (preferred)
    # Match: optional "=== ... ===" header or bare name, then ```python ... ```
    fenced = re.findall(
        r"(?:===\s*(.+?)\s*===|^([^\n`=][^\n]*?\.py))\s*\n```(?:python)?\n(.*?)```",
        content,
        flags=re.DOTALL | re.MULTILINE,
    )
    for g1, g2, body in fenced:
        raw_name = (g1 or g2).strip()
        name = normalise_filename(raw_name, allowed)
        if name:
            files[name] = body.rstrip("\n")

    if files:
        return files

    # Format 2: legacy === filename === delimiters
    parts = re.split(r"^===\s*(.+?)\s*===$", content, flags=re.MULTILINE)
    it = iter(parts[1:])
    for raw_name, body in zip(it, it):
        name = normalise_filename(raw_name.strip(), allowed)
        if name:
            files[name] = body.strip("\n")

    return files
