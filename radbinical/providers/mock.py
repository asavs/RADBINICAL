"""Offline stand-in reader for testing without keys."""
import random
import re


_MOCK = ["This sentence carries more weight than it admits.", "I read this differently: the claim is narrower than it sounds.",
         "Compare the earlier wording; the two do not obviously agree.", "What would count as evidence against this?",
         "Agreed, and it extends further than the author takes it."]


def mock_reply(name, page):
    """Placeholder comments on the page a reader was shown, clearly not a real model's reading:
    up to three blocks, or a line saying it passes."""
    rng = random.Random(name + page[:40] + str(len(page)))
    ids = re.findall(r"^\s*\[(c\d+)\]", page, re.M)
    body = page.split("=== THE MARGINS")[0].split("\n\n", 1)[1]
    sents = [s.strip() for s in re.split(r"(?<=[.;])\s+", body) if len(s.strip()) > 30]
    blocks = []
    for _ in range(rng.randint(0, 3)):
        said = "[mock] " + rng.choice(_MOCK)
        if ids and rng.random() < 0.6:
            blocks.append(f'<comment on="{rng.choice(ids)}">\n{said}\n</comment>')
        else:
            w = rng.choice(sents).split()
            a = rng.randrange(0, max(1, len(w) - 6))
            blocks.append(f'<comment on="passage">\n<quote>{" ".join(w[a:a + rng.randint(4, 12)])}</quote>\n{said}\n</comment>')
    return "\n\n".join(blocks) or "Nothing further this round."


class MockSession:
    """Offline stand-in: placeholder comments, clearly not a real model's reading."""
    def __init__(self, name, system, user):
        self.name, self.page, self.told = name, user, []

    def step(self):
        return ("Nothing further this round." if self.told else mock_reply(self.name, self.page)), {}

    def say(self, text):
        self.told.append(text)
