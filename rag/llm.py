"""Provider-agnostic chat completion: Ollama (default), Anthropic or OpenAI.

    from rag.llm import get_llm
    text = get_llm().complete(system="...", user="...")
"""
from __future__ import annotations

from dataclasses import dataclass

import requests

from rag import config

DEFAULT_MODELS = {"ollama": "qwen2.5:7b", "anthropic": "claude-opus-5-5", "openai": "gpt-4.1-mini"}


@dataclass
class LLM:
    provider: str
    model: str

    def complete(self, system: str, user: str, max_tokens: int = 2048) -> str:
        return getattr(self, f"_{self.provider}")(system, user, max_tokens).strip()

    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             max_tokens: int = 700, num_ctx: int = 16384) -> dict:
        """One chat turn with optional tool definitions (OpenAI/Ollama format).
        Returns the assistant message: {"content": str, "tool_calls": [...]}."""
        if self.provider != "ollama":
            raise NotImplementedError("agent mode currently supports LLM_PROVIDER=ollama only")
        body = {"model": self.model, "stream": False, "messages": messages,
                "options": {"temperature": 0, "num_predict": max_tokens, "num_ctx": num_ctx}}
        if tools:
            body["tools"] = tools
        r = requests.post(f"{config.OLLAMA_HOST}/api/chat", json=body, timeout=600)
        r.raise_for_status()
        return r.json()["message"]

    def _ollama(self, system: str, user: str, max_tokens: int) -> str:
        r = requests.post(f"{config.OLLAMA_HOST}/api/chat", timeout=600, json={
            "model": self.model,
            "stream": False,
            "options": {"temperature": 0, "num_predict": max_tokens, "num_ctx": 8192},
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
        })
        r.raise_for_status()
        return r.json()["message"]["content"]

    def _anthropic(self, system: str, user: str, max_tokens: int) -> str:
        import anthropic  # optional dependency

        resp = anthropic.Anthropic().beta.messages.create(
            model=self.model,
            max_tokens=max(max_tokens, 4096),
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",  # re-run on a fallback model if a safety classifier declines
        )
        if resp.stop_reason == "refusal":
            raise RuntimeError("Anthropic model declined the request")
        return "".join(b.text for b in resp.content if b.type == "text")

    def _openai(self, system: str, user: str, max_tokens: int) -> str:
        import openai  # optional dependency

        resp = openai.OpenAI().chat.completions.create(
            model=self.model, temperature=0, max_tokens=max_tokens,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        return resp.choices[0].message.content or ""


def get_llm(provider: str | None = None, model: str | None = None) -> LLM:
    provider = (provider or config.LLM_PROVIDER).lower()
    if provider not in DEFAULT_MODELS:
        raise ValueError(f"unknown LLM_PROVIDER {provider!r} (use ollama, anthropic or openai)")
    return LLM(provider, model or config.LLM_MODEL or DEFAULT_MODELS[provider])
