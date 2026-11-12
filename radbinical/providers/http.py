"""Shared HTTP plumbing for the OpenAI-style providers, and where each provider's key is read."""
import contextvars
import json
import os
import random
import time
import urllib.error
import urllib.request


KEYS = {  # environment variables holding each provider's key, first set one wins
    "openrouter": ("OPENROUTER_API_KEY",),
    "nous": ("NOUS_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "google": ("GEMINI_API_KEY",),
    "xai": ("XAI_API_KEY",),
    "nvidia": ("NVIDIA_API_KEY", "NVIDIA_NIM_API_KEY"),
}


_GIVEN = contextvars.ContextVar("given_keys", default=None)


def use_keys(keys, env=True):
    """From here on in this thread, take providers' keys from `keys` ({provider: key}) first, and
    from the environment only when `env` is true. The server calls this for each request that
    brings its own keys."""
    _GIVEN.set(({p: k for p, k in (keys or {}).items() if p in KEYS and k}, env))


def api_key(provider):
    """The provider's key: the one given by `use_keys`, else the environment's, or None."""
    given = _GIVEN.get()
    if given:
        if given[0].get(provider):
            return given[0][provider]
        if not given[1]:
            return None
    return next((os.environ[n] for n in KEYS[provider] if os.environ.get(n)), None)


ATTEMPTS = 8  # with backoff capped at a minute, about five minutes of retrying
ATTEMPTS_ASKED = 3  # for a request that brought its keys: someone is waiting at a page


def post_json(url, provider, body):
    # If no key is set locally a placeholder is sent; in a managed environment the
    # network proxy swaps in the real credential for the host.
    key = api_key(provider)
    if key is None and _GIVEN.get():
        raise RuntimeError(f"no {provider} key was given")
    key = key or "placeholder-key"
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json", "X-Title": "radbinical"})
    last, attempts = None, ATTEMPTS_ASKED if _GIVEN.get() else ATTEMPTS
    for attempt in range(attempts):
        wait = min(3 * 2 ** attempt, 60) + random.random()
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
            # A shared provider answers 402 when requests already in flight hold the credit; it says when to retry.
            after = (e.headers or {}).get("Retry-After") if e.headers is not None else None
            if after and str(after).replace(".", "", 1).isdigit():
                wait = min(float(after), 120) + random.random()
        except (urllib.error.URLError, TimeoutError, ConnectionError, RuntimeError, json.JSONDecodeError) as e:
            last = e
        if attempt < attempts - 1:
            time.sleep(wait)
    raise last


def add_usage(total, u):
    for k, v in (u or {}).items():
        if isinstance(v, (int, float)):
            total[k] = total.get(k, 0) + v
