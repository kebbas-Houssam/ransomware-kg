"""Read-only MCP server (stdio) over the ransomware-detection knowledge graph.

    python -m mcp_server            # or: python mcp_server/server.py

Tools: get_schema, sparql_select, search_papers, get_paper, get_results,
search_thesis. Everything is read-only; sparql_select only accepts SELECT/ASK.
"""
from __future__ import annotations

import re
import sys
from functools import lru_cache
from pathlib import Path

if __package__ in (None, ""):  # launched as a script, e.g. by Claude Desktop
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from rdflib import Literal
from rdflib.plugins.sparql import prepareQuery

from rag.ingest import fold
from rag.text2sparql import PREFIXES, run_sparql, schema_info

MAX_ROWS = 100
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True,
                            open_world_hint=False)
PAPER_ID = re.compile(r"^[a-z0-9]+$")

mcp = MCPServer(  # noqa: E501
    "ransomware-kg",
    log_level="WARNING",
    instructions=(
        "Knowledge graph of the ransomware-detection papers reviewed in a master's thesis, "
        "plus vector search over the thesis 'État de l'art' chapter. Numbers (results, counts) "
        "come from the graph tools; explanations from search_thesis. Cite paper ids and pages."
    ),
)


def checked_query(query: str) -> str:
    """Return a safe, prefixed query with LIMIT, or raise ToolError.

    Only SELECT and ASK parse (SPARQL Update is a different grammar, so INSERT,
    DELETE, LOAD, DROP... are rejected), CONSTRUCT/DESCRIBE are refused, and a
    SELECT without a top-level LIMIT gets LIMIT 100.
    """
    body = "\n".join(line for line in query.strip().splitlines()
                     if not line.strip().upper().startswith("PREFIX "))
    full = f"{PREFIXES}\n{body}"
    try:
        algebra = prepareQuery(full).algebra
    except Exception as e:  # rdflib raises pyparsing errors for updates and bad syntax
        raise ToolError(f"rejected: only read-only SELECT/ASK queries are allowed ({e})") from None
    if algebra.name not in ("SelectQuery", "AskQuery"):
        raise ToolError(f"rejected: {algebra.name} is not allowed, use SELECT or ASK")
    if algebra.name == "SelectQuery" and algebra.p.name != "Slice":
        full += f"\nLIMIT {MAX_ROWS}"
    return full


def run(query: str) -> list[dict]:
    try:
        return run_sparql(query)[:MAX_ROWS]
    except SyntaxError as e:
        raise ToolError(f"Fuseki rejected the query: {e}") from None


@mcp.tool(annotations=READ_ONLY)
def get_schema() -> dict:
    """Ontology of the graph: prefixes, classes, properties (domain -> range), the exact
    rdfs:label values present for each vocabulary class, paper roles and the paper list.
    Read this before writing SPARQL."""
    return schema_info()


@mcp.tool(annotations=READ_ONLY)
def sparql_select(query: str) -> dict:
    """Run a read-only SPARQL SELECT or ASK query on the graph (prefixes rkg:, dct:,
    bibo:, rdfs:, xsd: are added automatically; at most 100 rows)."""
    q = checked_query(query)
    rows = run(q)
    return {"query": q, "rows": rows, "row_count": len(rows)}


@lru_cache(maxsize=1)
def _papers() -> list[dict]:
    return run_sparql(f"""{PREFIXES}
    SELECT ?id ?title ?year ?venue ?role
           (GROUP_CONCAT(DISTINCT ?a; separator=", ") AS ?authors)
           (GROUP_CONCAT(DISTINCT ?x; separator=" | ") AS ?keywords)
    WHERE {{
      ?p a rkg:Paper ; dct:title ?title ; dct:issued ?y ; rkg:role ?role ;
         rkg:publishedIn/rdfs:label ?venue ; rkg:hasAuthor/rdfs:label ?a .
      OPTIONAL {{ ?p (rkg:hasApproach|rkg:usesMethod|rkg:analysesData|rkg:targetsPlatform|rkg:methodFamily)/rdfs:label ?x }}
      BIND(STRAFTER(STR(?p), "/paper/") AS ?id) BIND(STR(?y) AS ?year)
    }} GROUP BY ?id ?title ?year ?venue ?role ORDER BY ?id""")


@mcp.tool(annotations=READ_ONLY)
def search_papers(text: str) -> dict:
    """Find papers by words in their id, title, authors, venue, role, approach, methods,
    data sources, platforms or method family (case- and accent-insensitive). Papers
    matching the most words are returned, with their count."""
    words = [w for w in fold(text).split() if len(w) > 1]
    scored = []
    for p in _papers():
        hay = fold(" ".join(p.values()))
        score = sum(w in hay for w in words)
        if score:
            scored.append((score, p))
    best = max((s for s, _ in scored), default=0)
    hits = [{k: p[k] for k in ("id", "title", "year", "authors", "venue", "role")}
            for s, p in scored if s == best]
    return {"count": len(hits), "matched_words": best, "of_words": len(words), "papers": hits}


@mcp.tool(annotations=READ_ONLY)
def get_paper(paper_id: str) -> dict:
    """Full record of one paper (e.g. 'wang2024deftpunk'): title, year, authors, venue,
    role, approach, analysis type, method family, methods, data sources, platforms,
    thesis reference number and reported results."""
    if not PAPER_ID.match(paper_id):
        raise ToolError("paper_id must look like 'kebbas2025' (lowercase letters and digits)")
    uri = f"<https://w3id.org/rkg/id/paper/{paper_id}>"
    rows = run(f"""{PREFIXES}
    SELECT ?prop ?value WHERE {{
      {{ {uri} ?pr ?o . FILTER(?pr != rkg:reports)
         OPTIONAL {{ ?o rdfs:label ?l }} BIND(COALESCE(?l, STR(?o)) AS ?value)
         BIND(REPLACE(STR(?pr), "^.*[#/]", "") AS ?prop) }}
      UNION
      {{ {uri} rkg:hasApproach/rkg:analysisType/rdfs:label ?value . BIND("analysisType" AS ?prop) }}
    }}""")
    if not rows:
        raise ToolError(f"no paper with id {paper_id!r}; use search_papers")
    record: dict = {"id": paper_id}
    for r in rows:
        if r["prop"] == "type":
            continue
        record.setdefault(r["prop"], []).append(r["value"])
    record = {k: (v[0] if isinstance(v, list) and len(v) == 1 and k not in
                  ("hasAuthor", "usesMethod", "analysesData", "targetsPlatform") else v)
              for k, v in record.items()}
    record["results"] = get_results(paper_id=paper_id)
    return record


@mcp.tool(annotations=READ_ONLY)
def get_results(paper_id: str = "", metric: str = "", dataset: str = "") -> list[dict]:
    """Reported results, optionally filtered by paper id, metric label (e.g. 'accuracy',
    'precision', 'f2_score') and dataset label (e.g. 'DeftPunk'). Each row has paper,
    metric, value, unit, dataset, condition and source."""
    filters = []
    if paper_id:
        if not PAPER_ID.match(paper_id):
            raise ToolError("paper_id must look like 'kebbas2025'")
        filters.append(f"FILTER(?p = <https://w3id.org/rkg/id/paper/{paper_id}>)")
    if metric:
        m = metric.strip().lower().replace("-", "_").replace(" ", "_")
        filters.append(f"FILTER(LCASE(?metric) = {Literal(m).n3()})")
    if dataset:
        filters.append(f"FILTER(LCASE(?dataset) = {Literal(dataset.strip().lower()).n3()})")
    return run(f"""{PREFIXES}
    SELECT ?paper ?metric ?value ?unit ?dataset ?condition ?source WHERE {{
      ?p rkg:reports ?r . ?r rkg:metric/rdfs:label ?metric ; rkg:value ?value .
      OPTIONAL {{ ?r rkg:unit ?unit }} OPTIONAL {{ ?r rkg:onDataset/rdfs:label ?dataset }}
      OPTIONAL {{ ?r rkg:condition ?condition }} OPTIONAL {{ ?r dct:source ?source }}
      BIND(STRAFTER(STR(?p), "/paper/") AS ?paper)
      {" ".join(filters)}
    }} ORDER BY ?paper ?metric""")


@lru_cache(maxsize=1)
def _retriever():
    from rag.retrieve import Retriever
    return Retriever()


@mcp.tool(annotations=READ_ONLY)
def search_thesis(query: str, k: int = 4) -> list[dict]:
    """Semantic search (FR/EN) over the thesis chapter 'État de l'art'. Returns passages
    with their printed thesis pages and the paper ids they cite. Use for explanations."""
    k = max(1, min(int(k), 10))
    return [{"pages": c["pages"], "paper_ids": c["paper_ids"], "score": round(c["score"], 3),
             "text": c["text"]} for c in _retriever().search(query, k)]


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
