import json
import tempfile
import unittest
from pathlib import Path

from radbinical.anchoring import locate, snap_to_sentences
from radbinical.config import DEFAULT_FLAGS, ROOT
from radbinical.page import Page, load_passage, reader_entry, render_for_reader
from radbinical.providers import TextSession, split_model
from radbinical.rounds import run_layers

TEXT = "The laws of production are fixed. Distribution is “a matter of human institution solely.”\n\nA second paragraph."


def new_page(tmp, readers=("mock:alef", "mock:bet"), text=TEXT, **flags):
    data = {"passage": {"title": "T", "source": "", "text": text},
            "readers": [reader_entry(m) for m in readers],
            "flags": {**DEFAULT_FLAGS, **flags}, "comments": [], "log": [], "counter": 0, "layers_done": 0}
    return Page(data, tmp)


class Anchoring(unittest.TestCase):
    def test_exact(self):
        s, e = locate(TEXT, "laws of production")
        self.assertEqual(TEXT[s:e], "laws of production")

    def test_tolerates_case_spacing_and_quote_style(self):
        s, e = locate(TEXT, '"A  matter of HUMAN institution solely."')
        self.assertEqual(TEXT[s:e], "“a matter of human institution solely.”")

    def test_missing(self):
        self.assertIsNone(locate(TEXT, "surplus value"))

    def test_snap_to_sentence(self):
        s, e = snap_to_sentences(TEXT, *locate(TEXT, "human institution"))
        self.assertTrue(TEXT[s:e].startswith("Distribution is"))
        self.assertTrue(TEXT[s:e].endswith("solely.”"))


class Annotating(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.page = new_page(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_comment_then_reply(self):
        ok, msg = self.page.add("alef", 1, {"target": "passage", "quote": "laws of production", "text": "gloss"})
        self.assertTrue(ok)
        self.assertIn("c1", msg)
        ok, _ = self.page.add("bet", 2, {"target": "c1", "text": "reply", "see_also": ["c1", "c99"]})
        self.assertTrue(ok)
        self.assertEqual(self.page.d["comments"][1]["see_also"], ["c1"])

    def test_rejections(self):
        for args in ({"target": "passage", "text": "no quote"},
                     {"target": "passage", "quote": "not in the text", "text": "x"},
                     {"target": "c42", "text": "x"},
                     {"target": "passage", "quote": "laws", "text": "  "}):
            ok, msg = self.page.add("alef", 1, args)
            self.assertFalse(ok, args)
            self.assertTrue(msg.startswith("Not recorded"))
        self.assertEqual(self.page.d["comments"], [])

    def test_reader_view_marks_own_comments(self):
        self.page.add("alef", 1, {"target": "passage", "quote": "laws of production", "text": "gloss"})
        view = render_for_reader(self.page.d, self.page.d["comments"], lambda a: a, "alef")
        self.assertIn("[c1] alef (you), on the passage", view)

    def test_kind_and_meta_are_stored_but_never_shown(self):
        ok, _ = self.page.add("alef", 1, {"target": "passage", "quote": "laws of production", "text": "slip"},
                              kind="plant", meta={"truth": "SECRET-TRUTH"})
        self.assertTrue(ok)
        self.page.add("bet", 2, {"target": "c1", "text": "reply"}, kind="human", meta={"by": "SECRET-PERSON"})
        c1, c2 = self.page.d["comments"]
        self.assertEqual((c1["kind"], c1["meta"]), ("plant", {"truth": "SECRET-TRUTH"}))
        self.assertEqual(c2["kind"], "human")
        self.page.add("bet", 2, {"target": "c1", "text": "own"})
        self.assertNotIn("kind", self.page.d["comments"][2])
        view = render_for_reader(self.page.d, self.page.d["comments"], lambda a: a, "bet")
        for hidden in ("plant", "SECRET", "kind", "meta"):  # "human" is in the passage itself
            self.assertNotIn(hidden, view)

    def test_side_files(self):
        self.assertIsNone(self.page.side("redactions"))
        self.page.save()
        self.page.save_side("redactions", {"items": ["é"], "usage": [{"cost": 0.5}]})
        self.assertEqual(Page.load(self.tmp.name).side("redactions")["items"], ["é"])
        with self.assertRaises(ValueError):
            self.page.save_side("page", {})


class Providers(unittest.TestCase):
    def test_split_model(self):
        self.assertEqual(split_model("anthropic:claude-opus-5-5"), ("anthropic", "claude-opus-5-5"))
        self.assertEqual(split_model("qwen/qwen3.8-27b:batch"), ("openrouter", "qwen/qwen3.8-27b:batch"))

    def test_text_blocks_are_parsed(self):
        s = TextSession("nvidia", "m", "sys", "user", dict(DEFAULT_FLAGS), 100)
        s._send = lambda with_tools=True: ({"content": 'Hm.\n<annotate target="passage" quote="laws" see_also="c1, c2">\nA gloss.\n</annotate>'}, {})
        calls, text, _ = s.step()
        self.assertEqual(calls, [("0", {"target": "passage", "quote": "laws", "text": "A gloss.", "see_also": ["c1", "c2"]})])
        self.assertEqual(text, "Hm.")

    def test_text_blocks_left_open(self):
        s = TextSession("nvidia", "m", "sys", "user", dict(DEFAULT_FLAGS), 100)
        s._send = lambda with_tools=True: ({"content": '<annotate target="c8" quote="x y">\nOne.\n\n<annotate target="passage" quote="laws">\nTwo.</annotate>\n<annotate target="c1">Three.'}, {})
        calls, text, _ = s.step()
        self.assertEqual([(a["target"], a["text"]) for _, a in calls], [("c8", "One."), ("passage", "Two."), ("c1", "Three.")])
        self.assertEqual(text, "")

    def test_text_turn_ends_once_every_block_is_recorded(self):
        s = TextSession("nvidia", "m", "sys", "user", dict(DEFAULT_FLAGS), 100)
        sent = []
        def send(with_tools=True):
            sent.append(list(s.messages))
            return {"content": '<annotate target="passage" quote="laws">A.</annotate><annotate target="c9">B.</annotate>'}, {}
        s._send = send
        calls, _, _ = s.step()
        self.assertEqual(len(calls), 2)
        s.reply([("0", "Recorded as c1."), ("1", 'Not recorded: no comment with id "c9".')])
        self.assertIn("Block 2: Not recorded", s.messages[-1]["content"])
        calls, _, _ = s.step()
        s.reply([("0", "Recorded as c2."), ("1", "Recorded as c3.")])
        self.assertEqual(s.step(), ([], "", {}))
        self.assertEqual(len(sent), 2)

    def test_text_comments_in_another_shape_are_sent_back(self):
        s = TextSession("nvidia", "m", "sys", "user", dict(DEFAULT_FLAGS), 100)
        answers = iter(['{annotations: [{"target": "c3", "text": "x"}]}', '<annotate target="c3">x</annotate>'])
        s._send = lambda with_tools=True: ({"content": next(answers)}, {"cost": 0.1})
        calls, _, usage = s.step()
        self.assertEqual(calls, [("0", {"target": "c3", "quote": "", "text": "x"})])
        self.assertEqual(usage, {"cost": 0.2})
        self.assertIn("Nothing was recorded", s.messages[-2]["content"])
        s2 = TextSession("nvidia", "m", "sys", "user", dict(DEFAULT_FLAGS), 100)
        s2._send = lambda with_tools=True: ({"content": "Nothing further this round."}, {})
        self.assertEqual(s2.step()[0], [])
        self.assertEqual(len(s2.messages), 3)

    def test_text_retries_are_capped(self):
        s = TextSession("nvidia", "m", "sys", "user", dict(DEFAULT_FLAGS), 100)
        s._send = lambda with_tools=True: ({"content": '<annotate target="c9">B.</annotate>'}, {})
        for _ in range(TextSession.RETRIES + 1):
            self.assertEqual(len(s.step()[0]), 1)
            s.reply([("0", "Not recorded: no.")])
        self.assertEqual(s.step(), ([], "", {}))


class Brands(unittest.TestCase):
    def test_maker_is_found_from_the_model_id(self):
        from radbinical.site import brand_of, load_brands
        brands = load_brands()
        for model, name in (("anthropic:claude-opus-5-5", "Anthropic"), ("openai/gpt-oss-120b", "OpenAI"),
                            ("openai:gpt-6.1-sol", "OpenAI"), ("nvidia:nvidia/nemotron-3-ultra-550b-a55b", "NVIDIA"),
                            ("qwen/qwen3.8-27b:batch", "Alibaba")):
            self.assertEqual(brand_of({"model": model}, brands)["name"], name)
        self.assertIsNone(brand_of({"model": "thinkingmachines/inkling"}, brands))
        self.assertEqual(brand_of({"model": "some/finetune", "brand": "nousresearch"}, brands)["name"], "Nous Research")


class EndToEnd(unittest.TestCase):
    def test_mock_run_writes_record_and_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = new_page(tmp, text=load_passage(ROOT / "passages" / "mill-property.txt"))
            self.assertTrue(run_layers(page, 2))
            saved = json.loads((Path(tmp) / "page.json").read_text(encoding="utf-8"))
            self.assertGreaterEqual(saved["layers_done"], 1)
            self.assertGreater(len(saved["comments"]), 0)
            self.assertIn("const D = {", (Path(tmp) / "page.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
