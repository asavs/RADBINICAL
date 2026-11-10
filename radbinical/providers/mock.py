"""Offline stand-in reader for testing without keys."""
import json
import random
import re


_MOCK = ["This sentence carries more weight than it admits.", "I read this differently: the claim is narrower than it sounds.",
         "Compare the earlier wording; the two do not obviously agree.", "What would count as evidence against this?",
         "Agreed, and it extends further than the author takes it."]


def mock_chat(name, messages):
    """Offline stand-in: placeholder comments, clearly not a real model's reading."""
    rng = random.Random(name + str(len(messages)) + messages[1]["content"][:40])
    if len(messages) > 2 + 2 * rng.randint(1, 3):
        return {"role": "assistant", "content": "Nothing further this round."}, {}
    page = messages[1]["content"]
    ids = re.findall(r"^\s*\[(c\d+)\]", page, re.M)
    body = page.split("=== THE MARGINS")[0].split("\n\n", 1)[1]
    sents = [s.strip() for s in re.split(r"(?<=[.;])\s+", body) if len(s.strip()) > 30]
    if ids and rng.random() < 0.6:
        args = {"target": rng.choice(ids), "text": "[mock] " + rng.choice(_MOCK)}
    else:
        s = rng.choice(sents); w = s.split(); a = rng.randrange(0, max(1, len(w) - 6))
        args = {"target": "passage", "quote": " ".join(w[a:a + rng.randint(4, 12)]), "text": "[mock] " + rng.choice(_MOCK)}
    call = {"id": f"call_{rng.randrange(10**9)}", "type": "function", "function": {"name": "annotate", "arguments": json.dumps(args)}}
    return {"role": "assistant", "content": None, "tool_calls": [call]}, {}


class MockSession:
    """Offline stand-in: placeholder comments, clearly not a real model's reading."""
    def __init__(self, name, system, user):
        self.name, self.messages = name, [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def step(self):
        msg, _ = mock_chat(self.name, self.messages)
        self.messages.append(msg)
        calls = [(c["id"], json.loads(c["function"]["arguments"])) for c in msg.get("tool_calls") or []]
        return calls, msg.get("content") or "", {}

    def reply(self, results):
        for cid, res in results:
            self.messages.append({"role": "tool", "tool_call_id": cid, "content": res})
