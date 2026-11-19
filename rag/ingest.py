"""Index the "État de l'art" chapter of the master's thesis for vector search.

    python -m rag.ingest [--pdf docs/master.pdf] [--pages 31-58]

1. find the chapter (PDF outline first, then headings in the page text;
   --pages overrides both),
2. cut it into ~400-token chunks with 80 tokens of overlap, each one keeping the
   page(s) it comes from,
3. link each chunk to the paper ids whose ref_master matches a [n] citation in it,
4. embed with a multilingual sentence-transformers model and store a FAISS index
   under index/.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

from rag import config

CHUNK_TOKENS = 400
OVERLAP_TOKENS = 80
CITATION = re.compile(r"\[(\d{1,3}(?:\s*[,;–-]\s*\d{1,3})*)\]")


def fold(text: str) -> str:
    """Lowercase, strip accents and unify apostrophes: "État de l’art" -> "etat de l'art"."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text.replace("’", "'")).lower().strip()


def is_chapter_title(title: str) -> bool:
    t = fold(title)
    return "etat de l'art" in t or "state of the art" in t or "related work" in t


def find_chapter(doc) -> tuple[int, int]:
    """Return the chapter's (first, last) page as 0-based PDF page indexes."""
    toc = doc.get_toc()  # [[level, title, page(1-based)], ...]
    for i, (level, title, page) in enumerate(toc):
        if is_chapter_title(title):
            end = next((p for lv, _, p in toc[i + 1:] if lv <= level), doc.page_count + 1)
            return page - 1, max(page - 1, end - 2)
    # Fallback: the first page whose top lines hold the heading, skipping the
    # table of contents (dot leaders); it ends where the next chapter starts.
    start = None
    for i, page in enumerate(doc):
        text = page.get_text()
        if "....." in text:
            continue
        head = fold(" ".join(text.splitlines()[:6]))
        if start is None and is_chapter_title(head):
            start = i
        elif start is not None and re.search(r"\bchapitre\s+\d+\b|\bchapter\s+\d+\b", head):
            return start, i - 1
    if start is not None:
        return start, doc.page_count - 1
    raise SystemExit("could not locate the 'État de l'art' chapter; pass --pages FIRST-LAST")


def clean(text: str) -> str:
    text = re.sub(r"^\s*(Chapitre|Chapter) \d+\. [^\n]*\n", "", text)  # running page header
    text = re.sub(r"-\n(?=[a-zà-ÿ])", "", text)  # re-join hyphenated words
    return re.sub(r"[ \t]*\n[ \t]*", " ", text).strip()


def ref_to_paper_ids(papers_csv: Path) -> dict[int, str]:
    with papers_csv.open(newline="", encoding="utf-8") as f:
        return {int(r["ref_master"]): r["id"] for r in csv.DictReader(f) if r["ref_master"].strip()}


def cited_refs(text: str) -> list[int]:
    refs: set[int] = set()
    for group in CITATION.findall(text):
        for part in re.split(r"\s*[,;]\s*", group):
            if m := re.fullmatch(r"(\d+)\s*[–-]\s*(\d+)", part):
                lo, hi = int(m[1]), int(m[2])
                if hi - lo < 30:
                    refs.update(range(lo, hi + 1))
            elif part.isdigit():
                refs.add(int(part))
    return sorted(refs)


def chunk_pages(pages: list[tuple[str, str]], tokenizer,
                size: int = CHUNK_TOKENS, overlap: int = OVERLAP_TOKENS) -> list[dict]:
    """pages: [(page_label, text)] -> chunks with text and the page labels they span."""
    text, starts = "", []
    for _, page_text in pages:
        starts.append(len(text))
        text += page_text + "\n"
    enc = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)
    offsets = enc["offset_mapping"]
    chunks, step = [], size - overlap
    for first in range(0, max(1, len(offsets)), step):
        window = offsets[first:first + size]
        if not window:
            break
        a, b = window[0][0], window[-1][1]
        p0 = bisect.bisect_right(starts, a) - 1
        p1 = bisect.bisect_right(starts, max(a, b - 1)) - 1
        chunks.append({"text": text[a:b].strip(),
                       "pages": [pages[i][0] for i in range(p0, p1 + 1)]})
        if first + size >= len(offsets):
            break
    return chunks


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pdf", type=Path, default=config.THESIS_PDF)
    ap.add_argument("--pages", help="override chapter detection, 1-based PDF pages, e.g. 31-58")
    args = ap.parse_args()
    if not args.pdf.exists():
        print(f"error: {args.pdf} not found (it is git-ignored; copy the thesis there)", file=sys.stderr)
        return 1

    import faiss
    import pymupdf as fitz
    from sentence_transformers import SentenceTransformer

    doc = fitz.open(args.pdf)
    if args.pages:
        a, b = (int(x) for x in args.pages.split("-"))
        first, last = a - 1, b - 1
    else:
        first, last = find_chapter(doc)
    pages = [(doc[i].get_label() or str(i + 1), clean(doc[i].get_text())) for i in range(first, last + 1)]
    print(f"chapter: PDF pages {first + 1}-{last + 1} "
          f"(printed {pages[0][0]}-{pages[-1][0]}), {sum(len(t) for _, t in pages)} chars")

    model = SentenceTransformer(config.EMBED_MODEL)
    chunks = chunk_pages(pages, model.tokenizer)
    refs = ref_to_paper_ids(config.PAPERS_CSV)
    for i, c in enumerate(chunks):
        c["id"] = i
        c["refs"] = cited_refs(c["text"])
        c["paper_ids"] = sorted({refs[r] for r in c["refs"] if r in refs})

    vectors = model.encode([f"passage: {c['text']}" for c in chunks],
                           normalize_embeddings=True, show_progress_bar=False)
    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)

    out = config.INDEX_DIR
    out.mkdir(exist_ok=True)
    faiss.write_index(index, str(out / "chunks.faiss"))
    with (out / "chunks.jsonl").open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    (out / "meta.json").write_text(json.dumps({
        "pdf_sha256": hashlib.sha256(args.pdf.read_bytes()).hexdigest(),
        "pdf_pages": [first + 1, last + 1], "embed_model": config.EMBED_MODEL,
        "chunk_tokens": CHUNK_TOKENS, "overlap_tokens": OVERLAP_TOKENS, "chunks": len(chunks),
    }, indent=2))
    linked = sum(bool(c["paper_ids"]) for c in chunks)
    print(f"indexed {len(chunks)} chunks ({linked} linked to papers) -> {out.relative_to(config.ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
