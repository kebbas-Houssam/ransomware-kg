import re

from bench.run import score
from rag.ask import find_citations
from rag.ingest import chunk_pages, cited_refs


def fake_tokenizer(text, **_):
    return {"offset_mapping": [m.span() for m in re.finditer(r"\S+", text)]}


def test_chunks_keep_page_labels_and_overlap():
    pages = [("10", "a " * 6), ("11", "b " * 6)]
    chunks = chunk_pages(pages, fake_tokenizer, size=5, overlap=2)
    assert chunks[0]["pages"] == ["10"]
    assert any(c["pages"] == ["10", "11"] for c in chunks)
    assert chunks[-1]["pages"] == ["11"]


def test_citation_ranges_and_lists():
    assert cited_refs("as shown in [3], [5-7] and [12, 14]") == [3, 5, 6, 7, 12, 14]


def test_answer_citations():
    papers, pages = find_citations("DeftPunk (wang2024deftpunk) reaches 95.8% (p. 42).")
    assert papers == ["wang2024deftpunk"] and pages == ["42"]


def test_scoring_numbers_and_alternatives():
    assert score(["98.2"], "accuracy of 98,20 %")
    assert score([["3", "three"]], "There are three surveys.")
    assert not score(["2025"], "see kebbas2025")
    assert not score([["4"]], "static papers (p. 4)")
