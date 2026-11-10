#!/usr/bin/env python3
"""marginalia: several models annotate one passage, then annotate each other.

    python3 marginalia.py run config.json            # start a new page
    python3 marginalia.py extend runs/<dir> -n 2     # add layers to an existing page
    python3 marginalia.py extend runs/<dir> -n 1 --models openai/gpt-6.1-terra
    python3 marginalia.py render runs/<dir>          # rebuild page.html

Model ids are OpenRouter ids by default. Prefix with "anthropic:", "openai:" or
"nvidia:" to call that provider directly, or "mock:" for an offline stand-in.
Standard library only, plus the `anthropic` package for "anthropic:" readers.
"""
import argparse, concurrent.futures as cf, datetime, json, os, random, re, sys
import threading, time, urllib.error, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent

DEFAULT_FLAGS = {
    "max_layers": 4,              # hard cap on rounds
    "stop_when_all_pass": True,   # end early once a whole round adds nothing
    "blind_first_layer": True,    # round 1: everyone glosses the bare text independently
    "sequential": False,          # later rounds: one at a time, each seeing the live page
    "signed": True,               # False: readers see each other as "Reader A", "Reader B"...
    "anchor": "span",             # "span" (any quoted run) or "sentence" (snapped to whole sentences)
    "cross_refs": True,           # allow see_also pointers between comments
    "allow_self_reply": True,
    "max_comments_per_turn": None,
    "max_steps_per_turn": 16,     # safety cap on tool round-trips per reader per round
    "max_tokens": 8000, 
    "temperature": None,
    "seed": 0,
}

# ---------------------------------------------------------------- text anchoring

_FOLD = {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "}


def fold(s):
    """Normalise for matching; returns (folded, map from folded index -> original index)."""
    out, idx, prev_space = [], [], False
    for i, ch in enumerate(s):
        ch = _FOLD.get(ch, ch)
        if ch.isspace():
            if prev_space:
                continue
            ch, prev_space = " ", True
        else:
            prev_space = False
        out.append(ch.lower())
        idx.append(i)
    return "".join(out), idx


def locate(haystack, quote):
    """Find quote in haystack tolerant of whitespace, case and curly quotes. -> (start, end) or None."""
    h, idx = fold(haystack)
    q = fold(quote.strip())[0].strip()
    for cand in (q, q.strip(" .\"'"), q.replace("...", "").replace("…", "").strip(" .\"'")):
        if len(cand) < 2:
            continue
        k = h.find(cand)
        if k >= 0:
            return idx[k], idx[k + len(cand) - 1] + 1
    return None


def snap_to_sentences(text, start, end):
    bounds = [0] + [m.end() for m in re.finditer(r"[.!?][\"')\]]*\s+", text)] + [len(text)]
    s = max(b for b in bounds if b <= start)
    e = min(b for b in bounds if b >= end)
    return s, len(text[:e].rstrip())


# ---------------------------------------------------------------- the page

def load_passage(path):
    raw = Path(path).read_text(encoding="utf-8")
    paras = [" ".join(p.split()) for p in re.split(r"\n\s*\n", raw) if p.strip()]
    return "\n\n".join(paras)


def children(page, cid):
    return [c for c in page["comments"] if c["target"] == cid]


def render_for_reader(page, visible, label, me):
    """Plain-text view of the page as one reader sees it."""
    p = page["passage"]
    out = ["=== THE PASSAGE ===", f"{p['title']}" + (f" ({p['source']})" if p.get("source") else ""), "", p["text"], ""]
    out.append(f"=== THE MARGINS ({len(visible)} comment{'s' if len(visible) != 1 else ''}) ===")
    if not visible:
        out.append("(empty)")
    vis_ids = {c["id"] for c in visible}

    def walk(c, depth):
        pad = "    " * depth
        who = label(c["author"]) + (" (you)" if c["author"] == me else "")
        where = "on the passage" if c["target"] == "passage" else f"on {c['target']}"
        q = f': "{c["quote"]}"' if c.get("quote") else ""
        out.append(f"{pad}[{c['id']}] {who}, {where}{q}")
        for line in c["text"].splitlines() or [""]:
            out.append(f"{pad}    {line}")
        if c.get("see_also"):
            out.append(f"{pad}    (see also: {', '.join(c['see_also'])})")
        out.append("")
        for k in children(page, c["id"]):
            if k["id"] in vis_ids:
                walk(k, depth + 1)

    tops = [c for c in visible if c["target"] == "passage"]
    for c in sorted(tops, key=lambda c: (c["start"], c["n"])):
        walk(c, 0)
    return "\n".join(out)


def system_prompt(page, me, label, protocol="tools"):
    flags = page["flags"]
    others = [label(r["name"]) for r in page["readers"] if r["name"] != me]
    n = len(page["readers"])
    if flags["signed"]:
        roster = f"You appear on the page as {me}. The other readers are {', '.join(others)}." if others else f"You appear on the page as {me}."
    else:
        roster = "Readers are not named on the page; your own comments are marked (you)."
    anchor = ("quote the span exactly as it appears; it can be a few words or several sentences"
              if flags["anchor"] == "span" else "quote any part of a sentence; the comment attaches to the whole sentence")
    refs = " A comment can also point at other comments with see_also." if flags["cross_refs"] else ""
    return (
        f"You are one of {n} readers sharing a single page. At the centre of the page is a passage. "
        f"Around it, in the margins, commentary accumulates over several rounds. {roster}\n\n"
        + (f"You have one tool, `annotate`. Use it to attach a comment to the passage ({anchor}) "
           f"or to an existing comment (give its id, and optionally quote the part of it you mean).{refs}\n\n"
           if protocol != "text" else
           "To attach a comment, write a block like this in your reply:\n\n"
           '<annotate target="passage" quote="the exact words you mean">\nyour comment\n</annotate>\n\n'
           f"The target is either \"passage\" ({anchor}) or the id of an existing comment such as \"c7\" "
           "(the quote is then optional). You can write several blocks in one reply."
           + (' A block can also carry see_also="c2,c5" to point at other comments.' if flags["cross_refs"] else "") + "\n\n") +
        "There is no assignment and nothing here is being scored. Comment where you have something to say, "
        "as briefly or at as much length as the thought needs, and leave the rest alone. Agreeing, disagreeing, "
        "asking, connecting and staying silent are all fine. When you have nothing further to add this round, "
        + ("say so in plain text without calling the tool. That ends your turn." if protocol != "text"
           else "reply without any block. That ends your turn.")
    )


def annotate_tool(flags):
    props = {
        "target": {"type": "string", "description": 'Either "passage" or the id of an existing comment, e.g. "c7".'},
        "quote": {"type": "string", "description": "The exact words you are commenting on, copied from the target. Required when the target is the passage."},
        "text": {"type": "string", "description": "Your comment."},
    }
    if flags["cross_refs"]:
        props["see_also"] = {"type": "array", "items": {"type": "string"}, "description": "Optional ids of other comments this one connects to."}
    return {"type": "function", "function": {
        "name": "annotate",
        "description": "Attach a comment to a span of the passage or to an existing comment.",
        "parameters": {"type": "object", "properties": props, "required": ["target", "text"]},
    }}


# ---------------------------------------------------------------- model calls
# Every provider is wrapped in a Session with the same three moves:
#   step()  -> (calls, text, usage)   calls = [(call_id, args_dict_or_None)]
#   reply(results)                    results = [(call_id, message)]

PROVIDERS = {
    "openrouter": ("https://openrouter.ai/api/v1/chat/completions", "OPENROUTER_API_KEY", "max_tokens"),
    "openai": ("https://api.openai.com/v1/chat/completions", "OPENAI_API_KEY", "max_completion_tokens"),
    "nvidia": ("https://integrate.api.nvidia.com/v1/chat/completions", "NVIDIA_API_KEY", "max_tokens"),
}
KNOWN = set(PROVIDERS) | {"anthropic", "mock"}


def split_model(model):
    head, sep, rest = model.partition(":")
    return (head, rest) if sep and head in KNOWN else ("openrouter", model)


def post_json(url, env, body):
    # If no key is set locally a placeholder is sent; in a managed environment the
    # network proxy swaps in the real credential for the host.
    key = os.environ.get(env) or "placeholder-key"
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json", "X-Title": "marginalia"})
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


class ChatSession:
    """OpenAI-style chat completions with native tool calls (OpenRouter, OpenAI, NVIDIA)."""
    def __init__(self, provider, name, system, user, flags, max_tokens):
        self.url, self.env, self.cap = PROVIDERS[provider]
        self.name, self.flags, self.max_tokens = name, flags, max_tokens
        self.messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        self.tools = [annotate_tool(flags)]

    def _send(self, with_tools=True):
        body = {"model": self.name, "messages": self.messages, self.cap: self.max_tokens}
        if with_tools:
            body["tools"] = self.tools
        if self.flags["temperature"] is not None:
            body["temperature"] = self.flags["temperature"]
        data = post_json(self.url, self.env, body)
        return data["choices"][0]["message"], data.get("usage") or {}

    def step(self):
        msg, usage = self._send()
        self.messages.append(msg)  # kept whole so any reasoning blocks the provider needs are replayed intact
        calls = []
        for c in msg.get("tool_calls") or []:
            try:
                calls.append((c["id"], json.loads(c["function"].get("arguments") or "{}")))
            except json.JSONDecodeError:
                calls.append((c["id"], None))
        text = msg.get("content") if isinstance(msg.get("content"), str) else ""
        return calls, text or "", usage

    def reply(self, results):
        for cid, res in results:
            self.messages.append({"role": "tool", "tool_call_id": cid, "content": res})


class ResponsesSession:
    """OpenAI's Responses API, which its reasoning models need for tool use."""
    URL = "https://api.openai.com/v1/responses"

    def __init__(self, name, system, user, flags, max_tokens):
        self.name, self.system, self.flags, self.max_tokens = name, system, flags, max_tokens
        self.input = [{"role": "user", "content": user}]
        t = annotate_tool(flags)["function"]
        self.tools = [{"type": "function", "name": t["name"], "description": t["description"], "parameters": t["parameters"]}]

    def step(self):
        body = {"model": self.name, "instructions": self.system, "input": self.input, "tools": self.tools,
                "max_output_tokens": self.max_tokens, "store": False, "include": ["reasoning.encrypted_content"]}
        if self.flags["temperature"] is not None:
            body["temperature"] = self.flags["temperature"]
        data = post_json(self.URL, "OPENAI_API_KEY", body)
        self.input += data["output"]  # reasoning items are replayed as returned
        calls, text = [], []
        for item in data["output"]:
            if item.get("type") == "function_call":
                try:
                    calls.append((item["call_id"], json.loads(item.get("arguments") or "{}")))
                except json.JSONDecodeError:
                    calls.append((item["call_id"], None))
            elif item.get("type") == "message":
                text += [c.get("text", "") for c in item.get("content", []) if c.get("type") == "output_text"]
        u = data.get("usage") or {}
        return calls, "\n".join(text), {"prompt_tokens": u.get("input_tokens", 0), "completion_tokens": u.get("output_tokens", 0)}

    def reply(self, results):
        self.input += [{"type": "function_call_output", "call_id": cid, "output": res} for cid, res in results]


_BLOCK = re.compile(r"<annotate\b([^>]*)>(.*?)</annotate>", re.S | re.I)
_ATTR = re.compile(r"""(\w+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")


class TextSession(ChatSession):
    """For models without reliable tool calling: comments are written as <annotate> blocks in plain text."""
    def step(self):
        msg, usage = self._send(with_tools=False)
        text = msg.get("content") if isinstance(msg.get("content"), str) else ""
        self.messages.append({"role": "assistant", "content": text or ""})
        calls = []
        for i, m in enumerate(_BLOCK.finditer(text or "")):
            attrs = {k.lower(): (a or b) for k, a, b in _ATTR.findall(m.group(1))}
            args = {"target": attrs.get("target", "passage"), "quote": attrs.get("quote", ""), "text": m.group(2).strip()}
            if attrs.get("see_also"):
                args["see_also"] = re.split(r"[,\s]+", attrs["see_also"].strip())
            calls.append((str(i), args))
        return calls, _BLOCK.sub("", text or "").strip(), usage

    def reply(self, results):
        lines = [res for _, res in results]
        self.messages.append({"role": "user", "content": "\n".join(lines) + "\n\nAdd more blocks if you wish, or reply without one to end your turn."})


class AnthropicSession:
    """Claude through the Anthropic API directly, using the official SDK."""
    def __init__(self, name, system, user, flags, max_tokens):
        import anthropic
        # base_url is pinned so an ANTHROPIC_BASE_URL set for other tooling cannot redirect the call.
        self.client = anthropic.Anthropic(api_key=os.environ.get("MARGINALIA_ANTHROPIC_KEY") or os.environ.get("ANTHROPIC_API_KEY") or "placeholder-key",
                                          base_url="https://api.anthropic.com")
        self.name, self.system, self.max_tokens, self.flags = name, system, max_tokens, flags
        self.messages = [{"role": "user", "content": user}]
        t = annotate_tool(flags)["function"]
        self.tools = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}]

    def step(self):
        # No `thinking` parameter: each model runs with its own default, which keeps one
        # request shape valid from Claude 3 through the current models. No refusal fallback
        # either: a reader silently swapped for another model would corrupt the record.
        kw = {}
        if self.flags["temperature"] is not None:
            kw["temperature"] = self.flags["temperature"]
        r = self.client.messages.create(model=self.name, max_tokens=self.max_tokens, system=self.system,
                                        tools=self.tools, messages=self.messages, **kw)
        self.messages.append({"role": "assistant", "content": r.content})
        calls = [(b.id, b.input if isinstance(b.input, dict) else None) for b in r.content if b.type == "tool_use"]
        text = "\n".join(b.text for b in r.content if b.type == "text")
        if r.stop_reason == "refusal":
            calls, text = [], "[the model declined to continue]"
        return calls, text, {"prompt_tokens": r.usage.input_tokens, "completion_tokens": r.usage.output_tokens}

    def reply(self, results):
        self.messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": cid, "content": res} for cid, res in results]})


class MockSession:
    """Offline stand-in: placeholder comments, clearly not a real model's reading."""
    def __init__(self, name, system, user):
        self.name, self.messages = name, [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def step(self):
        msg, _ = mock_chat(self.name, self.messages)
        self.messages.append(msg)
        calls = [(c["id"], json.loads(c["function"]["arguments"])) for c in msg.get("tool_calls") or []]
        return calls, msg.get("content") or "", {}

    def reply(self, results):
        for cid, res in results:
            self.messages.append({"role": "tool", "tool_call_id": cid, "content": res})


def open_session(reader, system, user, flags):
    provider, name = split_model(reader["model"])
    max_tokens = reader.get("max_tokens") or flags["max_tokens"]
    if provider == "mock":
        return MockSession(name, system, user)
    if provider == "anthropic":
        return AnthropicSession(name, system, user, flags, max_tokens)
    if provider == "openai" and reader.get("protocol") != "text":
        return ResponsesSession(name, system, user, flags, max_tokens)
    cls = TextSession if reader.get("protocol") == "text" else ChatSession
    return cls(provider, name, system, user, flags, max_tokens)


_MOCK = ["This sentence carries more weight than it admits.", "I read this differently: the claim is narrower than it sounds.",
         "Compare the earlier wording; the two do not obviously agree.", "What would count as evidence against this?",
         "Agreed, and it extends further than the author takes it."]


def mock_chat(name, messages):
    """Offline stand-in: placeholder comments, clearly not a real model's reading."""
    rng = random.Random(name + str(len(messages)) + messages[1]["content"][:40])
    if len(messages) > 2 + 2 * rng.randint(1, 3):
        return {"role": "assistant", "content": "Nothing further this round."}, {}
    page = messages[1]["content"]
    ids = re.findall(r"^\s*\[(c\d+)\]", page, re.M)
    body = page.split("=== THE MARGINS")[0].split("\n\n", 1)[1]
    sents = [s.strip() for s in re.split(r"(?<=[.;])\s+", body) if len(s.strip()) > 30]
    if ids and rng.random() < 0.6:
        args = {"target": rng.choice(ids), "text": "[mock] " + rng.choice(_MOCK)}
    else:
        s = rng.choice(sents); w = s.split(); a = rng.randrange(0, max(1, len(w) - 6))
        args = {"target": "passage", "quote": " ".join(w[a:a + rng.randint(4, 12)]), "text": "[mock] " + rng.choice(_MOCK)}
    call = {"id": f"call_{rng.randrange(10**9)}", "type": "function", "function": {"name": "annotate", "arguments": json.dumps(args)}}
    return {"role": "assistant", "content": None, "tool_calls": [call]}, {}


# ---------------------------------------------------------------- one reader, one round

class Page:
    def __init__(self, data, out_dir):
        self.d, self.dir, self.lock = data, Path(out_dir), threading.Lock()

    def save(self):
        with self.lock:
            (self.dir / "page.json").write_text(json.dumps(self.d, indent=1, ensure_ascii=False), encoding="utf-8")

    def add(self, author, layer, args):
        """Validate and record one annotation. Returns (ok, message for the model)."""
        d, flags = self.d, self.d["flags"]
        target = str(args.get("target", "")).strip().strip("[]")
        text = str(args.get("text", "")).strip()
        quote = str(args.get("quote") or "").strip()
        if not text:
            return False, "Not recorded: the comment text is empty."
        with self.lock:
            by_id = {c["id"]: c for c in d["comments"]}
            c = {"author": author, "layer": layer, "text": text}
            if target.lower() == "passage":
                if not quote:
                    return False, "Not recorded: a comment on the passage needs `quote`, the exact words it attaches to."
                span = locate(d["passage"]["text"], quote)
                if not span:
                    return False, "Not recorded: that quote was not found in the passage. Copy the words exactly as they appear."
                if flags["anchor"] == "sentence":
                    span = snap_to_sentences(d["passage"]["text"], *span)
                c.update(target="passage", start=span[0], end=span[1], quote=d["passage"]["text"][span[0]:span[1]])
            elif target in by_id:
                parent = by_id[target]
                if parent["author"] == author and not flags["allow_self_reply"]:
                    return False, "Not recorded: replying to your own comment is switched off for this page."
                c.update(target=target)
                if quote:
                    span = locate(parent["text"], quote)
                    c["quote"] = parent["text"][span[0]:span[1]] if span else quote
            else:
                return False, f'Not recorded: no comment with id "{target}". Use "passage" or an id shown on the page.'
            refs = [str(r).strip("[] ") for r in (args.get("see_also") or [])] if flags["cross_refs"] else []
            refs = [r for r in refs if r in by_id]
            if refs:
                c["see_also"] = refs
            d["counter"] += 1
            c["n"] = d["counter"]
            c["id"] = f"c{c['n']}"
            d["comments"].append(c)
            return True, f"Recorded as {c['id']}."


def take_turn(page, reader, layer, visible_fn, label, note):
    d, flags, me = page.d, page.d["flags"], reader["name"]
    visible = visible_fn(me)
    system = system_prompt(d, me, label, reader.get("protocol", "tools"))
    user = f"Round {layer}. {note}\n\n" + render_for_reader(d, visible, label, me)
    made, usage, closing, err = 0, {}, None, None
    try:
        session = open_session(reader, system, user, flags)
        for _ in range(flags["max_steps_per_turn"]):
            calls, text, u = session.step()
            add_usage(usage, u)
            if not calls:
                closing = text.strip() or None
                break
            results = []
            for cid, args in calls:
                cap = flags["max_comments_per_turn"]
                if args is None:
                    ok, res = False, "Not recorded: the arguments were not valid JSON."
                elif cap is not None and made >= cap:
                    ok, res = False, "Not recorded: you have reached this round's comment limit."
                else:
                    ok, res = page.add(me, layer, args)
                made += ok
                results.append((cid, res))
            session.reply(results)
    except Exception as e:  # one reader failing should not sink the round
        err = f"{type(e).__name__}: {e}"[:600]
    entry = {"layer": layer, "reader": me, "model": reader["model"], "comments": made, "usage": usage}
    if closing:
        entry["closing"] = closing[:2000]
    if err:
        entry["error"] = err
    with page.lock:
        d["log"].append(entry)
    print(f"  round {layer}  {me:<22} {made} comment{'s' if made != 1 else ''}" + (f"   ERROR {err}" if err else ""), flush=True)
    return made, err


def run_layers(page, how_many):
    d, flags = page.d, page.d["flags"]
    rng = random.Random(f"{flags['seed']}-{d['layers_done']}")
    pseudonyms = {r["name"]: f"Reader {chr(65 + i)}" for i, r in enumerate(d["readers"])}
    label = (lambda a: a) if flags["signed"] else (lambda a: pseudonyms.get(a, "Reader"))
    for _ in range(how_many):
        layer = d["layers_done"] + 1
        readers = d["readers"][:]
        rng.shuffle(readers)
        live = flags["sequential"] and not (layer == 1 and flags["blind_first_layer"])
        if live:
            vis = lambda me: list(d["comments"])
            note = "Readers take turns this round; you see the page as it stands now."
        else:
            vis = lambda me, L=layer: [c for c in d["comments"] if c["layer"] < L or c["author"] == me]
            note = ("The margins are empty. Every reader is annotating independently this round; you will see each other's comments next round."
                    if layer == 1 else "Everyone annotates at the same time this round; you will see this round's comments from the others next round.")
        print(f"round {layer}: {'in turn' if live else 'in parallel'}", flush=True)
        if live:
            results = [take_turn(page, r, layer, vis, label, note) for r in readers]
        else:
            with cf.ThreadPoolExecutor(len(readers)) as ex:
                results = list(ex.map(lambda r: take_turn(page, r, layer, vis, label, note), readers))
        d["layers_done"] = layer
        page.save()
        render(page.dir)
        if all(e for _, e in results):
            print("every reader failed this round; stopping.")
            return False
        if flags["stop_when_all_pass"] and sum(m for m, _ in results) == 0:
            print("everyone passed; the page is at rest.")
            d["at_rest"] = True
            page.save()
            break
    return True


# ---------------------------------------------------------------- commands

def reader_entry(m):
    if isinstance(m, str):
        m = {"model": m}
    name = m.get("name") or split_model(m["model"])[1].split("/")[-1]
    return {**{k: m[k] for k in ("protocol", "max_tokens") if k in m}, "model": m["model"], "name": name}


def cmd_run(a):
    cfg = json.loads(Path(a.config).read_text())
    flags = {**DEFAULT_FLAGS, **cfg.get("flags", {})}
    unknown = set(flags) - set(DEFAULT_FLAGS)
    if unknown:
        sys.exit(f"unknown flag(s) in config: {', '.join(sorted(unknown))}")
    base = Path(a.config).resolve().parent
    p = cfg["passage"]
    text = load_passage(base / p["file"])
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^a-z0-9]+", "-", p["title"].lower()).strip("-")[:40]
    out = Path(a.out) if a.out else HERE / "runs" / f"{stamp}-{slug}"
    out.mkdir(parents=True, exist_ok=True)
    data = {
        "passage": {"title": p["title"], "source": p.get("source", ""), "text": text},
        "readers": [reader_entry(m) for m in cfg["models"]],
        "flags": flags, "comments": [], "log": [], "counter": 0, "layers_done": 0,
        "started": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    names = [r["name"] for r in data["readers"]]
    if len(set(names)) != len(names):
        sys.exit("reader names must be unique; give duplicates a distinct \"name\" in the config")
    page = Page(data, out)
    data["prompt_example"] = system_prompt(data, names[0], lambda x: x)
    page.save()
    ok = run_layers(page, flags["max_layers"])
    print(f"\n{len(data['comments'])} comments over {data['layers_done']} round(s)\n{out / 'page.html'}")
    sys.exit(0 if ok else 1)


def cmd_extend(a):
    out = Path(a.run)
    page = Page(json.loads((out / "page.json").read_text()), out)
    if a.models:
        have = {r["name"] for r in page.d["readers"]}
        for m in a.models.split(","):
            r = reader_entry(m.strip())
            if r["name"] not in have:
                page.d["readers"].append(r)
    page.d.pop("at_rest", None)
    ok = run_layers(page, a.n)
    print(f"\n{len(page.d['comments'])} comments over {page.d['layers_done']} round(s)\n{out / 'page.html'}")
    sys.exit(0 if ok else 1)


def render(run_dir):
    run_dir = Path(run_dir)
    data = json.loads((run_dir / "page.json").read_text())
    tpl = (HERE / "viewer.html").read_text(encoding="utf-8")
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    title = "Marginalia on " + re.sub(r"[<>&]", "", data["passage"]["title"])
    html = tpl.replace("__TITLE__", title).replace("/*__PAGE_DATA__*/null", blob)
    (run_dir / "page.html").write_text(html, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("config"); r.add_argument("--out"); r.set_defaults(f=cmd_run)
    e = sub.add_parser("extend"); e.add_argument("run"); e.add_argument("-n", type=int, default=1)
    e.add_argument("--models", help="comma-separated extra readers who join the existing page"); e.set_defaults(f=cmd_extend)
    v = sub.add_parser("render"); v.add_argument("run"); v.set_defaults(f=lambda a: (render(a.run), print(Path(a.run) / "page.html")))
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
