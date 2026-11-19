"""Run both question sets through every mode and write results/benchmark.md.

    python -m bench.run [--modes vector sparql hybrid hybrid2 agent] [--sets original holdout]

Sets: bench/questions.yaml ("original 15", used for error analysis while building
the system) and bench/questions_holdout.yaml ("held-out 10", never used for tuning).

A question is correct when every expected item appears in the answer (numbers
compared with "." or "," and trailing zeros; text case- and accent-insensitive).
An answer is "cited" when it cites a paper id or page that was in its context.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import sys
import time
from pathlib import Path

import yaml

from rag.agent import Agent
from rag.ask import MODES, Answer, ask, retriever
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
    """The answer cites at least one paper id or thesis page that was in its context."""
    return bool(set(a["cited_papers"]) & set(a["context_papers"])
                or set(a["cited_pages"]) & set(a["context_pages"]))


SETS = {
    "original": ("Original 15 (used for error analysis)", ROOT / "bench/questions.yaml"),
    "holdout": ("Held-out 10 (never used for tuning)", ROOT / "bench/questions_holdout.yaml"),
}


def record(q: dict, mode: str, a: dict, err: str) -> dict:
    r = {"id": q["id"], "mode": mode, "type": q["type"], "correct": score(q["expected"], a["text"]),
         "cited": grounded_citation(a), "error": err, **a}
    print(f"{mode:7} {q['id']} {'✓' if r['correct'] else '✗'} {r['latency_s']:5.1f}s {err}", flush=True)
    return r


def failed(q: dict, mode: str, e: Exception) -> dict:
    return record(q, mode, Answer(q["question"], mode).to_dict(), f"{type(e).__name__}: {e}")


async def run_agent(questions: list[dict], llm) -> list[dict]:
    """One MCP session for the whole set; only the per-question work is timed."""
    out = []
    async with Agent(llm) as agent:
        await agent.warm_up()
        for q in questions:
            try:
                out.append(record(q, "agent", (await agent.ask(q["question"])).to_dict(), ""))
            except Exception as e:
                out.append(failed(q, "agent", e))
    return out


def section(title: str, results: list[dict], questions: list[dict], modes: list[str]) -> list[str]:
    def rate(rows, key):
        return f"{100 * sum(r[key] for r in rows) / len(rows):.0f}%" if rows else "-"

    lines = [f"## {title}", "",
             "| Mode | Accuracy | Answers with citations | Avg latency (s) | Errors |",
             "|---|---|---|---|---|"]
    for m in modes:
        rows = [r for r in results if r["mode"] == m]
        lat = statistics.mean(r["latency_s"] for r in rows) if rows else 0
        lines.append(f"| {m} | {rate(rows, 'correct')} ({sum(r['correct'] for r in rows)}/{len(rows)}) "
                     f"| {rate(rows, 'cited')} | {lat:.1f} | {sum(bool(r['error']) for r in rows)} |")
    lines += ["", "| Type | " + " | ".join(modes) + " |", "|---|" + "---|" * len(modes)]
    for t in sorted({q["type"] for q in questions}):
        ids = {q["id"] for q in questions if q["type"] == t}
        lines.append(f"| {t} ({len(ids)}) | " + " | ".join(
            rate([r for r in results if r["mode"] == m and r["id"] in ids], "correct") for m in modes) + " |")
    lines += ["", "<details><summary>Per question (✓ correct · ✗ wrong · 📎 cites its context)</summary>", "",
              "| Id | Type | Question | " + " | ".join(modes) + " |", "|---|---|---|" + "---|" * len(modes)]
    by = {(r["id"], r["mode"]): r for r in results}
    for q in questions:
        cells = []
        for m in modes:
            r = by.get((q["id"], m))
            cells.append("-" if r is None else ("✓" if r["correct"] else "✗") + (" 📎" if r["cited"] else ""))
        lines.append(f"| {q['id']} | {q['type']} | {q['question']} | " + " | ".join(cells) + " |")
    return lines + ["", "</details>", ""]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--modes", nargs="+", choices=MODES, default=list(MODES))
    ap.add_argument("--sets", nargs="+", choices=list(SETS), default=list(SETS))
    ap.add_argument("--out", type=Path, default=ROOT / "results/benchmark.md")
    args = ap.parse_args()

    if set(args.modes) - {"vector"}:
        try:
            run_sparql("ASK {}")
        except Exception as e:
            sys.exit(f"Fuseki is not reachable ({e}); run `make up load` first")
    llm = get_llm()
    llm.complete("Reply OK.", "ping", max_tokens=5)  # load models before timing
    if set(args.modes) & {"vector", "hybrid", "hybrid2"}:
        retriever().search("warm-up", 1)

    started = time.strftime("%Y-%m-%d %H:%M")
    lines = ["# Benchmark", "", f"LLM `{llm.provider}:{llm.model}` · run {started} · modes: "
             + ", ".join(args.modes), "",
             "A question is correct when every expected value appears in the answer; an answer",
             "is cited when it cites a paper id or thesis page that was in its context.", ""]
    all_results = {}
    for name in args.sets:
        title, path = SETS[name]
        questions = yaml.safe_load(path.read_text(encoding="utf-8"))
        results = []
        for m in args.modes:
            if m == "agent":
                results += asyncio.run(run_agent(questions, llm))
                continue
            for q in questions:
                try:
                    results.append(record(q, m, ask(q["question"], m, llm=llm).to_dict(), ""))
                except Exception as e:  # keep going; the error is reported
                    results.append(failed(q, m, e))
        all_results[name] = results
        lines += section(title, results, questions, args.modes)

    args.out.parent.mkdir(exist_ok=True)
    args.out.with_suffix(".json").write_text(json.dumps(all_results, ensure_ascii=False, indent=1))
    args.out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
