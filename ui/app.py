"""Streamlit UI: ask a question in any mode, see the answer, its sources and the
generated SPARQL / tool calls.

    streamlit run ui/app.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

from rag import config  # noqa: E402
from rag.ask import MODES, ask  # noqa: E402
from rag.llm import get_llm  # noqa: E402

MODE_HELP = {
    "hybrid2": "graph facts for numbers, thesis passages for explanations",
    "agent": "LLM calls the MCP tools (max 6)",
    "hybrid": "graph rows + passages (phase 2)",
    "sparql": "text-to-SPARQL only",
    "vector": "thesis passages only",
}

st.set_page_config(page_title="Ransomware KG", page_icon="🔎", layout="wide")


@st.cache_resource
def llm():
    return get_llm()


@st.cache_data
def paper_titles() -> dict[str, str]:
    with config.PAPERS_CSV.open(newline="", encoding="utf-8") as f:
        return {r["id"]: f"{r['title']} ({r['year']})" for r in csv.DictReader(f)}


st.title("Ransomware-detection knowledge graph")
st.caption(f"LLM: `{llm().provider}:{llm().model}` · graph: {config.SPARQL_ENDPOINT}")

with st.form("ask"):
    question = st.text_input("Question (English or French)",
                             placeholder="Combien d'articles ciblent Windows ?")
    order = ["hybrid2", "agent", "hybrid", "sparql", "vector"]
    mode = st.radio("Mode", [m for m in order if m in MODES], horizontal=True,
                    format_func=lambda m: f"{m} — {MODE_HELP[m]}")
    submitted = st.form_submit_button("Ask", type="primary")

if submitted and question.strip():
    with st.spinner(f"Answering in {mode} mode…"):
        try:
            st.session_state["answer"] = ask(question.strip(), mode, llm=llm())
        except Exception as e:  # Fuseki down, Ollama down, missing index…
            st.session_state.pop("answer", None)
            st.error(f"{type(e).__name__}: {e}")

a = st.session_state.get("answer")
if a:
    st.subheader("Answer")
    st.markdown(a.text or "_(empty answer)_")
    st.caption(f"{a.mode} · {a.latency_s:.1f} s")

    titles = paper_titles()
    left, right = st.columns(2)
    with left:
        st.markdown("**Cited papers**")
        if a.cited_papers:
            for pid in a.cited_papers:
                mark = "" if pid in a.context_papers else " ⚠️ not in the retrieved context"
                st.markdown(f"- `{pid}` — {titles.get(pid, '?')}{mark}")
        else:
            st.markdown("_none_")
    with right:
        st.markdown("**Cited thesis pages**")
        if a.cited_pages:
            st.markdown(", ".join(
                f"p. {p}" + ("" if p in a.context_pages else " ⚠️") for p in a.cited_pages))
        else:
            st.markdown("_none_")
        if a.context_pages:
            st.caption("Pages given to the model: " + ", ".join(a.context_pages))

    if a.sparql:
        with st.expander("Generated SPARQL", expanded=False):
            st.code(a.sparql, language="sparql")
            if a.sparql_rows:
                st.dataframe(a.sparql_rows, use_container_width=True)
            else:
                st.warning(a.sparql_error or "The query returned no rows.")
    if a.tool_calls:
        with st.expander(f"Tool calls ({len(a.tool_calls)})", expanded=False):
            for i, t in enumerate(a.tool_calls, 1):
                st.markdown(f"**{i}. `{t['name']}`** {'✅' if t['ok'] else '❌'}")
                st.json(t["arguments"])
                st.code(t["result"], language="json")
    if a.chunks:
        with st.expander(f"Retrieved thesis passages ({len(a.chunks)})", expanded=False):
            for c in a.chunks:
                st.markdown(f"- chunk {c['id']} · pages {', '.join(c['pages'])} · "
                            f"cites {', '.join(c['paper_ids']) or '—'} · score {c['score']:.3f}")
