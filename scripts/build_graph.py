#!/usr/bin/env python3
"""Build the ransomware-detection knowledge graph from the curated CSV files.

    data/papers.csv + data/results.csv  ->  data/graph.ttl

The graph is validated against shapes/rkg-shapes.ttl with pySHACL; on any
violation the report is printed, nothing is written, and the exit code is 1.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import unicodedata
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pyshacl import validate
from rdflib import RDF, RDFS, XSD, Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS

ROOT = Path(__file__).resolve().parent.parent
RKG = Namespace("https://w3id.org/rkg#")
ID = "https://w3id.org/rkg/id/"


def slug(text: str) -> str:
    """'Jürgen Schmidhuber' -> 'jurgen-schmidhuber' (stable, ASCII, URL-safe)."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def split_list(cell: str) -> list[str]:
    """Split on ';' but not inside parentheses: 'a (b; c); d' -> ['a (b; c)', 'd']."""
    items, buf, depth = [], [], 0
    for ch in cell:
        depth += (ch == "(") - (ch == ")")
        if ch == ";" and depth == 0:
            items.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    items.append("".join(buf))
    return [i.strip() for i in items if i.strip()]


class Builder:
    def __init__(self) -> None:
        self.g = Graph()
        self.g.bind("rkg", RKG)
        self.g.bind("dct", DCTERMS)

    def entity(self, kind: str, cls: URIRef, label: str) -> URIRef:
        """Return the URI of a labelled entity, creating it on first use."""
        uri = URIRef(f"{ID}{kind}/{slug(label)}")
        if (uri, RDF.type, cls) not in self.g:
            self.g.add((uri, RDF.type, cls))
            self.g.add((uri, RDFS.label, Literal(label)))
        return uri

    def add_paper(self, row: dict[str, str]) -> None:
        p = URIRef(f"{ID}paper/{row['id']}")
        g = self.g
        g.add((p, RDF.type, RKG.Paper))
        g.add((p, DCTERMS.title, Literal(row["title"])))
        g.add((p, DCTERMS.issued, Literal(row["year"], datatype=XSD.gYear)))
        g.add((p, RKG.role, Literal(row["role"])))
        if row["ref_master"]:
            g.add((p, RKG.thesisRef, Literal(int(row["ref_master"]))))

        authors = row["authors"]
        if authors.endswith("et al."):
            authors = authors[: -len("et al.")]
            g.add((p, RKG.authorListComplete, Literal(False)))
        for name in split_list(authors):
            g.add((p, RKG.hasAuthor, self.entity("author", RKG.Author, name)))

        venue = self.entity("venue", RKG.Venue, row["venue"])
        g.add((p, RKG.publishedIn, venue))
        if row["venue_type"]:
            g.set((venue, RKG.venueType, Literal(row["venue_type"])))

        if row["approach"]:
            a = self.entity("approach", RKG.Approach, row["approach"])
            g.add((p, RKG.hasApproach, a))
            if row["analysis_type"]:
                g.add((a, RKG.analysisType,
                       self.entity("analysis-type", RKG.AnalysisType, row["analysis_type"])))
        if row["method_family"]:
            g.add((p, RKG.methodFamily,
                   self.entity("method-family", RKG.MethodFamily, row["method_family"])))
        for col, prop, kind, cls in [
            ("data_source", RKG.analysesData, "data-source", RKG.DataSource),
            ("platform", RKG.targetsPlatform, "platform", RKG.Platform),
            ("methods", RKG.usesMethod, "method", RKG.Method),
        ]:
            for item in split_list(row[col]):
                g.add((p, prop, self.entity(kind, cls, item)))

    def add_result(self, row: dict[str, str], paper_ids: set[str]) -> None:
        if row["paper_id"] not in paper_ids:
            raise ValueError(f"results.csv references unknown paper {row['paper_id']!r}")
        try:
            value = Decimal(row["value"])
        except InvalidOperation:
            raise ValueError(f"non-numeric value {row['value']!r} for {row['paper_id']}") from None
        key = "-".join(filter(None, [row["paper_id"], slug(row["metric"]), slug(row["dataset"])]))
        r = URIRef(f"{ID}result/{key}")
        g = self.g
        if (r, RDF.type, RKG.Result) in g:
            raise ValueError(f"duplicate result {key}")
        g.add((r, RDF.type, RKG.Result))
        g.add((URIRef(f"{ID}paper/{row['paper_id']}"), RKG.reports, r))
        g.add((r, RKG.metric, self.entity("metric", RKG.Metric, row["metric"])))
        g.add((r, RKG.value, Literal(value, datatype=XSD.decimal)))
        if row["unit"]:
            g.add((r, RKG.unit, Literal(row["unit"])))
        if row["dataset"]:
            g.add((r, RKG.onDataset, self.entity("dataset", RKG.Dataset, row["dataset"])))
        if row["condition"]:
            g.add((r, RKG.condition, Literal(row["condition"])))
        if row["source"]:
            g.add((r, DCTERMS.source, Literal(row["source"])))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]


def build(papers: Path, results: Path) -> Graph:
    b = Builder()
    paper_rows = read_csv(papers)
    for row in paper_rows:
        b.add_paper(row)
    ids = {row["id"] for row in paper_rows}
    for row in read_csv(results):
        b.add_result(row, ids)
    return b.g


def check(g: Graph, shapes: Path) -> tuple[bool, str]:
    conforms, _, report = validate(g, shacl_graph=Graph().parse(shapes), inference="none")
    return conforms, report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--papers", type=Path, default=ROOT / "data/papers.csv")
    ap.add_argument("--results", type=Path, default=ROOT / "data/results.csv")
    ap.add_argument("--shapes", type=Path, default=ROOT / "shapes/rkg-shapes.ttl")
    ap.add_argument("--out", type=Path, default=ROOT / "data/graph.ttl")
    args = ap.parse_args()

    try:
        g = build(args.papers, args.results)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    conforms, report = check(g, args.shapes)
    if not conforms:
        print(report, file=sys.stderr)
        print("SHACL validation failed; graph not written.", file=sys.stderr)
        return 1
    g.serialize(args.out, format="turtle")
    print(f"wrote {args.out.relative_to(ROOT) if args.out.is_relative_to(ROOT) else args.out}: "
          f"{len(g)} triples, SHACL conforms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
