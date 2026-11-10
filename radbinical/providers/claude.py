"""Claude through the Anthropic API, using the official SDK."""
from ..prompts import annotate_tool
from .http import api_key


class AnthropicSession:
    """Claude through the Anthropic API directly, using the official SDK."""
    def __init__(self, name, system, user, flags, max_tokens, tools=True):
        import anthropic
        # base_url is pinned so an ANTHROPIC_BASE_URL set for other tooling cannot redirect the call.
        self.client = anthropic.Anthropic(api_key=api_key("anthropic") or "placeholder-key",
                                          base_url="https://api.anthropic.com")
        self.name, self.system, self.max_tokens, self.flags = name, system, max_tokens, flags
        self.messages = [{"role": "user", "content": user}]
        t = annotate_tool(flags)["function"]
        self.tools = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}] if tools else []
        self.truncated = False

    def step(self):
        # No `thinking` parameter: each model runs with its own default, which keeps one
        # request shape valid from Claude 3 through the current models. No refusal fallback
        # either: a reader silently swapped for another model would corrupt the record.
        kw = {"tools": self.tools} if self.tools else {}
        if self.flags["temperature"] is not None:
            kw["temperature"] = self.flags["temperature"]
        r = self.client.messages.create(model=self.name, max_tokens=self.max_tokens, system=self.system,
                                        messages=self.messages, **kw)
        self.truncated = r.stop_reason == "max_tokens"
        self.messages.append({"role": "assistant", "content": r.content})
        calls = [(b.id, b.input if isinstance(b.input, dict) else None) for b in r.content if b.type == "tool_use"]
        text = "\n".join(b.text for b in r.content if b.type == "text")
        if r.stop_reason == "refusal":
            calls, text = [], "[the model declined to continue]"
        return calls, text, {"prompt_tokens": r.usage.input_tokens, "completion_tokens": r.usage.output_tokens}

    def reply(self, results):
        self.messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": cid, "content": res} for cid, res in results]})
