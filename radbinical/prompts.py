"""What each reader is told, and how its reply is read.

Every reader writes the same way, whatever its model can do: one reply per turn, holding a block
for each comment and nothing else that counts.

    <comment on="passage">
    <quote>the exact words it is on</quote>
    the comment
    </comment>

`on` is the node whose margin the comment goes in: "passage" or a comment's id. The quote is
required on the passage and optional on a comment. `see="c2 c5"` points at other comments.
"""
import re


def system_prompt(page, me, label):
    flags = page["flags"]
    others = [label(r["name"]) for r in page["readers"] if r["name"] != me]
    n = len(page["readers"])
    if flags["signed"]:
        roster = f"You appear on the page as {me}. The other readers are {', '.join(others)}." if others else f"You appear on the page as {me}."
    else:
        roster = "Readers are not named on the page; your own comments are marked (you)."
    anchor = ("the span exactly as it appears; it can be a few words or several sentences"
              if flags["anchor"] == "span" else "any part of a sentence; the comment attaches to the whole sentence")
    refs = ' A block can also carry see="c2 c5" to point at other comments.' if flags["cross_refs"] else ""
    return (
        f"You are one of {n} readers sharing a single page. At the centre of the page is a passage. "
        f"Around it, in the margins, commentary accumulates over several rounds. {roster}\n\n"
        "The page is one shape repeated: a text with a margin. The passage has a margin, where the comments "
        "on it stand. Every comment has a margin of its own, where the comments on that comment stand. You "
        "are shown each comment beneath what it is written on, set in one step.\n\n"
        "To write a comment, put a block like this in your reply:\n\n"
        '<comment on="passage">\n<quote>the exact words you mean</quote>\nyour comment\n</comment>\n\n'
        '`on` says whose margin the comment goes in: "passage", or the id of a comment, such as "c7". '
        f"On the passage the quote is required: {anchor}. On a comment it is optional, and marks the part "
        f"of that comment you mean.{refs}\n\n"
        "There is no assignment and nothing here is being scored. Comment where you have something to say, "
        "as briefly or at as much length as the thought needs, and leave the rest alone. Agreeing, disagreeing, "
        "asking, connecting and staying silent are all fine. "
        "Your reply is your whole turn this round: put a block in it for every comment you want to make, or "
        "none if you have nothing to add. Only the blocks go on the page. If a comment cannot be recorded "
        "you will be told why, once, and can write it again."
    )


def asked_note(ask):
    """What opens an asked turn: which words the reader has been asked about, and that the turn is
    for one comment on them."""
    where = "the passage" if ask["target"] == "passage" else f"comment {ask['target']}"
    quote = " ".join((ask.get("quote") or "").split())
    what = f'these words of {where}: "{quote}"' if quote else where
    block = f'on="{ask["target"]}"' + (" and those words as its quote" if quote else "")
    return (f"A person reading the page has asked you about {what}. You see the page as it stands now. This turn is "
            f"for one comment in answer: a single block with {block}. Reply without a block if you have nothing to say.")


# A block ends at its closing tag or, when that is left out, where the next block or the reply ends.
_BLOCK = re.compile(r"<comment\b([^>]*)>(.*?)(</comment\s*>|(?=<comment\b)|\Z)", re.S | re.I)
_ATTR = re.compile(r"""([\w-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""")
_QUOTE = re.compile(r"<quote>(.*?)</quote>", re.S | re.I)
# A reply with no block that still looks like comments: a quote tag on its own, or JSON keys.
_ATTEMPT = re.compile(r"""<\s*quote\b|["'](?:on|quote)["']\s*:""", re.I)

WRONG_SHAPE = ('Nothing was recorded: comments must be written as <comment on="..."> ... </comment> blocks, as '
               "described, not as JSON or in any other form.")


def read_reply(text, truncated=False):
    """(comments, note, wrong_shape) from one reply. Each comment is the arguments `Page.add` takes:
    target, quote, text and, when given, see_also. `note` is what the reply says outside its blocks.
    A reply cut off at the output limit loses its last block if that block was left open, since
    the comment in it is unfinished. `wrong_shape` is true when the reply has no block but seems
    to hold comments written some other way."""
    text = text or ""
    found = list(_BLOCK.finditer(text))
    if truncated and found and not found[-1].group(3):
        found.pop()
    comments = []
    for m in found:
        attrs = {k.lower(): a or b or c for k, a, b, c in _ATTR.findall(m.group(1))}
        body, quote = m.group(2), ""
        q = _QUOTE.search(body)
        if q:
            quote, body = q.group(1).strip(), body[:q.start()] + body[q.end():]
        args = {"target": attrs.get("on", "").strip(), "quote": quote, "text": body.strip()}
        if attrs.get("see"):
            args["see_also"] = [r for r in re.split(r"[,\s]+", attrs["see"].strip()) if r]
        comments.append(args)
    return comments, _BLOCK.sub("", text).strip(), not found and bool(_ATTEMPT.search(text))


def repair_request(problems):
    """What a reader is told when part of its reply could not be recorded. `problems` is
    [(position in the reply, what it was on, why not)], or empty when the whole reply was in the
    wrong shape."""
    if not problems:
        return WRONG_SHAPE + " You may write them again as blocks, in one more reply."
    lines = [f"Comment {i}" + (f' (on "{on}")' if on else "") + f": {why}" for i, on, why in problems]
    return ("\n".join(lines) + "\n\nEverything else in your reply was recorded. You may write the comments that "
            "were not again, corrected, in one more reply. Do not repeat the ones that were recorded. Reply "
            "without a block to leave them out.")
