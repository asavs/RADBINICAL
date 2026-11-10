"""OpenAI-style chat completions: OpenRouter, Nous, NVIDIA and Google."""
from .http import post_json


PROVIDERS = {  # endpoint, name of the output-limit field
    "openrouter": ("https://openrouter.ai/api/v1/chat/completions", "max_tokens"),
    "nous": ("https://inference-api.nousresearch.com/v1/chat/completions", "max_tokens"),  # takes OpenRouter-style ids
    "openai": ("https://api.openai.com/v1/chat/completions", "max_completion_tokens"),
    "nvidia": ("https://integrate.api.nvidia.com/v1/chat/completions", "max_tokens"),
    "google": ("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", "max_tokens"),
}


class ChatSession:
    """OpenAI-style chat completions (OpenRouter, Nous, NVIDIA, Google)."""
    def __init__(self, provider, name, system, user, flags, max_tokens):
        self.provider = provider
        self.url, self.cap = PROVIDERS[provider]
        self.name, self.flags, self.max_tokens = name, flags, max_tokens
        self.messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        self.truncated = False  # the last answer stopped at the output limit

    def _send(self):
        body = {"model": self.name, "messages": self.messages, self.cap: self.max_tokens}
        if self.flags["temperature"] is not None:
            body["temperature"] = self.flags["temperature"]
        data = post_json(self.url, self.provider, body)
        self.truncated = data["choices"][0].get("finish_reason") == "length"
        return data["choices"][0]["message"], data.get("usage") or {}

    def step(self):
        msg, usage = self._send()
        self.messages.append(msg)  # kept whole so any reasoning blocks the provider needs are replayed intact
        text = msg.get("content") if isinstance(msg.get("content"), str) else ""
        return text or "", usage

    def say(self, text):
        self.messages.append({"role": "user", "content": text})
