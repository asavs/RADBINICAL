"""The served page (radbinical/serve.py): bare pages, a person's comments, rounds and asked turns
from stand-in readers, comments taken off the page, and keys that come with a request."""
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from radbinical.page import Page, render_for_reader
from radbinical.providers import http
from radbinical.rounds import take_turn
from radbinical.serve import Desk, Refused, make_server

TEXT = "The land was open. Later the land was locked up.\n\nA second paragraph about the land."


class Served(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.desk = Desk(Path(self.tmp.name) / "pages", passages_dir=Path(self.tmp.name) / "passages")
        self.pid = self.desk.new_page({"title": "On Land", "text": TEXT})

    def tearDown(self):
        self.tmp.cleanup()

    def page(self):
        return json.loads(self.desk.state(self.pid))["page"]

    def settle(self):
        for _ in range(200):
            if not self.desk.pending.get(self.pid):
                return
            time.sleep(0.02)
        self.fail("the round did not finish")

    def test_a_page_opens_bare_and_is_kept(self):
        d = self.page()
        self.assertEqual((d["comments"], d["readers"], d["layers_done"]), ([], [], 0))
        self.assertEqual(d["passage"]["text"], TEXT)
        self.assertEqual(Page.load(self.desk.dir / self.pid).d["passage"]["title"], "On Land")

    def test_a_page_is_found_only_by_its_id(self):
        for pid in ("nope", "../" + self.pid, "a" * 16):
            with self.assertRaises(Refused):
                self.desk.get(pid)

    def test_a_persons_comment_stands_on_the_words_selected_not_their_first_occurrence(self):
        second = TEXT.index("the land")
        self.desk.comment(self.pid, {"name": "Asa", "text": "Which?", "quote": "the land", "span": [second, second + 8]})
        d = self.page()
        c = d["comments"][0]
        self.assertEqual((c["start"], c["author"], c["kind"], c["layer"]), (second, "Asa", "human", 1))
        self.assertTrue(d["readers"][0]["human"])
        self.assertEqual(d["layers_done"], 1)

    def test_a_span_that_does_not_hold_the_quote_falls_back_to_the_quote(self):
        self.desk.comment(self.pid, {"name": "Asa", "text": "Which?", "quote": "locked up", "span": [0, 9]})
        c = self.page()["comments"][0]
        self.assertEqual(TEXT[c["start"]:c["end"]], "locked up")

    def test_a_round_is_taken_by_the_models_named_and_adds_them_as_readers(self):
        self.assertEqual(self.desk.ask(self.pid, {"models": ["mock:alpha", {"model": "mock:beta", "name": "Beta"}]}), 1)
        self.settle()
        d = self.page()
        self.assertEqual([r["name"] for r in d["readers"]], ["alpha", "Beta"])
        self.assertEqual(sorted(e["reader"] for e in d["log"]), ["Beta", "alpha"])
        self.assertTrue(all(c["layer"] == 1 for c in d["comments"]))
        self.assertIn("prompt_example", d)
        self.assertEqual(self.desk.ask(self.pid, {"models": ["mock:alpha"]}), 2)   # the same reader again
        self.settle()
        self.assertEqual(len(self.page()["readers"]), 2)

    def test_a_requested_comment_goes_on_exactly_the_words_asked_about(self):
        third = TEXT.rindex("the land")
        page = self.desk.get(self.pid)
        reply = '<comment on="passage"><quote>The land was open</quote>An answer.</comment><comment on="passage"><quote>locked up</quote>More.</comment>'
        with mock.patch("radbinical.rounds.open_session") as opened:
            opened.return_value.step.return_value = (reply, {})
            opened.return_value.truncated = False
            ask = {"target": "passage", "quote": "the land", "span": [third, third + 8]}
            take_turn(page, {"name": "alpha", "model": "mock:alpha"}, 1, lambda me: [], lambda a: a, "note", ask)
        (c,) = page.d["comments"]
        self.assertEqual((c["start"], c["end"], c["text"]), (third, third + 8, "An answer."))
        self.assertEqual(page.d["log"][-1]["asked"], {"target": "passage", "quote": "the land"})

    def test_a_request_can_be_about_words_of_a_comment(self):
        self.desk.comment(self.pid, {"name": "Asa", "text": "Open to whom?\nOpen to whom, exactly?", "quote": "open"})
        self.desk.ask(self.pid, {"models": ["mock:alpha"], "on": {"target": "c1", "quote": "Open to whom", "span": [14, 26]}})
        self.settle()
        d = self.page()
        asked = [e for e in d["log"] if e.get("asked")]
        self.assertEqual(asked[0]["asked"], {"target": "c1", "quote": "Open to whom"})
        for c in d["comments"][1:]:   # the stand-in may pass; what it writes is on those words
            self.assertEqual((c["target"], c["start"], c["end"]), ("c1", 14, 26))

    def test_asking_about_a_comment_that_is_not_there_is_refused(self):
        with self.assertRaises(Refused):
            self.desk.ask(self.pid, {"models": ["mock:alpha"], "on": {"target": "c9"}})
        for models in ([], ["human:asa"], ["not a model id"], ["mock:a"] * 9):
            with self.assertRaises(Refused):
                self.desk.ask(self.pid, {"models": models})

    def test_a_comment_taken_off_the_page_is_kept_but_not_shown_to_readers(self):
        self.desk.comment(self.pid, {"name": "Asa", "text": "Stays.", "quote": "open"})
        self.desk.comment(self.pid, {"name": "Asa", "text": "Goes.", "quote": "locked up"})
        self.desk.hide(self.pid, {"id": "c2", "hidden": True})
        d = self.page()
        self.assertTrue(d["comments"][1]["hidden"])
        from radbinical.page import on_page
        seen = render_for_reader(d, on_page(d), lambda a: a, None)
        self.assertIn("Stays.", seen)
        self.assertNotIn("Goes.", seen)
        self.desk.hide(self.pid, {"id": "c2", "hidden": False})
        self.assertNotIn("hidden", self.page()["comments"][1])

    def test_the_viewer_is_told_when_nothing_has_changed(self):
        v = json.loads(self.desk.state(self.pid))["v"]
        self.assertEqual(json.loads(self.desk.state(self.pid, v)), {"v": v, "same": True})
        self.desk.flags(self.pid, {"signed": False})
        self.assertIn("page", json.loads(self.desk.state(self.pid, v)))

    def test_the_served_page_carries_its_controls_and_a_rendered_one_does_not(self):
        from radbinical.site import page_html
        self.assertIn("function live(", self.desk.html(self.pid))
        self.assertNotIn("function live(", page_html(self.page()))


class Keys(unittest.TestCase):
    def in_thread(self, f):
        out = []
        t = threading.Thread(target=lambda: out.append(f()))
        t.start()
        t.join()
        return out[0]

    def test_a_key_given_with_a_request_is_used_and_the_environment_only_when_allowed(self):
        with mock.patch.dict("os.environ", {"OPENROUTER_API_KEY": "from-env", "XAI_API_KEY": "x-env"}):
            def given():
                http.use_keys({"openrouter": "from-request", "bogus": "x"}, env=False)
                return http.api_key("openrouter"), http.api_key("xai")
            def allowed():
                http.use_keys({"openrouter": "from-request"}, env=True)
                return http.api_key("openrouter"), http.api_key("xai")
            self.assertEqual(self.in_thread(given), ("from-request", None))
            self.assertEqual(self.in_thread(allowed), ("from-request", "x-env"))
            self.assertEqual(http.api_key("openrouter"), "from-env")   # other threads are untouched

    def test_the_given_key_is_the_one_sent_and_none_given_sends_nothing(self):
        def send():
            http.use_keys({"openrouter": "from-request"}, env=False)
            with mock.patch("urllib.request.urlopen") as opened:
                opened.return_value.__enter__.return_value.read.return_value = b'{"choices": [{"message": {"content": "ok"}}]}'
                http.post_json("https://example.invalid", "openrouter", {"model": "m"})
                return opened.call_args[0][0].get_header("Authorization")
        self.assertEqual(self.in_thread(send), "Bearer from-request")

        def none():
            http.use_keys({}, env=False)
            with mock.patch("urllib.request.urlopen") as opened:
                try:
                    http.post_json("https://example.invalid", "openrouter", {"model": "m"})
                except RuntimeError as e:
                    return str(e), opened.called
        self.assertEqual(self.in_thread(none), ("no openrouter key was given", False))


class OverHTTP(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = make_server("127.0.0.1", 0, Path(self.tmp.name) / "pages")
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def send(self, path, body=None, kind="application/json"):
        req = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": kind} if body is not None else {})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def test_the_library_a_new_page_and_writing_on_it(self):
        status, lib = self.send("/api/library")
        passages = json.loads(lib)["passages"]
        self.assertEqual(status, 200)
        self.assertIn("read-poor-support", [p["id"] for p in passages])
        self.assertTrue(all(p["title"] and p["text"] for p in passages))
        status, made = self.send("/api/pages", {"passage": "read-poor-support"})
        pid = json.loads(made)["id"]
        self.assertEqual(self.send(f"/p/{pid}")[0], 200)
        self.assertEqual(self.send(f"/api/pages/{pid}/comment", {"name": "Asa", "text": "Why?", "quote": "the land"})[0], 200)
        self.assertEqual(len(json.loads(self.send(f"/api/pages/{pid}")[1])["page"]["comments"]), 1)
        self.assertEqual(self.send("/")[0], 200)

    def test_what_is_refused(self):
        self.assertEqual(self.send("/api/pages", {"passage": "read-poor-support"}, kind="text/plain")[0], 415)
        self.assertEqual(self.send("/api/pages", {"passage": "no-such"})[0], 404)
        self.assertEqual(self.send("/api/pages/aaaaaaaaaaaaaaaa")[0], 404)
        self.assertEqual(self.send("/p/..%2F..%2Fx")[0], 404)
        self.assertEqual(self.send("/api/pages", {"title": "T", "text": ""})[0], 400)


if __name__ == "__main__":
    unittest.main()
