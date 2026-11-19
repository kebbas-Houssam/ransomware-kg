import sys
from pathlib import Path

from rdflib import RDF, Literal

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from build_graph import RKG, build, check, split_list  # noqa: E402

SHAPES = ROOT / "shapes/rkg-shapes.ttl"


def graph():
    return build(ROOT / "data/papers.csv", ROOT / "data/results.csv")


def test_split_list_respects_parentheses():
    assert split_list("memory artifacts (processes; DLLs); entropy") == [
        "memory artifacts (processes; DLLs)", "entropy"]


def test_graph_conforms_and_matches_csv():
    g = graph()
    assert check(g, SHAPES)[0]
    assert len(set(g.subjects(RDF.type, RKG.Paper))) == 24
    assert len(set(g.subjects(RDF.type, RKG.Result))) == 20


def test_result_without_value_is_rejected():
    g = graph()
    r = next(g.subjects(RDF.type, RKG.Result))
    g.remove((r, RKG.value, None))
    g.add((r, RKG.value, Literal("high")))
    assert not check(g, SHAPES)[0]
