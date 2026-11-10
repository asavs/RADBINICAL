import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from radbinical import amend
from radbinical import ask as ask_mod
from radbinical.cli import main
from radbinical.page import Page, render_for_reader
from radbinical.site import render
from radbinical.table import rows

TEXT = "Courts should publish dissents. A dissent records the losing argument. Later courts may need it when facts change."
READERS = ["mock:alef", "mock:bet", "mock:gimel", "mock:dalet"]


def quiet(f, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return f(*a, **k)


def step_of(system):
    return "draft" if system.startswith("You are drafting") else "vote" if "Vote on every" in system else "propose"


class Hook:
    """ask.HOOK stand-in: answers[step][reader name] is a reply string, an object (sent as JSON)
    or an exception to raise. Missing entries answer with an empty object."""

    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def __call__(self, model, system, user, max_tokens, temperature):
        step, name = step_of(system), model.split(":", 1)[1]
        self.calls.append((step, name, user))
        a = self.answers.get(step, {}).get(name, {})
        if isinstance(a, Exception):
            raise a
        return (a if isinstance(a, str) else json.dumps(a)), {"cost": 0.01}


def config(**amend_settings):
    return {"question": "Should courts publish dissents?", "models": READERS, "flags": {"seed": 1},
            "amend": {"threshold": 0.66, "max_words": 40, **amend_settings}}


class WithTmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "runs" / "court"

    def tearDown(self):
        ask_mod.HOOK = None
        self.tmp.cleanup()

    def use(self, answers):
        ask_mod.HOOK = Hook(answers)
        return ask_mod.HOOK

    def started(self, cfg=None):
        first = amend.order({"readers": [{"name": m.split(":")[1]} for m in READERS], "flags": {"seed": 1}})[0]["name"]
        self.use({"draft": {first: {"statement": TEXT}}})
        return quiet(amend.start, cfg or config(), self.out)

    def rec(self):
        return json.loads((self.out / "amendments.json").read_text(encoding="utf-8"))


class Start(WithTmp):
    def test_version_one(self):
        page = self.started()
        rec = self.rec()
        self.assertEqual(page.d["passage"]["text"], TEXT)
        self.assertEqual(page.d["passage"]["version"], 1)
        self.assertEqual(page.d["passage"]["title"], "Should courts publish dissents?")
        self.assertEqual(page.d["passage"]["id"], "amend-should-courts-publish-dissents")
        self.assertEqual(rec["versions"], [{"n": 1, "text": TEXT, "from_proposals": [], "after_round": 0, "words": 18}])
        self.assertEqual((rec["question"], rec["threshold"], rec["max_words"]), ("Should courts publish dissents?", 0.66, 40))
        self.assertEqual(rec["drafter"], amend.order(page.d)[0]["name"])
        self.assertEqual(page.d["group"], "court")
        self.assertTrue((self.out / "page.html").exists())

    def test_next_reader_drafts_when_one_fails(self):
        order = [r["name"] for r in amend.order({"readers": [{"name": m.split(":")[1]} for m in READERS], "flags": {"seed": 1}})]
        self.use({"draft": {order[0]: "no json here", order[1]: {"statement": " ".join(["word"] * 41)},
                            order[2]: {"statement": TEXT}}})
        quiet(amend.start, config(), self.out)
        rec = self.rec()
        self.assertEqual(rec["drafter"], order[2])
        self.assertEqual([e["reader"] for e in rec["log"]], order[:3])
        self.assertIn("ValueError", rec["log"][0]["error"])
        self.assertIn("over max_words", rec["log"][1]["error"])
        self.assertEqual(len(rec["usage"]), 3)

    def test_no_drafter_exits(self):
        self.use({"draft": {}})
        with self.assertRaises(SystemExit):
            quiet(amend.start, config(), self.out)
        self.assertFalse(self.out.exists())


class Check(unittest.TestCase):
    def test_valid(self):
        p, ok, note = amend.check(TEXT, {"quote": "records the  LOSING argument", "replacement": "keeps the losing argument",
                                         "reason": "r", "cites": ["c1", "[c2]", "c9"]}, {"c1", "c2"})
        self.assertTrue(ok)
        self.assertEqual(p["quote"], "records the losing argument")
        self.assertEqual(TEXT[p["start"]:p["end"]], p["quote"])
        self.assertEqual(p["cites"], ["c1", "c2"])
        self.assertEqual(note, "unknown cites dropped: c9")

    def test_rejected(self):
        cases = [
            ({"quote": "no such words", "replacement": "x"}, "quote not found"),
            ({"quote": "courts", "replacement": "judges"}, "more than once"),
            ({"quote": "publish dissents", "replacement": "publish  dissents"}, "same as the quote"),
            ({"quote": "publish dissents"}, "no replacement"),
            ({"replacement": "x"}, "no quote"),
            ("just a string", "not an object"),
        ]
        for raw, why in cases:
            p, ok, note = amend.check(TEXT, raw, set())
            self.assertFalse(ok, raw)
            self.assertIn(why, note)

    def test_empty_replacement_deletes(self):
        p, ok, _ = amend.check(TEXT, {"quote": "when facts change", "replacement": ""}, set())
        self.assertTrue(ok)
        self.assertEqual(amend.splice(TEXT, [(p["start"] - 1, p["end"], "")]), TEXT.replace(" when facts change", ""))


class Tally(unittest.TestCase):
    def votes(self, yes, no, abstain):
        return [{"vote": "yes"}] * yes + [{"vote": "no"}] * no + [{"vote": "abstain"}] * abstain

    def test_threshold_and_quorum(self):
        cases = [
            ((2, 1, 1), 4, 0.66, True),     # 2/3 >= 0.66, 3 of 4 voted
            ((2, 1, 1), 4, 0.67, False),    # 2/3 < 0.67
            ((2, 2, 0), 4, 0.5, True),      # exactly the threshold
            ((2, 2, 0), 4, 0.66, False),
            ((2, 0, 2), 4, 0.66, True),     # abstentions do not count against; 2 of 4 is half
            ((1, 0, 3), 4, 0.66, False),    # unanimous yes but under quorum
            ((2, 0, 3), 5, 0.66, False),    # 2 of 5 is under half
            ((3, 0, 2), 5, 0.66, True),
            ((0, 0, 4), 4, 0.66, False),
        ]
        for (y, n, a), readers, th, passed in cases:
            self.assertEqual(amend.tally(self.votes(y, n, a), readers, th), (y, n, a, passed), (y, n, a, readers, th))


class Apply(unittest.TestCase):
    def prop(self, pid, quote, rep, yes, no):
        s = TEXT.index(quote)
        return {"id": pid, "start": s, "end": s + len(quote), "quote": quote, "replacement": rep, "yes": yes, "no": no}

    def test_order_and_overlap(self):
        a = self.prop("p1", "the losing argument", "the defeated argument", 3, 1)
        b = self.prop("p2", "records the losing", "keeps the losing", 4, 0)
        c = self.prop("p3", "Courts should", "Courts must", 3, 1)
        new, edits = amend.apply(TEXT, [a, b, c], 40)
        self.assertEqual((a["applied"], b["applied"], c["applied"]), (False, True, True))
        self.assertEqual(a["note"], "overlaps p2, applied before it")
        self.assertEqual(new, "Courts must publish dissents. A dissent keeps the losing argument. Later courts may need it when facts change.")
        self.assertEqual([e[2] for e in edits], ["Courts must", "keeps the losing"])

    def test_ties_go_to_the_earlier_id(self):
        a = self.prop("p10", "the losing argument", "X", 2, 1)
        b = self.prop("p9", "records the losing", "Y", 2, 1)
        amend.apply(TEXT, [a, b], 40)
        self.assertEqual((a["applied"], b["applied"]), (False, True))

    def test_word_limit(self):
        a = self.prop("p1", "Courts should", "Courts, " + "very " * 30 + "much, should", 3, 0)
        b = self.prop("p2", " when facts change", "", 3, 1)
        new, _ = amend.apply(TEXT, [a, b], 20)
        self.assertFalse(a["applied"])
        self.assertIn("over max_words 20", a["note"])
        self.assertTrue(b["applied"])
        self.assertEqual(new, "Courts should publish dissents. A dissent records the losing argument. Later courts may need it.")


class Reanchor(WithTmp):
    def test_moves_relocates_and_marks_stale(self):
        page = self.started()
        add = lambda q: page.add("alef", 1, {"target": "passage", "quote": q, "text": "note"})
        add("Courts should publish dissents.")         # c1: words replaced -> stale
        add("Later courts may need it")                 # c2: after the edit -> moves
        add("A dissent")                                # c3: before the edit -> stays
        add("when facts change")                        # c4: deleted -> stale
        page.add("bet", 1, {"target": "c1", "quote": "note", "text": "reply"})
        old = TEXT
        s1 = old.index("Courts should publish")
        s2 = old.index(" when facts change")
        edits = [(s1, s1 + len("Courts should publish"), "Every court of record ought to publish"), (s2, s2 + len(" when facts change"), "")]
        new = amend.splice(old, edits)
        amend.reanchor(page.d["comments"], old, edits, new, 2)
        c = {x["id"]: x for x in page.d["comments"]}
        self.assertEqual(c["c1"]["stale"], 2)
        self.assertEqual(new[c["c1"]["start"]:c["c1"]["end"]], "Every court of record ought to publish dissents.")
        self.assertEqual(new[c["c2"]["start"]:c["c2"]["end"]], "Later courts may need it")
        self.assertEqual(new[c["c3"]["start"]:c["c3"]["end"]], "A dissent")
        self.assertNotIn("stale", c["c2"])
        self.assertEqual(c["c4"]["stale"], 2)
        self.assertEqual(c["c4"]["start"], c["c4"]["end"])
        self.assertEqual(c["c4"]["quote"], "when facts change")
        self.assertNotIn("start", c["c5"])

        # a stale comment stays stale and only moves; a quote found elsewhere is re-anchored there
        add("dissents.")  # c6
        newer = "Preface. " + new
        amend.reanchor(page.d["comments"], new, [(0, 0, "Preface. ")], newer, 3)
        self.assertEqual(c["c1"]["stale"], 2)
        self.assertEqual(newer[c["c1"]["start"]:c["c1"]["end"]], "Every court of record ought to publish dissents.")
        moved = newer.replace("dissents.", "opinions.").replace("A dissent", "A dissents.")
        amend.reanchor(page.d["comments"], newer, [], moved, 4)
        c6 = page.d["comments"][-1]
        self.assertEqual(moved[c6["start"]:c6["end"]], "dissents.")
        self.assertNotIn("stale", c6)

        page.d["passage"]["text"] = moved
        page.save()
        self.assertIn("[c1] alef", render_for_reader(page.d, page.d["comments"], lambda a: a, "bet"))
        render(page.dir)
        self.assertTrue(rows(self.out.parent))


class Cycle(WithTmp):
    def test_propose_vote_apply(self):
        page = self.started()
        page.add("alef", 1, {"target": "passage", "quote": "the losing argument", "text": "keeps it for later"})
        page.add("bet", 1, {"target": "passage", "quote": "Courts should publish dissents.", "text": "too strong"})
        page.save()
        hook = self.use({
            "propose": {
                "alef": {"amendments": [{"quote": "Courts should", "replacement": "Courts should, as a rule,", "reason": "hedge", "cites": ["c2"]}]},
                "bet": {"amendments": [{"quote": "not in the text", "replacement": "x", "reason": "r"},
                                       {"quote": "Courts should publish", "replacement": "Judges publish", "reason": "plainer"}]},
                "gimel": "I would keep it as it is. {\"amendments\": []}",
                "dalet": RuntimeError("provider down"),
            },
            "vote": {
                "alef": {"votes": [{"id": "p1", "vote": "yes", "why": "mine"}, {"id": "p3", "vote": "no", "why": "loses the should"}]},
                "bet": {"votes": [{"id": "p1", "vote": "YES", "why": "fine"}, {"id": "p3", "vote": "yes", "why": "mine"},
                                  {"id": "p2", "vote": "yes"}, {"id": "p1", "vote": "no"}]},
                "gimel": {"votes": [{"id": "p1", "vote": "no", "why": "hedges too much"}, {"id": "p3", "vote": "maybe"}]},
                "dalet": "not json",
            },
        })
        new = amend.propose(page)
        self.assertEqual([(p["id"], p["author"], p["status"]) for p in new],
                         [("p1", "alef", "open"), ("p2", "bet", "invalid"), ("p3", "bet", "open")])
        self.assertIn("quote not found", new[1]["note"])
        self.assertEqual((new[1]["passed"], new[1]["applied"]), (False, False))
        rec = self.rec()
        self.assertIn("provider down", next(e for e in rec["log"] if e["reader"] == "dalet")["error"])

        nv = amend.vote(Page.load(self.out))
        ballot = next(u for s, n, u in hook.calls if s == "vote" and n == "alef")
        self.assertIn('[p1] by alef (you): replace "Courts should" with "Courts should, as a rule,"', ballot)
        self.assertIn("    cites: c2", ballot)
        self.assertNotIn("[p2]", ballot)
        rec = self.rec()
        p = {x["id"]: x for x in rec["proposals"]}
        self.assertEqual((p["p1"]["yes"], p["p1"]["no"], p["p1"]["abstain"], p["p1"]["passed"], p["p1"]["applied"]), (2, 1, 0, True, True))
        self.assertEqual((p["p3"]["yes"], p["p3"]["no"], p["p3"]["passed"], p["p3"]["applied"]), (1, 1, False, False))
        self.assertIn({"reader": "gimel", "vote": "no", "why": "hedges too much"}, p["p1"]["votes"])
        self.assertEqual(p["p2"]["votes"], [])
        errors = {e["reader"]: e.get("error", "") for e in rec["log"] if e["step"] == "vote"}
        self.assertIn('"p2"', errors["bet"])
        self.assertIn('"maybe"', errors["gimel"])
        self.assertIn("ValueError", errors["dalet"])
        self.assertEqual(nv["n"], 2)
        self.assertEqual(rec["versions"][1], {"n": 2, "text": TEXT.replace("Courts should", "Courts should, as a rule,"),
                                              "from_proposals": ["p1"], "after_round": 0, "words": 21})
        d = Page.load(self.out).d
        self.assertEqual((d["passage"]["text"], d["passage"]["version"]), (rec["versions"][1]["text"], 2))
        c = {x["id"]: x for x in d["comments"]}
        self.assertEqual(d["passage"]["text"][c["c1"]["start"]:c["c1"]["end"]], "the losing argument")
        self.assertEqual(c["c2"]["stale"], 2)
        self.assertEqual(sum(u.get("cost", 0) for u in rec["usage"]), 0.01 * 8)

        self.use({"propose": {"alef": {"amendments": []}}})
        quiet(amend.cycle, Page.load(self.out), 0)
        self.assertEqual(len(self.rec()["versions"]), 2)

    def test_full_offline_cycle_through_cli(self):
        cfg = Path(self.tmp.name) / "amend.json"
        cfg.write_text(json.dumps({**config(), "amend": {"threshold": 0.5, "max_words": 250}}), encoding="utf-8")
        quiet(main, ["amend", "start", str(cfg), "--out", str(self.out)])
        for _ in range(3):
            quiet(main, ["amend", "cycle", str(self.out), "-n", "1"])
        quiet(main, ["render", str(self.out)])
        rec, d = self.rec(), Page.load(self.out).d
        self.assertGreater(len(rec["versions"]), 1)
        self.assertEqual(d["passage"]["text"], rec["versions"][-1]["text"])
        self.assertEqual(d["layers_done"], 3)
        self.assertTrue(all(p["status"] in ("closed", "invalid") for p in rec["proposals"]))
        applied = [i for v in rec["versions"] for i in v["from_proposals"]]
        self.assertEqual(applied, [p["id"] for p in rec["proposals"] if p["applied"]])
        for c in d["comments"]:
            if c["target"] == "passage":
                self.assertTrue(0 <= c["start"] <= c["end"] <= len(d["passage"]["text"]))
                if not c.get("stale"):
                    self.assertEqual(d["passage"]["text"][c["start"]:c["end"]].lower(), c["quote"].lower())
        self.assertTrue(rows(self.out.parent))


if __name__ == "__main__":
    unittest.main()
