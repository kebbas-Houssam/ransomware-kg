"""Answer a question about the literature review.

    python -m rag.ask "question" --mode vector|sparql|hybrid [--show-context]

vector  thesis chunks retrieved from the FAISS index -> LLM answer
sparql  LLM-generated SPARQL on Fuseki -> LLM verbalises the rows
hybrid  both contexts together; the answer cites paper ids and thesis pages
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

MODES = ("vector", "sparql", "hybrid")

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


def ask(question: str, mode: str = "hybrid", k: int = 5, llm: LLM | None = None) -> Answer:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    llm = llm or get_llm()
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
    ans.cited_papers, ans.cited_pages = find_citations(ans.text)
    return ans


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
        for c in a.chunks:
            print(f"chunk {c['id']} pages {c['pages']} papers {c['paper_ids']} score {c['score']:.3f}")
        print()
    print(a.text)
    print(f"\n[{a.mode} · {a.latency_s}s · papers: {', '.join(a.cited_papers) or '-'}"
          f" · pages: {', '.join(a.cited_pages) or '-'}]")


if __name__ == "__main__":
    main()
