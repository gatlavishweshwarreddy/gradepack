"""
gradepack doctor — check environment and connectivity.

Usage:
    python -m gradepack doctor
    python -m gradepack doctor --dry-run
"""
import json
import os
import sys
import urllib.error
import urllib.request


def cmd_doctor(dry_run: bool = False) -> None:
    """
    Check BASE_URL, API_KEY, MODEL env vars and make a tiny test request.
    Never prints the API key value — only 'set' or 'missing'.
    --dry-run only checks env vars without making a network request.
    """
    base_url = os.environ.get("BASE_URL", "")
    api_key  = os.environ.get("API_KEY", "")
    model    = os.environ.get("MODEL", "meta-models/muse-spark-open-1026")

    print("Environment:")
    print(f"  BASE_URL : {'set (' + base_url + ')' if base_url else 'MISSING'}")
    print(f"  API_KEY  : {'set' if api_key else 'MISSING'}")
    print(f"  MODEL    : {model}")

    missing = [k for k, v in [("BASE_URL", base_url), ("API_KEY", api_key)] if not v]
    if missing:
        print(f"\nERROR: missing required env var(s): {', '.join(missing)}")
        sys.exit(1)

    if dry_run:
        print("\n--dry-run: skipping network request.")
        return

    print("\nSending test request…")
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a test assistant."},
            {"role": "user",   "content": "Reply with the single word: ok"},
        ],
        "max_tokens": 16,
        "temperature": 0.0,
    }).encode()

    url = f"{base_url.rstrip('/')}/chat/completions"
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
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        print(f"  HTTP error: {exc.code} {exc.reason}")
        sys.exit(1)
    except Exception as exc:
        print(f"  Request failed: {exc}")
        sys.exit(1)

    choices = data.get("choices", [])
    if choices:
        msg = choices[0].get("message", {})
        content          = msg.get("content")
        reasoning        = msg.get("reasoning_content")
        finish_reason    = choices[0].get("finish_reason", "")
        content_present  = content is not None and content != ""
        reasoning_present = reasoning is not None and reasoning != ""
        print(f"  status       : OK")
        print(f"  finish_reason: {finish_reason}")
        print(f"  content      : {'present' if content_present else 'absent/null'}")
        print(f"  reasoning_content: {'present' if reasoning_present else 'absent'}")
        if reasoning_present and not content_present:
            print("  WARNING: content is absent but reasoning_content is present.")
            print("           gradepack uses 'content' only — this model may not work correctly.")
    else:
        print(f"  Unexpected response: {json.dumps(data)[:200]}")
        sys.exit(1)
