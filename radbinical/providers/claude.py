"""Claude through the Anthropic API, using the official SDK."""
from .http import api_key


class AnthropicSession:
    """Claude through the Anthropic API directly, using the official SDK."""
    def __init__(self, name, system, user, flags, max_tokens):
        import anthropic
        # base_url is pinned so an ANTHROPIC_BASE_URL set for other tooling cannot redirect the call.
        self.client = anthropic.Anthropic(api_key=api_key("anthropic") or "placeholder-key",
                                          base_url="https://api.anthropic.com")
        self.name, self.system, self.max_tokens, self.flags = name, system, max_tokens, flags
        self.messages = [{"role": "user", "content": user}]
        self.truncated = False

    def step(self):
        # No `thinking` parameter: each model runs with its own default, which keeps one
        # request shape valid from Claude 3 through the current models. No refusal fallback
        # either: a reader silently swapped for another model would corrupt the record.
        kw = {} if self.flags["temperature"] is None else {"temperature": self.flags["temperature"]}
        # Streamed: the SDK refuses a plain request whose max_tokens could run past ten minutes.
        with self.client.messages.stream(model=self.name, max_tokens=self.max_tokens, system=self.system,
                                         messages=self.messages, **kw) as stream:
            r = stream.get_final_message()
        self.truncated = r.stop_reason == "max_tokens"
        self.messages.append({"role": "assistant", "content": r.content})
        text = "\n".join(b.text for b in r.content if b.type == "text")
        if r.stop_reason == "refusal":
            text = "[the model declined to continue]"
        return text, {"prompt_tokens": r.usage.input_tokens, "completion_tokens": r.usage.output_tokens}

    def say(self, text):
        self.messages.append({"role": "user", "content": text})
