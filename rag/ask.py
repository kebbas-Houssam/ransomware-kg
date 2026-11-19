"""Answer a question about the literature review.

    python -m rag.ask "question" --mode vector|sparql|hybrid|hybrid2|agent [--show-context]

vector   thesis chunks retrieved from the FAISS index -> LLM answer
sparql   LLM-generated SPARQL on Fuseki -> LLM verbalises the rows
hybrid   both contexts together; the answer cites paper ids and thesis pages
hybrid2  like hybrid, but numbers come from the SPARQL rows (enforced), and with
         no rows the answer says the graph has no data instead of guessing
agent    the LLM calls the MCP server's tools (max 6 calls), see rag/agent.py
"""
from __future__ import annotations

import argparse
import csv
import re
import time
from dataclasses import asdict, dataclass, field
from functools import lru_cache

from rag import config
from rag.llm import LLM, get_llm
from rag.text2sparql import SparqlResult, text_to_sparql

MODES = ("vector", "sparql", "hybrid", "hybrid2", "agent")

SYSTEM = """You answer questions about a master's thesis literature review on
ransomware detection. Use only the context below; if it does not contain the
answer, say so. Answer in the language of the question, in at most 5 sentences.
Give exact numbers as they appear in the context.
Cite every paper you mention by its id exactly as written in the context, in
parentheses, e.g. (wang2024deftpunk).{pages}"""
PAGES_RULE = """
Also cite the thesis page of each passage you use, as written in its header,
e.g. (p. N)."""


@dataclass
class Answer:
    question: str
    mode: str
    text: str = ""
    sparql: str = ""
    sparql_rows: list[dict] = field(default_factory=list)
    sparql_error: str = ""
    chunks: list[dict] = field(default_factory=list)  # id, pages, paper_ids, score
    cited_papers: list[str] = field(default_factory=list)
    cited_pages: list[str] = field(default_factory=list)
    context_papers: list[str] = field(default_factory=list)  # paper ids the answer was given
    context_pages: list[str] = field(default_factory=list)   # thesis pages the answer was given
    tool_calls: list[dict] = field(default_factory=list)     # agent mode only
    latency_s: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@lru_cache(maxsize=1)
def paper_ids() -> frozenset[str]:
    with config.PAPERS_CSV.open(newline="", encoding="utf-8") as f:
        return frozenset(r["id"] for r in csv.DictReader(f))


def find_citations(text: str) -> tuple[list[str], list[str]]:
    papers = sorted(p for p in paper_ids() if re.search(rf"\b{re.escape(p)}\b", text))
    pages = sorted(set(re.findall(r"\bpp?\.\s*(\d+)", text)), key=int)
    return papers, pages


def chunk_context(chunks: list[dict]) -> str:
    parts = []
    for c in chunks:
        pages = c["pages"][0] if len(c["pages"]) == 1 else f"{c['pages'][0]}-{c['pages'][-1]}"
        cites = ", ".join(c["paper_ids"]) or "none"
        parts.append(f"[thesis p. {pages} | cites papers: {cites}]\n{c['text']}")
    return "\n\n".join(parts)


def sparql_context(res: SparqlResult) -> str:
    return f"Knowledge-graph query result (authoritative facts):\n{res.as_table()}"


_retriever = None


def retriever():
    global _retriever
    if _retriever is None:
        from rag.retrieve import Retriever
        _retriever = Retriever()
    return _retriever


HYBRID2_ROWS = """You answer questions about a master's thesis literature review on
ransomware detection. You are given thesis passages and, last, knowledge-graph rows.
The knowledge-graph rows are the ground truth: take every number, count, value and
paper id from them. Use the passages only to explain why or how. If a passage
seems to contradict the rows, follow the rows. Answer in the language of the
question, in at most 5 sentences. Cite every paper by its id in parentheses,
e.g. (wang2024deftpunk), and each passage you use by its page, e.g. (p. N)."""

HYBRID2_NO_ROWS = """You answer questions about a master's thesis literature review on
ransomware detection. The knowledge graph returned NO data for this question; the
reader has already been told so. Using only the thesis passages, add what they say
that is relevant (in at most 4 sentences, in the language of the question). Do not
state any number, percentage or count unless it is written in a passage. Cite each
passage by its page, e.g. (p. N), and papers by their id, e.g. (wang2024deftpunk)."""

NO_DATA = {"en": "The knowledge graph has no data for this question.",
           "fr": "Le graphe de connaissances ne contient pas de données pour cette question."}
GRAPH_SAYS = {"en": "Knowledge graph", "fr": "Graphe de connaissances"}
FR_WORDS = re.compile(r"\b(quel|quelle|quels|quelles|combien|pourquoi|comment|est-ce|les|des|une|sur|dans|avec)\b", re.I)
NUMBER = re.compile(r"^-?\d+(?:[.,]\d+)?$")


def lang_of(question: str) -> str:
    return "fr" if FR_WORDS.search(question) else "en"


def has_number(value: str, text: str) -> bool:
    """value '98.20' is in text as 98.2 / 98,20 / 98.20 (not as part of 198.2 or kebbas2025)."""
    whole, _, frac = value.replace(",", ".").partition(".")
    frac = frac.rstrip("0")
    pat = re.escape(whole) + (rf"[.,]{re.escape(frac)}0*" if frac else r"(?:[.,]0+)?")
    return re.search(rf"(?<![\w.,]){pat}(?![\d]|[.,]\d)", text) is not None


def enforce_rows(text: str, rows: list[dict], lang: str) -> str:
    """Make sure the numbers in the answer come from the rows.

    One row (a count or a single value): every number of the row must appear.
    Several rows: at least one of their numbers must appear. Otherwise the rows
    are stated first, deterministically, before the LLM's explanation."""
    nums = [v for r in rows[:10] for v in r.values() if NUMBER.match(v.strip())]
    if not nums:
        return text
    ok = all(has_number(n, text) for n in nums) if len(rows) == 1 else any(has_number(n, text) for n in nums)
    if ok:
        return text
    facts = "; ".join(", ".join(f"{k} = {v}" for k, v in r.items()) for r in rows[:5])
    return f"{GRAPH_SAYS[lang]}: {facts}.\n{text}"


def drop_unsupported_numbers(text: str, allowed: str) -> str:
    """Remove sentences giving a decimal or percentage that no passage contains."""
    keep = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        nums = re.findall(r"\d+[.,]\d+|\d+(?=\s?%)", sentence)
        if all(has_number(n, allowed) for n in nums):
            keep.append(sentence)
    return " ".join(keep)


def ask_hybrid2(question: str, k: int, llm: LLM) -> Answer:
    ans, lang = Answer(question, "hybrid2"), lang_of(question)
    t0 = time.perf_counter()
    res = text_to_sparql(question, llm)
    ans.sparql, ans.sparql_rows, ans.sparql_error = res.query, res.rows, res.error
    chunks = retriever().search(question, k)
    ans.chunks = [{k_: c[k_] for k_ in ("id", "pages", "paper_ids", "score")} for c in chunks]
    passages = "Thesis passages:\n" + chunk_context(chunks)
    if res.rows:
        user = f"{passages}\n\n{sparql_context(res)}\n\nQuestion: {question}"
        text = llm.complete(HYBRID2_ROWS, user, max_tokens=500)
        ans.text = enforce_rows(text, res.rows, lang)
    else:
        text = llm.complete(HYBRID2_NO_ROWS, f"{passages}\n\nQuestion: {question}", max_tokens=400)
        text = drop_unsupported_numbers(text, " ".join(c["text"] for c in chunks))
        ans.text = f"{NO_DATA[lang]} {text}".strip()
    ans.latency_s = round(time.perf_counter() - t0, 2)
    return ans


def fill_context(ans: Answer) -> Answer:
    if not ans.tool_calls:  # agent mode records its own context
        ids = paper_ids()
        ans.context_papers = sorted({p for c in ans.chunks for p in c["paper_ids"]}
                                    | {v for r in ans.sparql_rows for v in r.values() if v in ids})
        ans.context_pages = sorted({p for c in ans.chunks for p in c["pages"]}, key=int)
    ans.cited_papers, ans.cited_pages = find_citations(ans.text)
    return ans


def ask(question: str, mode: str = "hybrid", k: int = 5, llm: LLM | None = None) -> Answer:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    llm = llm or get_llm()
    if mode == "agent":
        from rag.agent import ask_agent
        return ask_agent(question, llm)
    if mode == "hybrid2":
        return fill_context(ask_hybrid2(question, k, llm))
    ans, context = Answer(question, mode), []
    t0 = time.perf_counter()

    if mode in ("sparql", "hybrid"):
        res = text_to_sparql(question, llm)
        ans.sparql, ans.sparql_rows, ans.sparql_error = res.query, res.rows, res.error
        context.append(sparql_context(res))
    if mode in ("vector", "hybrid"):
        chunks = retriever().search(question, k)
        ans.chunks = [{k_: c[k_] for k_ in ("id", "pages", "paper_ids", "score")} for c in chunks]
        context.append("Thesis passages:\n" + chunk_context(chunks))

    system = SYSTEM.format(pages=PAGES_RULE if ans.chunks else "")
    ans.text = llm.complete(system, "\n\n".join(context) + f"\n\nQuestion: {question}", max_tokens=500)
    ans.latency_s = round(time.perf_counter() - t0, 2)
    return fill_context(ans)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("question")
    ap.add_argument("--mode", choices=MODES, default="hybrid")
    ap.add_argument("-k", type=int, default=5, help="chunks to retrieve")
    ap.add_argument("--show-context", action="store_true")
    args = ap.parse_args()
    a = ask(args.question, args.mode, args.k)
    if args.show_context:
        if a.sparql:
            print(f"--- SPARQL ---\n{a.sparql}\n--- rows ---\n{a.sparql_rows or a.sparql_error}\n")
        for t in a.tool_calls:
            print(f"tool {t['name']}({t['arguments']}) ok={t['ok']}")
        for c in a.chunks:
            print(f"chunk {c['id']} pages {c['pages']} papers {c['paper_ids']} score {c['score']:.3f}")
        print()
    print(a.text)
    print(f"\n[{a.mode} · {a.latency_s}s · papers: {', '.join(a.cited_papers) or '-'}"
          f" · pages: {', '.join(a.cited_pages) or '-'}]")


if __name__ == "__main__":
    main()
