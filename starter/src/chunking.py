"""Fixed-size and structure-aware chunking inside one trace unit (article)."""
import hashlib
import re

from .models import Chunk, DocumentPage

SENTENCE_END = re.compile(r"(?<=[.;:!?])\s+")


def _chunk(page: DocumentPage, tag: str, index: int, start: int, end: int) -> Chunk:
    text = page.text[start:end]
    lead = len(text) - len(text.lstrip())
    text = text.strip()
    start += lead
    end = start + len(text)
    meta = dict(page.metadata)
    meta.update({
        "chunk_index": index,
        "chunk_start": start,
        "chunk_end": end,
        "text_sha1": hashlib.sha1(text.encode("utf-8")).hexdigest(),
    })
    chunk_id = f"{tag}:{page.document_id}:D{page.page:03d}:{index:02d}"
    return Chunk(chunk_id, page.document_id, page.source, page.page, text, meta)


def fixed_size(page: DocumentPage, size: int, overlap: int, tag: str = "A") -> list[Chunk]:
    """Character windows of `size` with `overlap`; ignores sentence and paragraph boundaries."""
    if not 0 <= overlap < size:
        raise ValueError("overlap must be in [0, size)")
    step, n = size - overlap, len(page.text)
    chunks, start = [], 0
    while start < n:
        end = min(start + size, n)
        if page.text[start:end].strip():
            chunks.append(_chunk(page, tag, len(chunks), start, end))
        if end == n:
            break
        start += step
    return chunks


def _split_long(text: str, start: int, end: int, max_size: int) -> list[tuple[int, int]]:
    """Split one oversized paragraph at sentence ends, then at spaces if still too long."""
    spans, cursor = [], start
    for m in SENTENCE_END.finditer(text, start, end):
        spans.append((cursor, m.start()))
        cursor = m.end()
    spans.append((cursor, end))

    pieces = []
    for s, e in spans:
        while e - s > max_size:
            cut = text.rfind(" ", s, s + max_size)
            cut = cut if cut > s else s + max_size
            pieces.append((s, cut))
            s = cut + 1 if text[cut:cut + 1] == " " else cut
        pieces.append((s, e))

    merged = []
    for s, e in pieces:
        if merged and e - merged[-1][0] <= max_size:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    return merged


def by_paragraph(page: DocumentPage, max_size: int, tag: str = "B") -> list[Chunk]:
    """Greedily group consecutive paragraphs (lines) up to `max_size` characters.

    The article heading stays with the first paragraph; a paragraph longer than
    `max_size` is split at sentence boundaries.
    """
    text, pieces, cursor = page.text, [], 0
    for line in text.split("\n"):
        s, e = cursor, cursor + len(line)
        cursor = e + 1
        if not line.strip():
            continue
        pieces.extend([(s, e)] if e - s <= max_size else _split_long(text, s, e, max_size))

    groups = []
    for s, e in pieces:
        if groups and e - groups[-1][0] <= max_size:
            groups[-1] = (groups[-1][0], e)
        else:
            groups.append((s, e))
    return [_chunk(page, tag, i, s, e) for i, (s, e) in enumerate(groups)]
