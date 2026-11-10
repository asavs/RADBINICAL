"""Text embeddings, cached on disk so no text is embedded twice by the same model.

    vectors = embed(["one text", "another"], "google:gemini-embedding-2")

The model id picks the provider:

    google:<model>    Gemini API, models/<model>:batchEmbedContents, key GEMINI_API_KEY
    openai:<model>    OpenAI, /v1/embeddings, key OPENAI_API_KEY
    mock:<anything>   no network: a hashed bag of words, deterministic (for tests)
    <vendor/model>    OpenRouter, /api/v1/embeddings, key OPENROUTER_API_KEY

The cache is `<cache_dir>/<model-slug>.jsonl` (default data/embeddings/), one line per text:
{"sha1": <sha1 of the text>, "vector": [...]}. Lines are appended as texts are embedded.
"""
import hashlib
import json
import math
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from .config import ROOT
from .providers.http import api_key

DEFAULT = "google:gemini-embedding-2"
BATCH = 100            # texts per request
GOOGLE_DIM = 768       # outputDimensionality asked of Gemini (docs: 128..3072, 768 recommended)
MOCK_DIM = 512

GOOGLE_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents"
OPENAI_URL = "https://api.openai.com/v1/embeddings"
OPENROUTER_URL = "https://openrouter.ai/api/v1/embeddings"

_STOP = set("""a an and are as at be been but by for from has have he her his i if in into is it its
of on or our she so that the their them then there these they this those to was we were what when which
who will with would you not no can may also more than such one""".split())


def slug(model):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", model).strip("-")


def sha1(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def embed(texts, model=DEFAULT, cache_dir=None):
    """One vector per text, in order. Texts already in the cache are not sent again."""
    path = Path(cache_dir or ROOT / "data" / "embeddings") / f"{slug(model)}.jsonl"
    cache = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                x = json.loads(line)
                cache[x["sha1"]] = x["vector"]
    keys = [sha1(t) for t in texts]
    todo = list({k: t for k, t in zip(keys, texts) if k not in cache}.items())
    if todo:
        path.parent.mkdir(parents=True, exist_ok=True)
        for i in range(0, len(todo), BATCH):
            chunk = todo[i:i + BATCH]
            vectors = _fetch(model, [t for _, t in chunk])
            with path.open("a", encoding="utf-8") as f:
                for (k, _), v in zip(chunk, vectors):
                    cache[k] = v
                    f.write(json.dumps({"sha1": k, "vector": v}) + "\n")
    return [cache[k] for k in keys]


def _fetch(model, texts):
    """Vectors for texts from the model's provider, one request."""
    head, sep, name = model.partition(":")
    if sep and head == "mock":
        return [bag_of_words(t) for t in texts]
    if sep and head == "google":
        body = {"requests": [{"model": f"models/{name}", "content": {"parts": [{"text": t}]},
                              "outputDimensionality": GOOGLE_DIM} for t in texts]}
        data = _post(GOOGLE_URL.format(model=name), {"x-goog-api-key": _key("google")}, body)
        return [e["values"] for e in data["embeddings"]]
    if sep and head == "openai":
        url, key = OPENAI_URL, _key("openai")
    else:
        url, key, name = OPENROUTER_URL, _key("openrouter"), model.removeprefix("openrouter:")
    data = _post(url, {"Authorization": f"Bearer {key}"}, {"model": name, "input": texts, "encoding_format": "float"})
    return [e["embedding"] for e in sorted(data["data"], key=lambda e: e["index"])]


def _key(provider):
    # As in providers.http: with no key set a placeholder is sent, for a proxy that supplies it.
    return api_key(provider) or "placeholder-key"


ATTEMPTS = 8


def _post(url, headers, body):
    """POST and return the JSON answer. A 429 waits as long as the answer's retryDelay asks (Gemini's
    free tier counts every text against a per-minute quota), else backs off; 5xx and network errors
    back off too."""
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={**headers, "Content-Type": "application/json"})
    for attempt in range(ATTEMPTS):
        wait = min(3 * 2 ** attempt, 60)
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            text = e.read().decode(errors="replace")
            msg = f"HTTP {e.code} from {url}: {text[:400]}"
            if e.code != 429 and e.code < 500 or attempt == ATTEMPTS - 1:
                raise RuntimeError(msg) from None
            asked = re.search(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"', text)
            if asked:
                wait = float(asked.group(1)) + 1
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == ATTEMPTS - 1:
                raise
        time.sleep(wait)


def words(text):
    return [w for w in re.findall(r"[a-z0-9']+", text.lower()) if w not in _STOP and len(w) > 2]


def bag_of_words(text):
    """A unit vector: each content word adds ±1 at a position fixed by its hash, then each
    position is damped by sqrt. Texts sharing words point the same way."""
    v = [0.0] * MOCK_DIM
    for w in words(text):
        h = int(hashlib.sha1(w.encode("utf-8")).hexdigest(), 16)
        v[h % MOCK_DIM] += 1.0 if (h >> 20) & 1 else -1.0
    v = [math.copysign(math.sqrt(abs(x)), x) for x in v]
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [round(x / n, 6) for x in v]


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0
