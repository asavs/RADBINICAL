"""OpenAI's Responses API."""
from .http import post_json


class ResponsesSession:
    """OpenAI's Responses API, which carries its reasoning models' reasoning from one step to the next."""
    URL = "https://api.openai.com/v1/responses"

    def __init__(self, name, system, user, flags, max_tokens):
        self.name, self.system, self.flags, self.max_tokens = name, system, flags, max_tokens
        self.input = [{"role": "user", "content": user}]
        self.truncated = False

    def step(self):
        body = {"model": self.name, "instructions": self.system, "input": self.input,
                "max_output_tokens": self.max_tokens, "store": False, "include": ["reasoning.encrypted_content"]}
        if self.flags["temperature"] is not None:
            body["temperature"] = self.flags["temperature"]
        data = post_json(self.URL, "openai", body)
        self.truncated = data.get("status") == "incomplete"
        self.input += data["output"]  # reasoning items are replayed as returned
        text = [c.get("text", "") for item in data["output"] if item.get("type") == "message"
                for c in item.get("content", []) if c.get("type") == "output_text"]
        u = data.get("usage") or {}
        return "\n".join(text), {"prompt_tokens": u.get("input_tokens", 0), "completion_tokens": u.get("output_tokens", 0)}

    def say(self, text):
        self.input.append({"role": "user", "content": text})
