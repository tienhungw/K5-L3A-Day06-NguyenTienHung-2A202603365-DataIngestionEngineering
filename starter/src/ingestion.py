"""Read and normalize source documents into traceable units.

The two labour codes are not paginated (Word .doc and HTML), so the trace unit
is one article ("Điều"). `DocumentPage.page` holds the article number.
"""
import hashlib
import re
import struct
import unicodedata
from html.parser import HTMLParser
from pathlib import Path

import olefile
from pypdf import PdfReader

from .models import DocumentPage

ARTICLE_RE = re.compile(r"^Điều\s+(\d+)\.\s*(.*)$")
CHAPTER_RE = re.compile(r"^(?:CHƯƠNG|Chương)\s+([IVXLC]+)\s*$")
SECTION_RE = re.compile(r"^(?:MỤC|Mục)\s+(\d+)\.?\s*(.*)$")
CLOSING_RE = re.compile(r"^Bộ luật này (?:đã )?được Quốc hội")
LAW_NUMBER_RE = re.compile(r"(?:Bộ luật|Luật) số:\s*(\d+/(\d{4})/QH\d+)")

def _is_title(line: str) -> bool:
    return line == line.upper() and any(ch.isalpha() for ch in line)


_REPLACE = {
    "\r": "\n", "\x07": "\n", "\x0b": "\n", "\x0c": "\n",
    "\xa0": " ", "​": "", "\xad": "", "﻿": "",
}


def normalize_text(text: str) -> str:
    """NFC, unify line breaks and spaces, drop control characters, keep one line per paragraph."""
    text = unicodedata.normalize("NFC", text)
    for src, dst in _REPLACE.items():
        text = text.replace(src, dst)
    text = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def load_pdf(path: Path, document_id: str, source: str) -> list[DocumentPage]:
    """One DocumentPage per physical page; pages without a text layer are flagged."""
    pages = []
    for number, page in enumerate(PdfReader(path).pages, start=1):
        text = normalize_text(page.extract_text() or "")
        pages.append(DocumentPage(document_id, source, number, text, {"empty": not text}))
    return pages


def read_doc(path: Path) -> str:
    """Main-document text of a Word 97-2003 file, read from the piece table."""
    with olefile.OleFileIO(str(path)) as ole:
        word = ole.openstream("WordDocument").read()
        flags = struct.unpack_from("<H", word, 0x0A)[0]
        table = ole.openstream("1Table" if flags & 0x0200 else "0Table").read()
    ccp_text = struct.unpack_from("<i", word, 0x4C)[0]
    fc_clx, lcb_clx = struct.unpack_from("<II", word, 0x1A2)
    clx = table[fc_clx:fc_clx + lcb_clx]
    pos = 0
    while clx[pos] == 0x01:  # skip Prc blocks
        pos += 3 + struct.unpack_from("<H", clx, pos + 1)[0]
    if clx[pos] != 0x02:
        raise ValueError(f"{path}: unexpected CLX layout")
    lcb = struct.unpack_from("<I", clx, pos + 1)[0]
    plc = clx[pos + 5:pos + 5 + lcb]
    count = (lcb - 4) // 12
    cps = struct.unpack_from(f"<{count + 1}I", plc, 0)
    parts = []
    for k in range(count):
        fc = struct.unpack_from("<I", plc, 4 * (count + 1) + 8 * k + 2)[0]
        length = cps[k + 1] - cps[k]
        if fc & 0x40000000:
            offset = (fc & 0x3FFFFFFF) // 2
            parts.append(word[offset:offset + length].decode("cp1252", errors="replace"))
        else:
            parts.append(word[fc:fc + 2 * length].decode("utf-16-le", errors="replace"))
    text = "".join(parts)[:ccp_text]
    text = re.sub(r"\x13[^\x14\x15]*\x14", "", text)  # field code, keep its result
    text = re.sub(r"\x13[^\x15]*\x15", "", text)
    return text.replace("\x15", "")


class _ParagraphParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.paragraphs: list[str] = []
        self._buffer: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "p":
            self._buffer = []
        elif tag == "br" and self._buffer is not None:
            self._buffer.append("\n")

    def handle_endtag(self, tag):
        if tag == "p" and self._buffer is not None:
            self.paragraphs.append("".join(self._buffer))
            self._buffer = None

    def handle_data(self, data):
        if self._buffer is not None:
            self._buffer.append(re.sub(r"\s+", " ", data))


def read_html(path: Path) -> str:
    parser = _ParagraphParser()
    parser.feed(path.read_text(encoding="utf-8"))
    return "\n".join(parser.paragraphs)


def read_source(path: Path, fmt: str) -> str:
    if fmt == "doc":
        return read_doc(path)
    if fmt == "html":
        return read_html(path)
    raise ValueError(f"unsupported format: {fmt}")


def split_articles(text: str, source: dict) -> tuple[list[DocumentPage], dict]:
    """Split a normalized law into one unit per article, tracking chapter and section.

    `text` must have one non-empty line per paragraph (see `compact_lines`);
    char offsets in the metadata refer to that text. Header/preamble lines before
    Điều 1 and the closing/signature lines are excluded and reported in the log.
    """
    doc_id, url = source["source_id"], source["source_url"]
    lines = text.split("\n")
    log = {"source_id": doc_id, "errors": [], "warnings": []}

    found = LAW_NUMBER_RE.search(text)
    if not found or found.group(1) != source["law_number"] or int(found.group(2)) != source["year"]:
        log["errors"].append(f"law number in text {found.group(1) if found else None!r} "
                             f"does not match manifest {source['law_number']!r}")

    articles, preamble, tail = [], [], []
    chapter, chapter_title, section, section_title = None, "", None, ""
    heading = None  # "chapter" / "section" while its (possibly multi-line) title is read
    offset = 0
    for line in lines:
        start, offset = offset, offset + len(line) + 1
        if tail or CLOSING_RE.match(line):
            tail.append(line)
            continue
        if m := CHAPTER_RE.match(line):
            chapter, chapter_title, section, section_title = m.group(1), "", None, ""
            heading = "chapter"
            continue
        if m := SECTION_RE.match(line):
            section, section_title = int(m.group(1)), m.group(2)
            heading = "section"
            continue
        if heading and _is_title(line) and not ARTICLE_RE.match(line):
            if heading == "chapter":
                chapter_title = f"{chapter_title} {line}".strip()
            else:
                section_title = f"{section_title} {line}".strip()
            continue
        if heading and not (chapter_title if heading == "chapter" else section_title):
            log["warnings"].append(f"{heading} heading without title before: {line[:60]!r}")
        heading = None
        if m := ARTICLE_RE.match(line):
            articles.append({
                "number": int(m.group(1)), "title": m.group(2), "lines": [line],
                "chapter": chapter, "chapter_title": chapter_title,
                "section": section, "section_title": section_title,
                "char_start": start,
            })
            continue
        if articles:
            articles[-1]["lines"].append(line)
        else:
            preamble.append(line)

    numbers = [a["number"] for a in articles]
    if numbers != list(range(1, len(numbers) + 1)):
        log["errors"].append(f"article numbers are not 1..{len(numbers)} in order")
    if not tail:
        log["warnings"].append("closing line not found; last article may contain signature text")

    units = []
    for a in articles:
        body = "\n".join(a["lines"])
        if len(a["lines"]) < 2:
            log["warnings"].append(f"Điều {a['number']} has a heading but no body")
        meta = {
            "unit_id": f"{doc_id}:D{a['number']:03d}",
            "year": source["year"],
            "law_number": source["law_number"],
            "article": a["number"],
            "article_title": a["title"],
            "chapter": a["chapter"] or "",
            "chapter_title": a["chapter_title"] or "",
            "section": a["section"] or 0,
            "section_title": a["section_title"] or "",
            "char_start": a["char_start"],
            "char_end": a["char_start"] + len(body),
            "char_count": len(body),
        }
        units.append(DocumentPage(doc_id, url, a["number"], body, meta))

    log.update({
        "units": len(units),
        "unit_chars": sum(len(u.text) for u in units),
        "excluded_preamble_lines": preamble,
        "excluded_tail_lines": tail,
        "chapters": len({a["chapter"] for a in articles}),
        "sections": len({(a["chapter"], a["section"]) for a in articles if a["section"]}),
    })
    return units, log


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compact_lines(text: str) -> str:
    return "\n".join(line for line in text.split("\n") if line.strip())


def load_corpus(sources: list[dict], root: Path) -> tuple[list[DocumentPage], list[dict], dict[str, str]]:
    """Return units, one log per source, and the normalized text of each source."""
    units, logs, texts = [], [], {}
    for source in sources:
        path = root / source["file"]
        raw = read_source(path, source["format"])
        text = compact_lines(normalize_text(raw))
        doc_units, log = split_articles(text, source)
        log.update({"file": source["file"], "sha256": file_sha256(path),
                    "raw_chars": len(raw), "normalized_chars": len(text)})
        if log["errors"]:
            raise ValueError(f"{source['source_id']}: {log['errors']}")
        units.extend(doc_units)
        logs.append(log)
        texts[source["source_id"]] = text
    return units, logs, texts
