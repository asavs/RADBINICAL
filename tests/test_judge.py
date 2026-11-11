import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from radbinical import ask as ask_mod
from radbinical.cli import main
from radbinical.commands.plant import add_plant
from radbinical.judge import (chunks, judge_claims, judge_plants, read_verdicts, replies_to, summarise_plant,
                              summary)
from test_plant import make_page


def run(argv):
    with contextlib.redirect_stdout(io.StringIO()) as out:
        main(argv)
    return out.getvalue()


def planted(d):
    """Page with a slip c3 (round 2) and a sound reading c4 (round 2), and replies in rounds 3 and 4.

    c5 bet r3 -> c3          c6 alef r3 -> c5 (nested)     c7 bet r3 on passage, see_also c3
    c8 alef r4 -> c6 (deep)  c9 bet r3 -> c4               c10 alef r3 -> c1 (unrelated)
    """
    page = make_page(d)
    add_plant(page, {"as": "alef", "sort": "slip", "target": "c1", "text": "Mill wrote this in 1859.", "truth": "1848."})
    add_plant(page, {"as": "bet", "sort": "sound", "target": "passage", "quote": "human institution",
                     "text": "Institution here means law.", "truth": "Mill uses it so in Book II."})
    page.add("bet", 3, {"target": "c3", "text": "Surely 1848?"})
    page.add("alef", 3, {"target": "c5", "text": "Yes, I misdated it."})
    page.add("bet", 3, {"target": "passage", "quote": "physical truths", "text": "Compare.", "see_also": ["c3"]})
    page.add("alef", 4, {"target": "c6", "text": "Moving on."})
    page.add("bet", 3, {"target": "c4", "text": "Nonsense, institution means custom."})
    page.add("alef", 3, {"target": "c1", "text": "Unrelated."})
    page.save()
    return page


def hook_from(answers, calls=None):
    """An ask.HOOK that returns answers[i] (a string, or a callable of the user message) on call i."""
    state = {"i": 0}

    def hook(model, system, user, max_tokens, temperature):
        a = answers[state["i"]]
        state["i"] += 1
        if calls is not None:
            calls.append((model, system, user))
        return (a(user) if callable(a) else a), {"cost": 0.001}
    return hook


class Plants(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "r"
        self.dir.mkdir()
        self.page = planted(self.dir)

    def tearDown(self):
        ask_mod.HOOK = None
        self.tmp.cleanup()

    def test_reply_gathering(self):
        d = self.page.d
        self.assertEqual([c["id"] for c in replies_to(d, "c3")], ["c5", "c6", "c7", "c8"])
        self.assertEqual([c["id"] for c in replies_to(d, "c4")], ["c9"])
        self.assertEqual(replies_to(d, "c9"), [])

    def test_aggregation(self):
        plant = self.page.d["comments"][2]
        reps = [{"id": "c5", "author": "bet", "round": 4, "verdict": "catches", "why": ""},
                {"id": "c6", "author": "alef", "round": 3, "verdict": "catches", "why": ""},
                {"id": "c7", "author": "bet", "round": 3, "verdict": "ignores", "why": ""},
                {"id": "c8", "author": "alef", "round": 5, "verdict": None, "why": ""}]
        e = summarise_plant(plant, reps)
        # c3 is filed under alef, so alef's catch in round 3 does not count; bet's in round 4 does
        self.assertEqual((e["caught"], e["by"], e["caught_round"], e["rounds_to_catch"]), (True, ["bet"], 4, 2))
        self.assertEqual(e["counts"], {"catches": 1, "accepts": 0, "ignores": 1, "dismisses": 0})
        self.assertEqual([r.get("nominal_author", False) for r in e["replies"]], [False, True, False, True])
        e = summarise_plant(plant, [r for r in reps if r["author"] == "alef"])
        self.assertEqual((e["caught"], e["by"], e["caught_round"], len(e["replies"])), (False, [], None, 2))
        e = summarise_plant(plant, [{**r, "verdict": "accepts"} for r in reps])
        self.assertEqual((e["caught"], e["by"], e["caught_round"], e["rounds_to_catch"]), (False, [], None, None))
        sound = self.page.d["comments"][3]
        # c4 is filed under bet, so bet's dismissal does not count; alef's does
        e = summarise_plant(sound, [{**reps[0], "verdict": "dismisses"}, {**reps[1], "verdict": "catches"}])
        self.assertEqual((e["caught"], e["dismissed"], e["dismissed_by"], e["dismissed_round"]), (False, False, [], None))
        e = summarise_plant(sound, [{**reps[0], "verdict": "dismisses"}, {**reps[1], "verdict": "dismisses"}])
        self.assertEqual((e["dismissed"], e["dismissed_by"], e["dismissed_round"]), (True, ["alef"], 3))

    def test_command_end_to_end(self):
        calls = []

        def answer_c3(user):
            self.assertIn("1848.", user)               # the truth note
            self.assertIn("Yes, I misdated it.", user)  # nested reply text
            self.assertIn("(in reply to [c5] by bet: Surely 1848?)", user)
            self.assertIn("names it in see also", user)
            return ('```json\n{"replies": [{"id": "c5", "verdict": "catches", "why": "gives 1848"},'
                    ' {"id": "[c6]", "verdict": "Accepts", "why": "concedes"},'
                    ' {"id": "c7", "verdict": "ignores", "why": ""}, {"id": "c8", "verdict": "ignores"}]}\n```')

        ask_mod.HOOK = hook_from([answer_c3, '[{"id": "c9", "verdict": "dismissed", "why": "rejects it"}]'], calls)
        out = run(["judge", "plants", str(self.dir), "--judge", "mock:j"])
        self.assertEqual(len(calls), 2)
        res = json.loads((self.dir / "plants.json").read_text(encoding="utf-8"))
        slip, sound = res["plants"]
        self.assertEqual(res["judge"], "mock:j")
        self.assertEqual((slip["id"], slip["sort"], slip["author"], slip["round"]), ("c3", "slip", "alef", 2))
        self.assertEqual([(r["id"], r["verdict"]) for r in slip["replies"]],
                         [("c5", "catches"), ("c6", "accepts"), ("c7", "ignores"), ("c8", "ignores")])
        self.assertEqual((slip["caught"], slip["by"], slip["caught_round"], slip["rounds_to_catch"]), (True, ["bet"], 3, 1))
        self.assertEqual([r["id"] for r in slip["replies"] if r.get("nominal_author")], ["c6", "c8"])
        self.assertEqual(slip["counts"], {"catches": 1, "accepts": 0, "ignores": 1, "dismisses": 0})
        # c4 is filed under bet, and its only reply, c9, is bet's own
        self.assertEqual((sound["caught"], sound["dismissed"], sound["dismissed_by"]), (False, False, []))
        self.assertEqual([(r["id"], r["verdict"], r.get("nominal_author")) for r in sound["replies"]], [("c9", "dismisses", True)])
        self.assertEqual(len(res["usage"]), 2)
        self.assertEqual(res["notes"], [])
        self.assertIn("caught in round 3 by bet", out)
        self.assertIn("by bet, round 2: not dismissed; 0 replies", out)
        self.assertIn("not counted: 1 reply by bet, the plant's nominal author: c9 dismisses", out)
        self.assertIn("2 replies (1 catches, 1 ignores)", out)
        self.assertIn("not counted: 2 replies by alef, the plant's nominal author: c6 accepts, c8 ignores", out)

    def test_malformed_judge_output(self):
        notes = []
        got = read_verdicts({"replies": [{"id": "c5", "verdict": "maybe"}, "junk", {"id": "c77", "verdict": "catches"},
                                         {"id": "c6", "verdict": "catches"}]}, {"c5", "c6"}, notes, "c3")
        self.assertEqual(got, {"c6": ("catches", "")})
        self.assertEqual(len(notes), 3)
        ask_mod.HOOK = hook_from(["no json here at all", '{"verdict": "catches"}'])
        res = judge_plants(self.page.d, "mock:j")
        self.assertTrue(all(r["verdict"] is None for p in res["plants"] for r in p["replies"]))
        self.assertFalse(res["plants"][0]["caught"])
        self.assertTrue(any("ValueError" in n for n in res["notes"]))
        self.assertTrue(any("no list of verdicts" in n for n in res["notes"]))

    def test_judge_call_that_raises(self):
        def boom(*a):
            raise RuntimeError("provider down")
        ask_mod.HOOK = boom
        res = judge_plants(self.page.d, "mock:j")
        self.assertEqual(len(res["plants"]), 2)
        self.assertEqual(sum("provider down" in n for n in res["notes"]), 2)

    def test_plant_without_replies_makes_no_call(self):
        d = Path(self.tmp.name) / "q"
        d.mkdir()
        page = make_page(d)
        add_plant(page, {"as": "alef", "sort": "slip", "target": "c1", "text": "x", "truth": "y"})
        ask_mod.HOOK = hook_from([])
        res = judge_plants(page.d, "mock:j")
        self.assertEqual((res["plants"][0]["replies"], res["plants"][0]["caught"], res["usage"]), ([], False, []))


class Claims(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "r"
        self.dir.mkdir()
        self.page = planted(self.dir)

    def tearDown(self):
        ask_mod.HOOK = None
        self.tmp.cleanup()

    def test_summary_arithmetic(self):
        cs = ([{"hedged": True, "verdict": v} for v in ("wrong", "wrong", "right", "unsure", None)]
              + [{"hedged": False, "verdict": v} for v in ("right", "right", "right", "wrong")])
        s = summary(cs)
        self.assertEqual(s["hedged"], {"n": 5, "wrong": 2, "right": 1, "unsure": 1, "unjudged": 1, "wrong_rate": 0.5})
        self.assertEqual(s["unhedged"], {"n": 4, "wrong": 1, "right": 3, "unsure": 0, "unjudged": 0, "wrong_rate": 0.25})
        self.assertIsNone(summary([])["hedged"]["wrong_rate"])

    def test_chunks(self):
        self.assertEqual(chunks(list(range(7)), 3), [[0, 1, 2], [3, 4, 5], [6]])
        self.assertEqual(chunks(["aaaa", "bb", "cc", "d"], 10, 5, len),[["aaaa"], ["bb", "cc", "d"]])
        self.assertEqual(chunks([], 3), [])

    def test_batching_keeps_calls_few(self):
        d = self.page.d
        for i in range(60):
            self.page.add("alef", 3, {"target": "c1", "text": f"Comment {i} " + "words " * 100})
        n = {"e": 0, "j": 0}

        def hook(model, system, user, max_tokens, temperature):
            if model == "mock:x":
                n["e"] += 1
                ids = re.findall(r"^\[(c\d+)\]", user, re.M)
                return json.dumps({"claims": [{"comment": i, "claim": f"Claim of {i}.", "hedged": False} for i in ids]}), {}
            n["j"] += 1
            k = len(re.findall(r"^\d+\. ", user, re.M))
            return json.dumps({"verdicts": [{"n": i, "verdict": "right"} for i in range(1, k + 1)]}), {}

        ask_mod.HOOK = hook
        res = judge_claims(d, "mock:j", "mock:x")
        self.assertEqual(res["comments"], 68)  # plants are left out
        self.assertEqual(len(res["claims"]), 68)
        self.assertLessEqual(n["e"] + n["j"], 12)
        self.assertEqual(res["summary"]["unhedged"]["right"], 68)
        self.assertEqual(res["notes"], [])

    def test_command_end_to_end(self):
        calls = []
        extract = json.dumps({"claims": [
            {"comment": "c5", "claim": "Mill's Principles first appeared in 1848.", "hedged": True},
            {"comment": "c6", "claim": "Mill was born in 1806.", "hedged": "false"},
            {"comment": "c3", "claim": "From a plant, not asked for.", "hedged": False},
            {"comment": "c7", "claim": "", "hedged": False},
            {"comment": "c7", "claim": "Mill died in 1873.", "hedged": "perhaps"},
            {"comment": "c9", "claim": "Mill wrote On Liberty in 1820.", "hedged": False}]})
        judge = '{"verdicts": [{"n": 1, "verdict": "right", "why": "1848"}, {"n": "2", "verdict": "Correct"}, {"n": 3, "verdict": "wrong", "why": "1859"}, {"n": 9, "verdict": "right"}]}'
        ask_mod.HOOK = hook_from([extract, judge], calls)
        out = run(["judge", "claims", str(self.dir), "--judge", "mock:j", "--extract", "mock:x"])
        self.assertEqual([c[0] for c in calls], ["mock:x", "mock:j"])
        self.assertIn("[c5]", calls[0][2])
        self.assertNotIn("[c3]", calls[0][2])  # plants are not read
        self.assertNotIn("c5", calls[1][2])    # the judge sees claims alone
        res = json.loads((self.dir / "claims.json").read_text(encoding="utf-8"))
        self.assertEqual((res["judge"], res["extractor"]), ("mock:j", "mock:x"))
        self.assertEqual([(c["comment"], c["author"], c["round"], c["hedged"], c["verdict"]) for c in res["claims"]],
                         [("c5", "bet", 3, True, "right"), ("c6", "alef", 3, False, "right"), ("c9", "bet", 3, False, "wrong")])
        self.assertEqual(res["summary"]["hedged"]["wrong_rate"], 0.0)
        self.assertEqual(round(res["summary"]["unhedged"]["wrong_rate"], 2), 0.5)
        self.assertEqual(len(res["notes"]), 4)  # plant id, empty claim, bad hedge, claim number 9
        self.assertIn("hedged", out)
        self.assertIn("wrong 1 of 2 judged (50%)", out)

    def test_extractor_garbage(self):
        ask_mod.HOOK = hook_from(["I cannot help with that."])
        res = judge_claims(self.page.d, "mock:j")
        self.assertEqual((res["claims"], res["extractor"]), ([], "mock:j"))
        self.assertEqual(len(res["notes"]), 1)


if __name__ == "__main__":
    unittest.main()
