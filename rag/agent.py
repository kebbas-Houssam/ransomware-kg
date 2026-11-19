"""Agent mode: the LLM calls the MCP server's tools (max 6 calls), then answers.

    python -m rag.ask "question" --mode agent

The MCP server (mcp_server/) is launched as a stdio subprocess and reached through
the official MCP client, exactly as Claude Desktop would use it.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time

from mcp import Client, StdioServerParameters

from rag import config
from rag.llm import LLM, get_llm

MAX_TOOL_CALLS = 6
MAX_RESULT_CHARS = 6000

SYSTEM = """You answer questions about a master's thesis literature review on
ransomware detection by calling tools, then writing a short final answer.

- Numbers (results, counts, years) and paper facts must come from the graph tools:
  get_results, get_paper, search_papers, sparql_select (call get_schema first if you
  need to write SPARQL).
- Explanations ("why", "how") come from search_thesis passages.
- You may make at most {max_calls} tool calls in total.
- Final answer: in the language of the question, at most 5 sentences. Cite every
  paper by its id in parentheses, e.g. (wang2024deftpunk), and every thesis passage
  you use by its page, e.g. (p. 37). If the tools returned no data, say so; never
  invent a number."""


def tool_specs(tools) -> list[dict]:
    return [{"type": "function", "function": {
        "name": t.name, "description": t.description or "", "parameters": t.input_schema}}
        for t in tools]


def result_payload(result) -> object:
    """Prefer structured content; fall back to the text blocks."""
    if result.structured_content is not None:
        sc = result.structured_content
        return sc.get("result", sc) if isinstance(sc, dict) and set(sc) == {"result"} else sc
    texts = [getattr(b, "text", "") for b in result.content]
    try:
        parsed = [json.loads(t) for t in texts]
        return parsed[0] if len(parsed) == 1 else parsed
    except (json.JSONDecodeError, TypeError):
        return "\n".join(texts)


def collect_context(payload: object, known_ids: frozenset[str], papers: set, pages: set) -> None:
    """Walk a tool result and record the paper ids and thesis pages it contains."""
    if isinstance(payload, dict):
        for k, v in payload.items():
            if k == "pages" and isinstance(v, list):
                pages.update(map(str, v))
            else:
                collect_context(v, known_ids, papers, pages)
    elif isinstance(payload, list):
        for v in payload:
            collect_context(v, known_ids, papers, pages)
    elif isinstance(payload, str) and payload in known_ids:
        papers.add(payload)


class Agent:
    """Async context manager holding one MCP session; ask() answers one question."""

    def __init__(self, llm: LLM | None = None):
        self.llm = llm or get_llm()
        self.params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_server"],
                                            cwd=str(config.ROOT))

    async def __aenter__(self) -> "Agent":
        self._client = Client(self.params)
        self.client = await self._client.__aenter__()
        self.tools = tool_specs((await self.client.list_tools()).tools)
        return self

    async def __aexit__(self, *exc) -> None:
        await self._client.__aexit__(*exc)

    async def warm_up(self) -> None:
        await self.client.call_tool("search_thesis", {"query": "warm-up", "k": 1})

    async def ask(self, question: str):
        from rag.ask import Answer, find_citations, paper_ids

        ans = Answer(question, "agent")
        t0 = time.perf_counter()
        messages = [{"role": "system", "content": SYSTEM.format(max_calls=MAX_TOOL_CALLS)},
                    {"role": "user", "content": question}]
        papers: set[str] = set()
        pages: set[str] = set()
        while True:
            budget = MAX_TOOL_CALLS - len(ans.tool_calls)
            msg = await asyncio.to_thread(self.llm.chat, messages, self.tools if budget > 0 else None)
            calls = msg.get("tool_calls") or []
            if not calls or budget <= 0:
                ans.text = (msg.get("content") or "").strip()
                break
            messages.append({"role": "assistant", "content": msg.get("content") or "",
                             "tool_calls": calls})
            for i, call in enumerate(calls):
                fn = call.get("function", {})
                name, args = fn.get("name", ""), fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                if i >= budget:
                    content, ok = "skipped: tool-call budget exhausted, write the final answer", False
                else:
                    try:
                        res = await self.client.call_tool(name, args)
                        payload = result_payload(res)
                        ok = not res.is_error
                        if ok:
                            collect_context(payload, paper_ids(), papers, pages)
                        content = payload if isinstance(payload, str) else json.dumps(
                            payload, ensure_ascii=False)
                    except Exception as e:  # unknown tool, bad args, transport error
                        content, ok = f"error: {e}", False
                    ans.tool_calls.append({"name": name, "arguments": args, "ok": ok,
                                           "result": content[:500]})
                messages.append({"role": "tool", "tool_name": name,
                                 "content": content[:MAX_RESULT_CHARS]})
        ans.context_papers, ans.context_pages = sorted(papers), sorted(pages, key=int)
        ans.cited_papers, ans.cited_pages = find_citations(ans.text)
        ans.latency_s = round(time.perf_counter() - t0, 2)
        return ans


def ask_agent(question: str, llm: LLM | None = None):
    async def run():
        async with Agent(llm) as agent:
            return await agent.ask(question)
    return asyncio.run(run())
