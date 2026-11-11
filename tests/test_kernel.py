"""The viewer's kernel (radbinical/templates/kernel.js), run under Node."""
import json
import shutil
import subprocess
import unittest

from radbinical.config import TEMPLATES

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

    def test_a_box_starts_at_its_words_and_runs_to_where_the_next_starts(self):
        self.assertEqual(js('k.place([{want: 0}, {want: 100}, {want: 220}], 30, 10, 400)'),
                         [{"top": 0, "height": 90}, {"top": 100, "height": 110}, {"top": 220, "height": 180}])

    def test_crowded_boxes_move_down_and_keep_the_least(self):
        self.assertEqual(js('k.place([{want: 100}, {want: 100}, {want: 105}], 30, 10, 400)'),
                         [{"top": 100, "height": 30}, {"top": 140, "height": 30}, {"top": 180, "height": 220}])
        self.assertEqual(js("k.place([], 30)"), [])

    def test_the_last_box_runs_to_the_foot_of_the_text_or_keeps_the_least(self):
        self.assertEqual(js('k.place([{want: 0}, {want: 100}], 30, 10, 250)')[1], {"top": 100, "height": 150})
        self.assertEqual(js('k.place([{want: 240}], 30, 10, 250)'), [{"top": 240, "height": 30}])

    def test_a_comment_stands_on_the_side_its_words_begin_nearer_to(self):
        self.assertEqual(js('[k.nearer(10, 0, 100), k.nearer(50, 0, 100), k.nearer(51, 0, 100), k.nearer(430, 400, 800), k.nearer(700, 400, 800)]'),
                         [0, 0, 1, 0, 1])

    def test_boxes_too_close_to_each_have_room_make_a_stack(self):
        items = '[{want: 0}, {want: 5}, {want: 70}, {want: 100}, {want: 140}, {want: 300}]'
        self.assertEqual(js(f'k.stacks({items}, 60, 10)'), [[0, 1], [2, 3], [4], [5]])
        self.assertEqual(js(f'k.stacks({items}, 1)'), [[0], [1], [2], [3], [4], [5]])
        self.assertEqual(js('k.stacks([], 60)'), [])

    def test_every_stack_starts_at_the_words_of_its_first_comment_with_room_to_show(self):
        got = js("""(() => {
          const items = [0, 3, 40, 41, 44, 90, 200, 204, 260].map(want => ({want})), least = 50, gap = 5;
          const groups = k.stacks(items, least, gap);
          const boxes = k.place(groups.map(g => ({want: items[g[0]].want})), least, gap, 400);
          return groups.map((g, i) => [g, boxes[i].top - items[g[0]].want, boxes[i].height]);
        })()""")
        self.assertEqual(sum(len(g) for g, _, _ in got), 9)
        self.assertTrue(all(off == 0 for _, off, _ in got))
        self.assertTrue(all(h >= 50 for _, _, h in got))


if __name__ == "__main__":
    unittest.main()
