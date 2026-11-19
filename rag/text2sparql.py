"""Question -> SPARQL with an LLM, executed on Fuseki (one retry on syntax error).

    python -m rag.text2sparql "How many papers target Windows?"
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from functools import lru_cache

import requests
from rdflib import OWL, RDF, RDFS, Graph

from rag import config
from rag.llm import LLM, get_llm

PREFIXES = """PREFIX rkg:  <https://w3id.org/rkg#>
PREFIX dct:  <http://purl.org/dc/terms/>
PREFIX bibo: <http://purl.org/ontology/bibo/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>"""

EXAMPLES = """Question: Which papers use SVM, and in which year?
```sparql
SELECT ?paper ?year WHERE {
  ?p rkg:usesMethod/rdfs:label "SVM" ; dct:issued ?y .
  BIND(STRAFTER(STR(?p), "/paper/") AS ?paper)
  BIND(STR(?y) AS ?year)
}
```

Question: Quels résultats rapporte lee2025fpe ?
```sparql
SELECT ?metric ?value ?unit ?condition WHERE {
  <https://w3id.org/rkg/id/paper/lee2025fpe> rkg:reports ?r .
  ?r rkg:metric/rdfs:label ?metric ; rkg:value ?value .
  OPTIONAL { ?r rkg:unit ?unit } OPTIONAL { ?r rkg:condition ?condition }
}
```

Question: Compare the false positive rate of unveil2016 and aljabri2024.
```sparql
SELECT ?paper ?value ?unit WHERE {
  VALUES ?p { <https://w3id.org/rkg/id/paper/unveil2016> <https://w3id.org/rkg/id/paper/aljabri2024> }
  ?p rkg:reports ?r .
  ?r rkg:metric/rdfs:label "false_positive_rate" ; rkg:value ?value .
  OPTIONAL { ?r rkg:unit ?unit }
  BIND(STRAFTER(STR(?p), "/paper/") AS ?paper)
}
```"""


@dataclass
class SparqlResult:
    query: str = ""
    rows: list[dict] = field(default_factory=list)
    error: str = ""
    attempts: int = 0

    def as_table(self, limit: int = 40) -> str:
        if not self.rows:
            return "(no rows)" if not self.error else f"(error: {self.error})"
        cols = list(self.rows[0])
        lines = [" | ".join(cols)] + [" | ".join(r.get(c, "") for c in cols) for r in self.rows[:limit]]
        return "\n".join(lines)


def run_sparql(query: str) -> list[dict]:
    r = requests.post(config.SPARQL_ENDPOINT, data={"query": query}, timeout=30,
                      headers={"Accept": "application/sparql-results+json"})
    if r.status_code == 400:
        raise SyntaxError(r.text.strip()[:500])
    r.raise_for_status()
    data = r.json()
    if "boolean" in data:
        return [{"answer": str(data["boolean"]).lower()}]
    return [{k: v["value"] for k, v in b.items()} for b in data["results"]["bindings"]]


@lru_cache(maxsize=1)
def schema_info() -> dict:
    """Ontology classes/properties + the controlled vocabulary actually in the graph."""
    g = Graph().parse(config.ONTOLOGY)
    short = lambda u: g.namespace_manager.normalizeUri(u)  # noqa: E731
    comment = lambda u: str(g.value(u, RDFS.comment) or "")  # noqa: E731
    classes = [{"name": short(c), "comment": comment(c)} for c in sorted(g.subjects(RDF.type, OWL.Class))]
    props = []
    for kind in (OWL.ObjectProperty, OWL.DatatypeProperty):
        for p in sorted(set(g.subjects(RDF.type, kind))):
            props.append({"name": short(p), "domain": short(g.value(p, RDFS.domain)),
                          "range": short(g.value(p, RDFS.range)), "comment": comment(p)})
    extra_props = ["- dct:title (rkg:Paper -> string)", "- dct:issued (rkg:Paper -> xsd:gYear)",
                   "- dct:source (rkg:Result -> string): table the number comes from",
                   "- bibo:volume / bibo:issue / bibo:identifier (rkg:Paper -> string)",
                   "- rdfs:label: name of every entity except Paper and Result"]
    labels = {}
    for cls in ["AnalysisType", "MethodFamily", "Platform", "Metric", "Dataset", "Method", "DataSource"]:
        labels[f"rkg:{cls}"] = [r["l"] for r in run_sparql(
            f"{PREFIXES} SELECT ?l WHERE {{ ?x a rkg:{cls} ; rdfs:label ?l }} ORDER BY ?l")]
    roles = [r["r"] for r in run_sparql(f"{PREFIXES} SELECT DISTINCT ?r WHERE {{ ?p rkg:role ?r }}")]
    papers = run_sparql(f"""{PREFIXES}
        SELECT ?id ?year ?title (GROUP_CONCAT(?a; separator=", ") AS ?authors) WHERE {{
          ?p a rkg:Paper ; dct:title ?title ; dct:issued ?year ; rkg:hasAuthor/rdfs:label ?a .
          BIND(STRAFTER(STR(?p), "/paper/") AS ?id) }} GROUP BY ?id ?year ?title ORDER BY ?id""")
    return {"prefixes": PREFIXES, "classes": classes, "properties": props,
            "other_properties": [line[2:] for line in extra_props], "labels": labels,
            "roles": roles, "papers": papers,
            "paper_uri_pattern": "https://w3id.org/rkg/id/paper/<ID>"}


@lru_cache(maxsize=1)
def schema_prompt() -> str:
    info = schema_info()
    classes = [f"- {c['name']}: {c['comment']}" for c in info["classes"]]
    props = [f"- {p['name']} ({p['domain']} -> {p['range']}): {p['comment']}" for p in info["properties"]]
    props += [f"- {line}" for line in info["other_properties"]]
    vocab = [f"- {cls}: " + "; ".join(json.dumps(l, ensure_ascii=False) for l in labels)
             for cls, labels in info["labels"].items()]
    vocab.append("- rkg:role values: " + "; ".join(json.dumps(r) for r in info["roles"]))
    paper_lines = [f"- {p['id']}: {p['authors']} ({p['year']}) {p['title'][:90]}" for p in info["papers"]]
    return "\n".join([
        "Prefixes:", PREFIXES, "", "Classes:", *classes, "", "Properties:", *props, "",
        "Labels present in the graph (match them exactly, case-sensitive):", *vocab, "",
        "Papers (URI = <https://w3id.org/rkg/id/paper/ID>):", *paper_lines,
    ])


SYSTEM = """You translate questions (English or French) about a knowledge graph of
ransomware-detection papers into one SPARQL 1.1 SELECT query for Apache Jena.

{schema}

Rules:
- Use only the classes and properties listed above. Prefixes are added for you.
- Match entities through rdfs:label with the exact strings listed, or use paper URIs.
- Return the paper id with BIND(STRAFTER(STR(?p), "/paper/") AS ?paper) whenever
  papers are involved, and STR() of years.
- Counting questions: use COUNT(DISTINCT ...).
- Only papers report results (?p rkg:reports ?r). A Dataset is reached only through
  ?r rkg:onDataset ?d; a paper and a dataset may share a name.
- rkg:analysisType is on rkg:Approach (Paper rkg:hasApproach ?a . ?a rkg:analysisType ?t).
- Reply with only the query inside a ```sparql block.

Examples:
{examples}"""


def extract_query(text: str) -> str:
    m = re.search(r"```(?:sparql)?\s*(.*?)```", text, re.S | re.I)
    q = (m[1] if m else text).strip()
    q = "\n".join(line for line in q.splitlines() if not line.strip().upper().startswith("PREFIX "))
    return f"{PREFIXES}\n{q}"


def text_to_sparql(question: str, llm: LLM | None = None) -> SparqlResult:
    llm = llm or get_llm()
    system = SYSTEM.format(schema=schema_prompt(), examples=EXAMPLES)
    user = f"Question: {question}"
    res = SparqlResult()
    for attempt in (1, 2):
        res.attempts = attempt
        res.query = extract_query(llm.complete(system, user, max_tokens=600))
        try:
            res.rows, res.error = run_sparql(res.query), ""
            return res
        except SyntaxError as e:
            res.error = str(e)
            user = (f"Question: {question}\n\nYour previous query failed:\n```sparql\n{res.query}\n```\n"
                    f"Fuseki error: {res.error}\nReturn a corrected query.")
    return res


if __name__ == "__main__":
    out = text_to_sparql(" ".join(sys.argv[1:]))
    print(out.query, "\n", out.as_table(), sep="\n")
