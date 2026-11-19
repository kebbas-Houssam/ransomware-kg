"""Run the benchmark questions through every mode and write results/benchmark.md.

    python -m bench.run [--modes vector sparql hybrid] [--only q01 q02]

A question is correct when every expected item appears in the answer (numbers
compared with "." or "," and trailing zeros; text case- and accent-insensitive).
An answer is "cited" when it cites a paper id or page that was in its context.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

import yaml

from rag.ask import MODES, ask, retriever
from rag.ingest import fold
from rag.llm import get_llm
from rag.text2sparql import run_sparql

ROOT = Path(__file__).resolve().parent.parent
NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def matches(item: str, answer: str) -> bool:
    if NUMBER.fullmatch(item):
        num = re.escape(item.replace(",", ".")).replace(r"\.", "[.,]")
        if "." not in item and "," not in item:
            num += r"(?:[.,]0+)?"
        else:
            num += "0*"
        return re.search(rf"(?<![\w.,]){num}(?![\d]|[.,]\d)", answer) is not None
    return fold(item) in fold(answer)


def score(expected: list, answer: str) -> bool:
    answer = re.sub(r"\(\s*pp?\.\s*[\d\s,–-]+\)", " ", answer)  # page citations are not answers
    return all(any(matches(str(alt), answer) for alt in (item if isinstance(item, list) else [item]))
               for item in expected)


def grounded_citation(a: dict) -> bool:
    ctx_papers = {pid for c in a["chunks"] for pid in c["paper_ids"]}
    ctx_papers |= {v for row in a["sparql_rows"] for v in row.values()}
    ctx_pages = {p for c in a["chunks"] for p in c["pages"]}
    return bool(set(a["cited_papers"]) & ctx_papers or set(a["cited_pages"]) & ctx_pages)


def write_report(results: list[dict], questions: list[dict], modes: list[str], llm_name: str,
                 path: Path) -> str:
    def rate(rows, key):
        return f"{100 * sum(r[key] for r in rows) / len(rows):.0f}%" if rows else "-"

    lines = [f"# Benchmark", "",
             f"{len(questions)} questions (FR/EN) · LLM `{llm_name}` · run {time.strftime('%Y-%m-%d %H:%M')}", "",
             "| Mode | Accuracy | Answers with citations | Avg latency (s) | Errors |",
             "|---|---|---|---|---|"]
    for m in modes:
        rows = [r for r in results if r["mode"] == m]
        lat = statistics.mean(r["latency_s"] for r in rows) if rows else 0
        lines.append(f"| {m} | {rate(rows, 'correct')} ({sum(r['correct'] for r in rows)}/{len(rows)}) "
                     f"| {rate(rows, 'cited')} | {lat:.1f} | {sum(bool(r['error']) for r in rows)} |")
    types = sorted({q["type"] for q in questions})
    lines += ["", "## Accuracy by question type", "",
              "| Type | " + " | ".join(modes) + " |", "|---|" + "---|" * len(modes)]
    for t in types:
        ids = {q["id"] for q in questions if q["type"] == t}
        lines.append(f"| {t} ({len(ids)}) | " + " | ".join(
            rate([r for r in results if r["mode"] == m and r["id"] in ids], "correct") for m in modes) + " |")
    lines += ["", "## Per question", "", "✓ correct · ✗ wrong · 📎 cites its context", "",
              "| Id | Type | Question | " + " | ".join(modes) + " |", "|---|---|---|" + "---|" * len(modes)]
    by = {(r["id"], r["mode"]): r for r in results}
    for q in questions:
        cells = []
        for m in modes:
            r = by.get((q["id"], m))
            cells.append("-" if r is None else ("✓" if r["correct"] else "✗") + (" 📎" if r["cited"] else ""))
        lines.append(f"| {q['id']} | {q['type']} | {q['question']} | " + " | ".join(cells) + " |")
    text = "\n".join(lines) + "\n"
    path.write_text(text, encoding="utf-8")
    return text


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--modes", nargs="+", choices=MODES, default=list(MODES))
    ap.add_argument("--only", nargs="+", help="question ids")
    ap.add_argument("--out", type=Path, default=ROOT / "results/benchmark.md")
    args = ap.parse_args()

    questions = yaml.safe_load((ROOT / "bench/questions.yaml").read_text(encoding="utf-8"))
    if args.only:
        questions = [q for q in questions if q["id"] in args.only]
    if set(args.modes) & {"sparql", "hybrid"}:
        try:
            run_sparql("ASK {}")
        except Exception as e:
            sys.exit(f"Fuseki is not reachable ({e}); run `make up load` first")
    llm = get_llm()
    llm.complete("Reply OK.", "ping", max_tokens=5)  # load models before timing
    if set(args.modes) & {"vector", "hybrid"}:
        retriever().search("warm-up", 1)

    results = []
    for m in args.modes:
        for q in questions:
            try:
                a = ask(q["question"], m, llm=llm).to_dict()
                err = ""
            except Exception as e:  # keep going; the error is reported
                a = {"text": "", "chunks": [], "sparql_rows": [], "cited_papers": [],
                     "cited_pages": [], "latency_s": 0.0, "sparql": ""}
                err = f"{type(e).__name__}: {e}"
            r = {"id": q["id"], "mode": m, "type": q["type"], "correct": score(q["expected"], a["text"]),
                 "cited": grounded_citation(a), "error": err, **a}
            results.append(r)
            print(f"{m:6} {q['id']} {'✓' if r['correct'] else '✗'} {r['latency_s']:5.1f}s {err}",
                  flush=True)

    args.out.parent.mkdir(exist_ok=True)
    args.out.with_suffix(".json").write_text(json.dumps(results, ensure_ascii=False, indent=1))
    print(write_report(results, questions, args.modes, f"{llm.provider}:{llm.model}", args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
