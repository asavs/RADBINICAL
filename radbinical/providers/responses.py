"""OpenAI's Responses API."""
import json

from ..prompts import annotate_tool
from .http import post_json


class ResponsesSession:
    """OpenAI's Responses API, which its reasoning models need for tool use."""
    URL = "https://api.openai.com/v1/responses"

    def __init__(self, name, system, user, flags, max_tokens, tools=True):
        self.name, self.system, self.flags, self.max_tokens = name, system, flags, max_tokens
        self.input = [{"role": "user", "content": user}]
        t = annotate_tool(flags)["function"]
        self.tools = [{"type": "function", "name": t["name"], "description": t["description"], "parameters": t["parameters"]}] if tools else []

    def step(self):
        body = {"model": self.name, "instructions": self.system, "input": self.input,
                "max_output_tokens": self.max_tokens, "store": False, "include": ["reasoning.encrypted_content"]}
        if self.tools:
            body["tools"] = self.tools
        if self.flags["temperature"] is not None:
            body["temperature"] = self.flags["temperature"]
        data = post_json(self.URL, "OPENAI_API_KEY", body)
        self.input += data["output"]  # reasoning items are replayed as returned
        calls, text = [], []
        for item in data["output"]:
            if item.get("type") == "function_call":
                try:
                    calls.append((item["call_id"], json.loads(item.get("arguments") or "{}")))
                except json.JSONDecodeError:
                    calls.append((item["call_id"], None))
            elif item.get("type") == "message":
                text += [c.get("text", "") for c in item.get("content", []) if c.get("type") == "output_text"]
        u = data.get("usage") or {}
        return calls, "\n".join(text), {"prompt_tokens": u.get("input_tokens", 0), "completion_tokens": u.get("output_tokens", 0)}

    def reply(self, results):
        self.input += [{"type": "function_call_output", "call_id": cid, "output": res} for cid, res in results]
