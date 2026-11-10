"""Shared HTTP plumbing for the OpenAI-style providers."""
import json
import os
import random
import time
import urllib.error
import urllib.request


def post_json(url, env, body):
    # If no key is set locally a placeholder is sent; in a managed environment the
    # network proxy swaps in the real credential for the host.
    key = os.environ.get(env) or "placeholder-key"
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json", "X-Title": "radbinical"})
    last = None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                data = json.loads(r.read())
            if data.get("error"):
                raise RuntimeError(json.dumps(data["error"])[:400])
            if not (data.get("choices") or data.get("output")):
                raise RuntimeError("empty response: " + json.dumps(data)[:300])
            return data
        except urllib.error.HTTPError as e:
            last = RuntimeError(f"HTTP {e.code} for {body['model']}: {e.read().decode(errors='replace')[:400]}")
            if e.code not in (402, 408, 409, 429) and e.code < 500:
                raise last
        except (urllib.error.URLError, TimeoutError, ConnectionError, RuntimeError, json.JSONDecodeError) as e:
            last = e
        time.sleep(3 * 2 ** attempt + random.random())
    raise last


def add_usage(total, u):
    for k, v in (u or {}).items():
        if isinstance(v, (int, float)):
            total[k] = total.get(k, 0) + v
