"""The viewer's kernel (radbinical/templates/kernel.js) run under Node, and its counterpart in page.py."""
import json
import shutil
import subprocess
import tempfile
import unittest

from radbinical.config import DEFAULT_FLAGS, TEMPLATES
from radbinical.page import Page, reader_entry, span

NODE = shutil.which("node")
TEXT = "The laws of production are fixed. Distribution is a matter of human institution solely."


def js(expr):
    """The value of a JavaScript expression that may use the kernel as `k`."""
    code = f"const k = require({json.dumps(str(TEMPLATES / 'kernel.js'))}); console.log(JSON.stringify({expr}))"
    return json.loads(subprocess.run([NODE, "-e", code], capture_output=True, text=True, check=True).stdout)


@unittest.skipUnless(NODE, "node is not installed")
class Kernel(unittest.TestCase):
    def test_a_comment_on_the_passage_carries_its_span(self):
        self.assertEqual(js('k.spanOf({target: "passage", start: 4, end: 22})'), [4, 22])

    def test_a_reply_is_where_its_quote_is_found_in_what_it_is_on(self):
        on = '{text: "One  line.\\nAnd a   second line."}'
        self.assertEqual(js(f'k.spanOf({{target: "c1", quote: "a second"}}, {on})'), [14, 22])
        self.assertEqual(js(f'k.shownText({on}).slice(14, 22)'), "a second")
        self.assertIsNone(js(f'k.spanOf({{target: "c1"}}, {on})'))                      # on the whole text
        self.assertIsNone(js(f'k.spanOf({{target: "c1", quote: "not there"}}, {on})'))

    def test_a_text_is_cut_where_spans_start_and_end(self):
        got = js('k.pieces("abcdefghij", [{id: "x", start: 2, end: 6}, {id: "y", start: 4, end: 8}, {id: "z", start: 2, end: 6}])')
        self.assertEqual([(p["start"], p["end"], p["on"], p["begins"]) for p in got],
                         [(0, 2, [], []), (2, 4, ["x", "z"], ["x", "z"]), (4, 6, ["x", "y", "z"], ["y"]), (6, 8, ["y"], []), (8, 10, [], [])])

    def test_pieces_cover_the_text_once_whatever_the_spans(self):
        got = js('k.pieces("abcdefghij", [{id: "a", start: -3, end: 4}, {id: "b", start: 7, end: 99}, {id: "c", start: 5, end: 5}], [3, 3, 10])')
        self.assertEqual("".join("abcdefghij"[p["start"]:p["end"]] for p in got), "abcdefghij")
        self.assertEqual([p["on"] for p in got], [["a"], ["a"], [], ["b"]])
        self.assertEqual(js('k.pieces("abc", [])'), [{"start": 0, "end": 3, "on": [], "begins": []}])

    def test_a_box_starts_at_its_words_and_is_cut_where_the_next_starts(self):
        got = js('k.place([{want: 0, height: 50}, {want: 100, height: 300}, {want: 220, height: 40}], 30, 10)')
        self.assertEqual(got, [{"top": 0, "height": 50, "cut": False}, {"top": 100, "height": 110, "cut": True},
                               {"top": 220, "height": 40, "cut": False}])

    def test_crowded_boxes_move_down_and_keep_the_least(self):
        got = js('k.place([{want: 100, height: 200}, {want: 100, height: 200}, {want: 105, height: 200}], 30, 10)')
        self.assertEqual([(b["top"], b["height"], b["cut"]) for b in got], [(100, 30, True), (140, 30, True), (180, 200, False)])
        self.assertEqual(js("k.place([], 30)"), [])

    def test_the_last_box_is_cut_at_the_foot_of_the_text(self):
        got = js('k.place([{want: 0, height: 50}, {want: 100, height: 300}], 30, 10, 250)')
        self.assertEqual(got[1], {"top": 100, "height": 150, "cut": True})
        self.assertEqual(js('k.place([{want: 240, height: 300}], 30, 10, 250)'), [{"top": 240, "height": 30, "cut": True}])
        self.assertEqual(js('k.place([{want: 0, height: 50}], 30, 10, 250)'), [{"top": 0, "height": 50, "cut": False}])

    def test_a_comment_stands_on_the_side_its_words_begin_nearer_to(self):
        self.assertEqual(js('[k.nearer(10, 0, 100), k.nearer(50, 0, 100), k.nearer(51, 0, 100), k.nearer(430, 400, 800), k.nearer(700, 400, 800)]'),
                         [0, 0, 1, 0, 1])

    def test_boxes_too_close_to_each_have_room_make_a_stack(self):
        items = '[{want: 0}, {want: 5}, {want: 20}, {want: 100}, {want: 105}, {want: 300}]'
        self.assertEqual(js(f'k.stacks({items}, 60, 10, 20)'), [[0, 1, 2], [3, 4], [5]])
        self.assertEqual(js(f'k.stacks({items}, 60, 10, 80)'), [[0], [1, 2], [3, 4], [5]])
        self.assertEqual(js(f'k.stacks({items}, 60, 10, 1000)'), [[0], [1], [2], [3], [4], [5]])   # enough slack: nothing stacks
        self.assertEqual(js('k.stacks([], 60)'), [])

    def test_a_stack_starts_within_the_slack_of_its_first_members_words(self):
        got = js("""(() => {
          const items = [0, 3, 40, 41, 44, 90, 200, 204, 260].map(want => ({want})), least = 50, gap = 5, slack = 25;
          const groups = k.stacks(items, least, gap, slack);
          const boxes = k.place(groups.map(g => ({want: items[g[0]].want, height: Infinity})), least, gap, 400);
          return groups.map((g, i) => [g, boxes[i].top - items[g[0]].want, boxes[i].height]);
        })()""")
        self.assertEqual(sum(len(g) for g, _, _ in got), 9)
        self.assertTrue(all(0 <= off <= 25 for _, off, _ in got))
        self.assertTrue(all(h >= 50 for _, _, h in got))


class Span(unittest.TestCase):
    """page.span: the same rule, for code that reads a page."""

    def test_span(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = Page({"passage": {"title": "T", "source": "", "text": TEXT}, "readers": [reader_entry("mock:a"), reader_entry("mock:b")],
                         "flags": dict(DEFAULT_FLAGS), "comments": [], "log": [], "counter": 0, "layers_done": 0}, tmp)
            page.add("a", 1, {"target": "passage", "quote": "laws of production", "text": "A gloss on  the laws.\nSecond line."})
            page.add("b", 2, {"target": "c1", "quote": "on the laws", "text": "reply"})
            page.add("b", 2, {"target": "c1", "text": "on the whole of it"})
            c1, c2, c3 = page.d["comments"]
            self.assertEqual(TEXT[slice(*span(page.d, c1))], "laws of production")
            s, e = span(page.d, c2)
            self.assertEqual(c1["text"][s:e], "on  the laws")
            self.assertIsNone(span(page.d, c3))


if __name__ == "__main__":
    unittest.main()
