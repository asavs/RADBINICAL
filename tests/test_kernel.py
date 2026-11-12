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

    def test_a_reply_that_stores_its_span_is_there_and_not_where_its_quote_first_occurs(self):
        on = '{text: "the land, and again the land"}'
        self.assertEqual(js(f'k.spanOf({{target: "c1", quote: "the land", start: 20, end: 28}}, {on})'), [20, 28])
        self.assertEqual(js(f'k.spanOf({{target: "c1", quote: "the land"}}, {on})'), [0, 8])

    def test_a_text_is_cut_where_spans_start_and_end(self):
        got = js('k.pieces("abcdefghij", [{id: "x", start: 2, end: 6}, {id: "y", start: 4, end: 8}, {id: "z", start: 2, end: 6}])')
        self.assertEqual([(p["start"], p["end"], p["on"], p["begins"]) for p in got],
                         [(0, 2, [], []), (2, 4, ["x", "z"], ["x", "z"]), (4, 6, ["x", "y", "z"], ["y"]), (6, 8, ["y"], []), (8, 10, [], [])])
        self.assertEqual([p["ends"] for p in got], [[], [], ["x", "z"], ["y"], []])

    def test_pieces_cover_the_text_once_whatever_the_spans(self):
        got = js('k.pieces("abcdefghij", [{id: "a", start: -3, end: 4}, {id: "b", start: 7, end: 99}, {id: "c", start: 5, end: 5}], [3, 3, 10])')
        self.assertEqual("".join("abcdefghij"[p["start"]:p["end"]] for p in got), "abcdefghij")
        self.assertEqual([p["on"] for p in got], [["a"], ["a"], [], ["b"]])
        self.assertEqual(js('k.pieces("abc", [])'), [{"start": 0, "end": 3, "on": [], "begins": [], "ends": []}])

    def test_a_comment_is_written_at_the_edge_its_words_end_nearest(self):
        got = js('[k.edge(10, 500, 400, 1000), k.edge(390, 500, 400, 1000), k.edge(200, 30, 400, 1000), k.edge(200, 980, 400, 1000)]')
        self.assertEqual(got, ["left", "right", "above", "below"])
        self.assertEqual(js('[k.edge(30, 30, 400, 1000), k.edge(370, 970, 400, 1000), k.edge(200, 500, 400, 1000)]'),
                         ["left", "right", "left"])   # a side wins a tie, and the left one the dead centre

    def test_a_note_with_room_starts_level_with_its_words(self):
        self.assertEqual(js('k.stack([{want: 0, h: 50}, {want: 100, h: 80}, {want: 400, h: 30}], 10)'), [0, 100, 400])
        self.assertEqual(js('k.stack([], 10)'), [])
        self.assertEqual(js('k.stack([{want: -40, h: 50}], 10)'), [-40])

    def test_a_note_with_room_to_spare_gives_way_to_the_one_above(self):
        # the second's words end 70 below the first's, which is 160 high; the second is last, so the margin below it is open
        self.assertEqual(js('k.stack([{want: 300, h: 160}, {want: 370, h: 100}], 10)'), [300, 470])
        # the same when it can end before the next note's words
        self.assertEqual(js('k.stack([{want: 300, h: 160}, {want: 370, h: 100}, {want: 900, h: 50}], 10)'), [300, 470, 900])

    def test_a_note_gives_way_only_so_far_before_the_ones_above_move_up_too(self):
        # the first is 400 high, so the second would start 340 low; it gives 50 on its own and they halve the other 290
        self.assertEqual(js('k.stack([{want: 300, h: 400}, {want: 370, h: 100}], 10, 50)'), [155, 565])
        # within what it gives on its own, nothing above moves
        self.assertEqual(js('k.stack([{want: 300, h: 100}, {want: 370, h: 100}], 10, 50)'), [300, 410])
        # and the ones above move up only as far as the margin above them is free
        self.assertEqual(js('k.stack([{want: 0, h: 200}, {want: 300, h: 400}, {want: 370, h: 100}], 10, 50)'), [0, 210, 620])

    def test_a_note_without_room_keeps_its_place_and_the_ones_above_move_up(self):
        # moved down, the second would run into the third's words; the margin above the first is free
        self.assertEqual(js('k.stack([{want: 300, h: 160}, {want: 370, h: 100}, {want: 480, h: 50}], 10)'), [200, 370, 480])
        # the same below a note that leaves enough free margin
        self.assertEqual(js('k.stack([{want: 0, h: 150}, {want: 300, h: 160}, {want: 370, h: 100}, {want: 480, h: 50}], 10)'), [0, 200, 370, 480])

    def test_with_too_little_free_margin_above_the_rest_is_made_up_below(self):
        # only 40 is free above the second, which needs to rise 100: the third starts 60 low, and the last, with open margin, gives way
        self.assertEqual(js('k.stack([{want: 0, h: 250}, {want: 300, h: 160}, {want: 370, h: 100}, {want: 480, h: 50}], 10)'), [0, 260, 430, 540])

    def test_stacked_notes_never_overlap_and_none_is_cut(self):
        got = js("""(() => {
          const items = Array.from({length: 60}, (_, i) => ({want: (i * 37) % 500 + i * 9, h: 40 + (i * 53) % 120})).sort((a, b) => a.want - b.want);
          const tops = k.stack(items, 8);
          return tops.every((y, i) => !i || y >= tops[i - 1] + items[i - 1].h + 8 - 1e-6);
        })()""")
        self.assertTrue(got)


if __name__ == "__main__":
    unittest.main()
