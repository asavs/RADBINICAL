"""What each reader is told, and the one tool it is given."""

def system_prompt(page, me, label, protocol="tools"):
    flags = page["flags"]
    others = [label(r["name"]) for r in page["readers"] if r["name"] != me]
    n = len(page["readers"])
    if flags["signed"]:
        roster = f"You appear on the page as {me}. The other readers are {', '.join(others)}." if others else f"You appear on the page as {me}."
    else:
        roster = "Readers are not named on the page; your own comments are marked (you)."
    anchor = ("quote the span exactly as it appears; it can be a few words or several sentences"
              if flags["anchor"] == "span" else "quote any part of a sentence; the comment attaches to the whole sentence")
    refs = " A comment can also point at other comments with see_also." if flags["cross_refs"] else ""
    return (
        f"You are one of {n} readers sharing a single page. At the centre of the page is a passage. "
        f"Around it, in the margins, commentary accumulates over several rounds. {roster}\n\n"
        + (f"You have one tool, `annotate`. Use it to attach a comment to the passage ({anchor}) "
           f"or to an existing comment (give its id, and optionally quote the part of it you mean).{refs}\n\n"
           if protocol != "text" else
           "To attach a comment, write a block like this in your reply:\n\n"
           '<annotate target="passage" quote="the exact words you mean">\nyour comment\n</annotate>\n\n'
           f"The target is either \"passage\" ({anchor}) or the id of an existing comment such as \"c7\" "
           "(the quote is then optional). You can write several blocks in one reply."
           + (' A block can also carry see_also="c2,c5" to point at other comments.' if flags["cross_refs"] else "") + "\n\n") +
        "There is no assignment and nothing here is being scored. Comment where you have something to say, "
        "as briefly or at as much length as the thought needs, and leave the rest alone. Agreeing, disagreeing, "
        "asking, connecting and staying silent are all fine. "
        + ("When you have nothing further to add this round, say so in plain text without calling the tool. "
           "That ends your turn." if protocol != "text"
           else "Your reply is your whole turn this round: put every block you want in it, or none if you have "
                "nothing to add. If a block cannot be recorded you will be told why and can write it again.")
    )


def annotate_tool(flags):
    props = {
        "target": {"type": "string", "description": 'Either "passage" or the id of an existing comment, e.g. "c7".'},
        "quote": {"type": "string", "description": "The exact words you are commenting on, copied from the target. Required when the target is the passage."},
        "text": {"type": "string", "description": "Your comment."},
    }
    if flags["cross_refs"]:
        props["see_also"] = {"type": "array", "items": {"type": "string"}, "description": "Optional ids of other comments this one connects to."}
    return {"type": "function", "function": {
        "name": "annotate",
        "description": "Attach a comment to a span of the passage or to an existing comment.",
        "parameters": {"type": "object", "properties": props, "required": ["target", "text"]},
    }}
