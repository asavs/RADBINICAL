"""The page, served so it can be written on.

    GET  /                        the library: passages to open a bare page on
    GET  /p/<id>                  one page, in the viewer, with its controls
    GET  /api/library             the passages, the models offered, whether the server has keys
    POST /api/pages               a new bare page, from {"passage": id} or {"title", "source", "text"}
    GET  /api/pages/<id>?v=<v>    the page's record, who is reading now, and what it has cost
    POST /api/pages/<id>/comment  a person's comment: {"name", "target", "text", "quote", "span"}
    POST /api/pages/<id>/ask      models take a turn: {"models", "keys", "on": {"target", "quote", "span"}}
    POST /api/pages/<id>/hide     take a comment off the page, or put it back: {"id", "hidden"}
    POST /api/pages/<id>/flags    {"signed": true or false}

A page is `page.json` in a folder named by its id, under the pages folder; the id is long and
random, and is all that is needed to read the page or write on it. There are no accounts.

Each `ask` is one round. The models named in it answer at the same time, each seeing the page as
it stood when they were asked. With `on`, every one of them is asked for one comment on those words
(rounds.take_turn's `ask`); without it they comment where they like.

Keys come with the request, are used for its calls and are not written anywhere. The keys in the
server's own environment are used only when it was started with `env_keys`.
"""
import datetime
import json
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .config import DEFAULT_FLAGS, PACKAGE, ROOT, TEMPLATES
from .human import human_round, slug
from .page import Page, cast_of, is_human, labeller, on_page, passage_text, reader_entry
from .prices import costs
from .prompts import asked_note, system_prompt
from .providers import canonical
from .providers.http import KEYS, use_keys
from .rounds import take_turn
from .site import HEAD, page_html
from .table import usages

PAGE_ID = re.compile(r"[A-Za-z0-9_-]{10,40}")
MODEL_ID = re.compile(r"[\w.:/@+-]{1,120}")
MAX_BODY, MAX_PASSAGE, MAX_COMMENT, MAX_MODELS = 400_000, 60_000, 12_000, 8
MAX_TOKENS = 16000  # a served page's output limit per turn; reasoning counts against it


class Refused(Exception):
    """A request that cannot be met: an HTTP status and what to tell the person."""
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


def _text(body, key, limit, required=False):
    v = body.get(key)
    v = v.strip() if isinstance(v, str) else ""
    if required and not v:
        raise Refused(400, f'"{key}" is missing')
    if len(v) > limit:
        raise Refused(400, f'"{key}" is longer than {limit} characters')
    return v


class Desk:
    """The pages a server holds, and everything that can be done to one."""

    def __init__(self, pages_dir=None, env_keys=False, passages_dir=None):
        self.dir = Path(pages_dir) if pages_dir else ROOT / "pages"
        self.passages = Path(passages_dir) if passages_dir else ROOT / "passages"
        self.env_keys = env_keys
        self.lock = threading.Lock()
        self.open, self.pending = {}, {}   # page id -> Page; page id -> [{"reader", "on"}] in flight

    # the library

    def library(self):
        """The passages on offer: every .txt in the passages folder, with the title and source
        `library.json` there gives it."""
        meta = {}
        if (self.passages / "library.json").exists():
            meta = json.loads((self.passages / "library.json").read_text(encoding="utf-8"))
        out = []
        for f in sorted(self.passages.glob("*.txt")):
            text = passage_text(f.read_text(encoding="utf-8"))
            m = meta.get(f.stem, {})
            out.append({"id": f.stem, "title": m.get("title") or f.stem.replace("-", " ").capitalize(),
                        "source": m.get("source", ""), "text": text})
        return out

    def roster(self):
        return json.loads((PACKAGE / "roster.json").read_text(encoding="utf-8"))

    # pages

    def new_page(self, body):
        if body.get("passage"):
            p = next((p for p in self.library() if p["id"] == body["passage"]), None)
            if not p:
                raise Refused(404, "no such passage")
        else:
            title = _text(body, "title", 200, required=True)
            text = passage_text(_text(body, "text", MAX_PASSAGE, required=True))
            p = {"id": slug(title)[:60], "title": title, "source": _text(body, "source", 400), "text": text, "own": True}
        pid = secrets.token_urlsafe(12)
        data = {"passage": p, "readers": [], "cast": cast_of([]), "group": pid,
                "flags": {**DEFAULT_FLAGS, "max_tokens": MAX_TOKENS}, "comments": [], "log": [], "counter": 0,
                "layers_done": 0, "started": datetime.datetime.now().isoformat(timespec="seconds")}
        (self.dir / pid).mkdir(parents=True)
        page = Page(data, self.dir / pid)
        page.save()
        with self.lock:
            self.open[pid] = page
        return pid

    def get(self, pid):
        if not PAGE_ID.fullmatch(pid or ""):
            raise Refused(404, "no such page")
        with self.lock:
            if pid not in self.open:
                if not (self.dir / pid / "page.json").exists():
                    raise Refused(404, "no such page")
                self.open[pid] = Page.load(self.dir / pid)
            return self.open[pid]

    def state(self, pid, have=None):
        """The page as the viewer needs it. `v` changes whenever anything it shows does; asked for
        with the `v` it already has, the viewer is told only that nothing changed."""
        page = self.get(pid)
        with self.lock:
            pending = list(self.pending.get(pid, []))
        with page.lock:
            d = page.d
            v = f"{d['counter']}.{len(d['log'])}.{sum(1 for c in d['comments'] if c.get('hidden'))}.{int(d['flags']['signed'])}.{len(pending)}"
            if v == have:
                return json.dumps({"v": v, "same": True})
            return json.dumps({"v": v, "page": d, "pending": pending, "cost": round(sum(costs(usages(d))), 4)}, ensure_ascii=False)

    def html(self, pid):
        page = self.get(pid)
        with page.lock:
            data = json.loads(json.dumps(page.d))
        data["live"] = {"id": pid, "models": self.roster(), "env_keys": self.env_keys, "providers": sorted(KEYS)}
        return HEAD + page_html(data, live=True)

    # writing on a page

    def _where(self, d, body):
        """{"target", "quote", "span"} from a request, the target checked to be on the page."""
        target = _text(body, "target", 40) or "passage"
        if target != "passage" and not any(c["id"] == target for c in on_page(d)):
            raise Refused(400, f"there is no comment {target} on the page")
        span = body.get("span")
        if span is not None and not (isinstance(span, list) and len(span) == 2 and all(isinstance(x, int) for x in span)):
            raise Refused(400, '"span" is two whole numbers')
        return {"target": target, "quote": _text(body, "quote", MAX_PASSAGE), "span": span}

    def comment(self, pid, body):
        page = self.get(pid)
        d = page.d
        name, text = _text(body, "name", 60, required=True), _text(body, "text", MAX_COMMENT, required=True)
        where = self._where(d, body)
        with page.lock:
            reader = next((r for r in d["readers"] if r["name"] == name), None)
            if reader and not is_human(reader):
                raise Refused(400, f"{name} is a model's name on this page; choose another")
            layer = human_round(d)
        ok, msg = page.add(name, layer, {**where, "text": text}, kind="human")
        if not ok:
            raise Refused(400, msg.removeprefix("Not recorded: "))
        with page.lock:
            if not any(r["name"] == name for r in d["readers"]):
                d["readers"].append({"name": name, "model": f"human:{slug(name)}", "human": True})
            d["layers_done"] = max(d["layers_done"], layer)
            d["log"].append({"layer": layer, "reader": name, "model": f"human:{slug(name)}", "via": "human", "comments": 1, "usage": {}})
            d.pop("at_rest", None)
        page.save()

    def ask(self, pid, body):
        """Start a round and return its number; the turns run on their own threads."""
        page = self.get(pid)
        d = page.d
        asked = body.get("models")
        if not isinstance(asked, list) or not 1 <= len(asked) <= MAX_MODELS:
            raise Refused(400, f"name between 1 and {MAX_MODELS} models")
        keys = body.get("keys") if isinstance(body.get("keys"), dict) else {}
        keys = {p: k.strip() for p, k in keys.items() if p in KEYS and isinstance(k, str) and 0 < len(k.strip()) <= 400}
        on = self._where(d, body["on"]) if isinstance(body.get("on"), dict) else None
        readers = []
        with page.lock:
            by_name = {r["name"]: r for r in d["readers"]}
            for m in asked:
                m = {"model": m} if isinstance(m, str) else m
                if not isinstance(m, dict) or not isinstance(m.get("model"), str) or not MODEL_ID.fullmatch(m["model"]) or m["model"].startswith("human:"):
                    raise Refused(400, "that is not a model id")
                name = m.get("name").strip()[:60] if isinstance(m.get("name"), str) else ""
                r = reader_entry({"model": m["model"], **({"name": name} if name else {})})
                have = by_name.get(r["name"])
                if have and (is_human(have) or canonical(have["model"]) != canonical(r["model"])):
                    raise Refused(400, f"{r['name']} is already another reader on this page")
                readers.append(have or r)
                by_name[r["name"]] = have or r
            readers = list({r["name"]: r for r in readers}.values())
            d["readers"] += [r for r in readers if r not in d["readers"]]
            d["cast"] = cast_of(d["readers"])
            layer = d["layers_done"] = d["layers_done"] + 1
            d.pop("at_rest", None)
            d.setdefault("prompt_example", system_prompt(d, readers[0]["name"], lambda x: x))
            seen = {c["id"] for c in on_page(d)}
            label = labeller(d)
        if on:
            note = asked_note(on)
        else:
            note = ("You see the page as it stands now." if seen else "The margins are empty.") + (
                " The other readers asked with you are writing at the same time; you will not see their comments this turn."
                if len(readers) > 1 else "")
        visible = lambda me: [c for c in on_page(d) if c["id"] in seen or (c["author"] == me and c["layer"] == layer)]
        flights = [{"reader": r["name"], "on": on["target"] if on else None} for r in readers]
        with self.lock:
            self.pending.setdefault(pid, []).extend(flights)

        def turn(reader, flight):
            use_keys(keys, self.env_keys)
            try:
                take_turn(page, reader, layer, visible, label, note, on)
            finally:
                page.save()
                with self.lock:
                    self.pending[pid].remove(flight)

        page.save()
        for r, f in zip(readers, flights):
            threading.Thread(target=turn, args=(r, f), daemon=True).start()
        return layer

    def hide(self, pid, body):
        page = self.get(pid)
        with page.lock:
            c = next((c for c in page.d["comments"] if c["id"] == body.get("id")), None)
            if not c:
                raise Refused(404, "no such comment")
            if body.get("hidden", True):
                c["hidden"] = True
            else:
                c.pop("hidden", None)
        page.save()

    def flags(self, pid, body):
        page = self.get(pid)
        if not isinstance(body.get("signed"), bool):
            raise Refused(400, '"signed" is true or false')
        with page.lock:
            page.d["flags"]["signed"] = body["signed"]
        page.save()


class Handler(BaseHTTPRequestHandler):
    desk = None
    server_version = "radbinical"

    def _send(self, status, body, kind="application/json"):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", kind + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")   # a page's address is its key; do not hand it to linked sites
        self.end_headers()
        self.wfile.write(data)

    def _answer(self, f):
        try:
            f()
        except Refused as e:
            self._send(e.status, json.dumps({"error": e.message}))
        except Exception as e:  # a fault here must not take the server down
            self._send(500, json.dumps({"error": f"{type(e).__name__}: {e}"[:300]}))

    def do_GET(self):
        url = urlparse(self.path)
        path, desk = url.path, self.desk

        def go():
            if path == "/":
                return self._send(200, HEAD + (TEMPLATES / "library.html").read_text(encoding="utf-8"), "text/html")
            if path == "/favicon.ico":
                return self._send(204, "", "image/x-icon")
            if path == "/api/library":
                return self._send(200, json.dumps({"passages": desk.library(), "env_keys": desk.env_keys}, ensure_ascii=False))
            m = re.fullmatch(r"/p/([^/]+)", path)
            if m:
                return self._send(200, desk.html(m.group(1)), "text/html")
            m = re.fullmatch(r"/api/pages/([^/]+)", path)
            if m:
                return self._send(200, desk.state(m.group(1), (parse_qs(url.query).get("v") or [None])[0]))
            raise Refused(404, "nothing here")
        self._answer(go)

    def do_POST(self):
        path, desk = urlparse(self.path).path, self.desk

        def go():
            # Only JSON is taken, which a page on another site cannot send here without being let:
            # that keeps such a page from spending the keys of a server started with --env-keys.
            if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
                raise Refused(415, "send JSON")
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                raise Refused(413, "too large")
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                raise Refused(400, "not JSON")
            if not isinstance(body, dict):
                raise Refused(400, "send a JSON object")
            if path == "/api/pages":
                return self._send(200, json.dumps({"id": desk.new_page(body)}))
            m = re.fullmatch(r"/api/pages/([^/]+)/(comment|ask|hide|flags)", path)
            if not m:
                raise Refused(404, "nothing here")
            pid, what = m.groups()
            got = getattr(desk, what)(pid, body)
            self._send(200, json.dumps({"ok": True, **({"round": got} if what == "ask" else {})}))
        self._answer(go)


def make_server(host="127.0.0.1", port=8000, pages_dir=None, env_keys=False, passages_dir=None):
    """The server, not yet serving; `server.desk` is its Desk."""
    desk = Desk(pages_dir, env_keys, passages_dir)
    server = ThreadingHTTPServer((host, port), type("Handler", (Handler,), {"desk": desk}))
    server.daemon_threads = True
    server.desk = desk
    return server
