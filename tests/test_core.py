import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from radbinical.anchoring import locate, snap_to_sentences
from radbinical.config import DEFAULT_FLAGS, ROOT
from radbinical.page import Page, load_passage, reader_entry, render_for_reader
from radbinical import rounds
from radbinical.prompts import read_reply, system_prompt
from radbinical.providers import split_model
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


class Reply(unittest.TestCase):
    """How a reader's one reply is read."""

    def test_blocks_are_read(self):
        comments, note, wrong = read_reply('Hm.\n<comment on="passage" see="c1, c2">\n<quote>laws</quote>\nA gloss.\n</comment>\nBye.')
        self.assertEqual(comments, [{"target": "passage", "quote": "laws", "text": "A gloss.", "see_also": ["c1", "c2"]}])
        self.assertEqual((note, wrong), ("Hm.\n\nBye.", False))

    def test_a_quote_may_hold_quotation_marks(self):
        [c], _, _ = read_reply("""<comment on='passage'><quote>a man "guilty" who takes</quote>Why the scare quotes?</comment>""")
        self.assertEqual((c["quote"], c["text"]), ('a man "guilty" who takes', "Why the scare quotes?"))

    def test_blocks_left_open_end_at_the_next(self):
        comments, note, _ = read_reply('<comment on="c8"><quote>x y</quote>\nOne.\n\n<comment on=passage>\n<quote>laws</quote>Two.</comment>\n<comment on="c1">Three.')
        self.assertEqual([(c["target"], c["quote"], c["text"]) for c in comments],
                         [("c8", "x y", "One."), ("passage", "laws", "Two."), ("c1", "", "Three.")])
        self.assertEqual(note, "")

    def test_a_reply_cut_off_loses_only_its_unfinished_block(self):
        text = '<comment on="c1">Whole.</comment><comment on="c2">Half a thou'
        self.assertEqual([c["text"] for c in read_reply(text, truncated=True)[0]], ["Whole."])
        self.assertEqual([c["text"] for c in read_reply(text)[0]], ["Whole.", "Half a thou"])
        self.assertEqual(len(read_reply('<comment on="c1">Whole.</comment>', truncated=True)[0]), 1)

    def test_comments_in_another_shape_are_noticed(self):
        self.assertEqual(read_reply('{"comments": [{"on": "c3", "text": "x"}]}')[::2], ([], True))
        self.assertEqual(read_reply('<annotate target="c3">x</annotate>')[::2], ([], True))
        self.assertEqual(read_reply("Nothing further this round; I will pass on: this one.")[::2], ([], False))

    def test_every_reader_is_told_the_same(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = new_page(tmp).d
            told = system_prompt(d, "alef", lambda a: a)
            self.assertIn('<comment on="passage">', told)
            self.assertIn('see="c2 c5"', told)
            self.assertNotIn("see=", system_prompt({**d, "flags": {**d["flags"], "cross_refs": False}}, "alef", lambda a: a))


class Script:
    """A session that gives scripted answers and keeps what it was told."""
    via, truncated = "script", False

    def __init__(self, *answers, cut=False):
        self.answers, self.told, self.cut = list(answers), [], cut

    def step(self):
        self.truncated = self.cut and len(self.answers) == 1
        return self.answers.pop(0), {"cost": 0.1}

    def say(self, text):
        self.told.append(text)


class Turn(unittest.TestCase):
    """A turn is one reply; what could not be recorded is sent back once."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.page = new_page(self.tmp.name)
        self.real = rounds.open_session

    def tearDown(self):
        rounds.open_session = self.real
        self.tmp.cleanup()

    def turn(self, session):
        rounds.open_session = lambda *a, **k: session
        with contextlib.redirect_stdout(io.StringIO()):
            rounds.take_turn(self.page, self.page.d["readers"][0], 1, lambda me: [], lambda a: a, "")
        return self.page.d["log"][-1]

    def test_one_reply_is_the_turn(self):
        s = Script('A thought.\n<comment on="passage"><quote>laws of production</quote>A.</comment><comment on="passage"><quote>fixed</quote>B.</comment>')
        entry = self.turn(s)
        self.assertEqual((entry["comments"], entry["replies"], entry["closing"], s.told), (2, 1, "A thought.", []))
        self.assertNotIn("refused", entry)
        self.assertEqual([c["text"] for c in self.page.d["comments"]], ["A.", "B."])

    def test_refused_comments_are_sent_back_once(self):
        first = '<comment on="passage"><quote>laws of production</quote>A.</comment><comment on="passage"><quote>not in it</quote>B.</comment>'
        s = Script(first, '<comment on="passage"><quote>still not in it</quote>B.</comment>', "never asked for")
        entry = self.turn(s)
        self.assertEqual((entry["comments"], entry["replies"], entry["refused"], entry["usage"]["cost"]), (1, 2, 1, 0.2))
        self.assertEqual(len(s.told), 1)
        self.assertIn('Comment 2 (on "passage"): Not recorded: that quote was not found', s.told[0])
        self.assertNotIn("Comment 1", s.told[0])
        self.assertEqual(len(s.answers), 1)

    def test_a_repaired_comment_is_recorded(self):
        s = Script('<comment on="c9">B.</comment>', '<comment on="passage"><quote>fixed</quote>B.</comment>')
        entry = self.turn(s)
        self.assertEqual((entry["comments"], entry["replies"]), (1, 2))
        self.assertNotIn("refused", entry)

    def test_another_shape_is_sent_back_once(self):
        s = Script('{"comments": [{"on": "passage", "quote": "fixed", "text": "x"}]}', '<comment on="passage"><quote>fixed</quote>x</comment>')
        entry = self.turn(s)
        self.assertEqual((entry["comments"], entry["replies"]), (1, 2))
        self.assertIn("Nothing was recorded", s.told[0])

    def test_passing_takes_one_reply(self):
        entry = self.turn(Script("Nothing further this round."))
        self.assertEqual((entry["comments"], entry["replies"], entry["closing"]), (0, 1, "Nothing further this round."))

    def test_a_reply_cut_off_keeps_its_whole_comments_and_is_marked(self):
        s = Script('<comment on="passage"><quote>fixed</quote>A.</comment><comment on="passage"><quote>laws</quote>Half a', cut=True)
        entry = self.turn(s)
        self.assertEqual((entry["comments"], entry["replies"], s.told), (1, 1, []))
        self.assertIn("stopped at max_tokens", entry["error"])

    def test_the_comment_limit_ends_the_turn_quietly(self):
        self.page.d["flags"]["max_comments_per_turn"] = 1
        s = Script('<comment on="passage"><quote>fixed</quote>A.</comment><comment on="passage"><quote>laws</quote>B.</comment>')
        entry = self.turn(s)
        self.assertEqual((entry["comments"], entry["replies"], s.told), (1, 1, []))


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
