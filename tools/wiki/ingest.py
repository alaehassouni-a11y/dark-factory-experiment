#!/usr/bin/env python3
"""Import any document into the wiki's knowledge format.

    uv run --project tools/wiki python tools/wiki/ingest.py SOURCE... --out WIKI_DIR
    uv run --project tools/wiki python tools/wiki/ingest.py brochure.pdf hours.docx --out /opt/virtualagent/wiki
    uv run --project tools/wiki python tools/wiki/ingest.py ./exports/ --out virtualagent/resources --dry-run

SOURCE is a file or a folder (searched recursively). Word, PDF, PowerPoint, Excel, CSV,
HTML, plain text and Markdown are understood; anything else is reported and skipped.

THE KNOWLEDGE FORMAT, which is what the service indexes best (see the wiki README):

    <!-- imported from: brochure.pdf on 2026-09-06 by tools/wiki/ingest.py -->
    # One topic, as a title

    A few short paragraphs of plain facts under the title.

    ## A section
    More short paragraphs. Tables survive as Markdown tables.

One file per topic. A source with several top-level headings is split into one file per
heading (`--no-split` keeps it whole). The title becomes the file name and is what the agent
cites as its source, so the first heading matters more than anything else in the document.

What this tool does NOT do: it never touches the running service (the folder is watched;
a file written here is knowledge within seconds), it never deletes anything, and it never
overwrites an existing file unless told to (`--force`).
"""

from __future__ import annotations

import argparse
import datetime as dt
import itertools
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

SUPPORTED = {
    ".md",
    ".markdown",
    ".txt",
    ".html",
    ".htm",
    ".docx",
    ".pdf",
    ".pptx",
    ".xlsx",
    ".xls",
    ".csv",
}
PLAIN = {".md", ".markdown", ".txt"}

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\((?:[^)\s]+)(?:\s+\"[^\"]*\")?\)")
_HTML_TAG = re.compile(
    r"</?(?:br|p|div|span|b|i|u|em|strong|a|img|table|tr|td|th|ul|ol|li|h[1-6])\b[^>]*>", re.I
)
_MANY_BLANKS = re.compile(r"\n{3,}")
_PAGE_MARK = re.compile(r"^\s*(?:page\s+\d+(?:\s+of\s+\d+)?|\d+\s*/\s*\d+)\s*$", re.I | re.M)


@dataclass
class Document:
    title: str
    body: str  # Markdown, starting with the "# title" line
    source: str

    @property
    def sections(self) -> int:
        return sum(1 for line in self.body.splitlines() if line.startswith("## "))


# ------------------------------------------------------------------ conversion
def to_markdown(path: Path) -> str:
    """Raw Markdown for any supported file. Plain formats are read as they are; the rest go
    through markitdown, which is the one dependency this tool carries."""
    if path.suffix.lower() in PLAIN:
        return path.read_text(encoding="utf-8", errors="replace")
    from markitdown import MarkItDown  # imported lazily: plain files need nothing

    result = MarkItDown().convert(str(path))
    return result.text_content or ""


def slugify(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug[:80] or "document"


def title_from_filename(path: Path) -> str:
    return re.sub(r"[-_]+", " ", path.stem).strip().capitalize() or "Document"


def clean(markdown: str) -> str:
    """Strip what a speech agent cannot use and what converters leave behind."""
    text = markdown.replace("\r\n", "\n").replace("\xa0", " ")
    text = _IMAGE.sub("", text)
    text = _LINK.sub(r"\1", text)  # keep the words, drop the URL: everything is spoken
    text = _HTML_TAG.sub("", text)
    text = _PAGE_MARK.sub("", text)
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = _MANY_BLANKS.sub("\n\n", text)
    return text.strip() + "\n"


def split_topics(markdown: str, fallback_title: str, split: bool = True) -> list[tuple[str, str]]:
    """(title, body) per topic. A document with several `#` headings is one topic per
    heading; one with none gets `fallback_title`. Deeper headings are kept, shifted so the
    topic title is the only `#`."""
    lines = markdown.split("\n")
    h1_positions = [
        i for i, line in enumerate(lines) if (m := _HEADING.match(line)) and len(m.group(1)) == 1
    ]

    if not h1_positions:
        # No H1: promote the first heading of any level if there is one, else the fallback.
        first = next((i for i, line in enumerate(lines) if _HEADING.match(line)), None)
        if first is None:
            return [(fallback_title, markdown)]
        m = _HEADING.match(lines[first])
        assert m is not None
        title = m.group(2).strip()
        lines[first] = f"# {title}"
        depth = len(m.group(1))
        body = "\n".join(_shift_headings(lines, depth - 1))
        return [(title, body)]

    if not split or len(h1_positions) == 1:
        m = _HEADING.match(lines[h1_positions[0]])
        assert m is not None
        title = m.group(2).strip()
        if len(h1_positions) > 1:
            # keep one file: later H1s become H2s
            for i in h1_positions[1:]:
                lines[i] = "#" + lines[i]
        return [(title, "\n".join(lines))]

    topics: list[tuple[str, str]] = []
    preamble = "\n".join(lines[: h1_positions[0]]).strip()
    bounds = [*h1_positions, len(lines)]
    for start, end in itertools.pairwise(bounds):
        m = _HEADING.match(lines[start])
        assert m is not None
        title = m.group(2).strip()
        chunk = lines[start:end]
        if preamble and start == h1_positions[0]:
            chunk = [chunk[0], "", preamble, *chunk[1:]]
        topics.append((title, "\n".join(chunk)))
    return topics


def _shift_headings(lines: list[str], by: int) -> list[str]:
    if by <= 0:
        return lines
    out = []
    for line in lines:
        m = _HEADING.match(line)
        if m and len(m.group(1)) > 1:
            level = max(2, len(m.group(1)) - by)
            out.append(f"{'#' * level} {m.group(2).strip()}")
        else:
            out.append(line)
    return out


def import_file(path: Path, split: bool = True, today: dt.date | None = None) -> list[Document]:
    """Every topic in one source file, in the knowledge format, ready to write."""
    raw = to_markdown(path)
    text = clean(raw)
    if not text.strip():
        return []
    stamp = (today or dt.date.today()).isoformat()
    docs = []
    for title, body in split_topics(text, title_from_filename(path), split=split):
        body = clean(body)
        if not body.lstrip().startswith("# "):
            body = f"# {title}\n\n{body}"
        header = f"<!-- imported from: {path.name} on {stamp} by tools/wiki/ingest.py -->\n"
        docs.append(Document(title=title, body=header + body, source=path.name))
    return docs


# ------------------------------------------------------------------ CLI
def _sources(args: list[str]) -> list[Path]:
    out: list[Path] = []
    for a in args:
        p = Path(a)
        if p.is_dir():
            out.extend(sorted(q for q in p.rglob("*") if q.is_file()))
        else:
            out.append(p)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("sources", nargs="+", help="files or folders to import")
    ap.add_argument("--out", required=True, type=Path, help="the wiki folder to write into")
    ap.add_argument(
        "--no-split", action="store_true", help="keep a multi-heading source as one file"
    )
    ap.add_argument(
        "--force", action="store_true", help="overwrite files that already exist in the wiki"
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="show what would be written, write nothing"
    )
    ns = ap.parse_args(argv)

    if not ns.dry_run:
        ns.out.mkdir(parents=True, exist_ok=True)

    written = skipped = failed = 0
    for src in _sources(ns.sources):
        if src.suffix.lower() not in SUPPORTED:
            print(f"  skip    {src}  (unsupported: {src.suffix or 'no extension'})")
            skipped += 1
            continue
        if src.name.lower() == "readme.md":
            print(f"  skip    {src}  (a README is not knowledge)")
            skipped += 1
            continue
        try:
            docs = import_file(src, split=not ns.no_split)
        except Exception as e:  # one bad file must not stop the batch
            print(f"  FAIL    {src}  ({type(e).__name__}: {e})")
            failed += 1
            continue
        if not docs:
            print(f"  skip    {src}  (no text found)")
            skipped += 1
            continue
        for doc in docs:
            target = ns.out / f"{slugify(doc.title)}.md"
            words = len(doc.body.split())
            note = f'"{doc.title}"  {words} words, {doc.sections} sections'
            if words > 1500:
                note += "  <- long for one topic; consider splitting"
            if target.exists() and not ns.force and not ns.dry_run:
                print(f"  exists  {target}  ({note}; use --force to overwrite)")
                skipped += 1
                continue
            if ns.dry_run:
                print(f"  would   {target}  ({note})")
            else:
                target.write_text(doc.body, encoding="utf-8", newline="\n")
                print(f"  wrote   {target}  ({note})")
            written += 1

    print(
        f"IMPORT_DONE written={written} skipped={skipped} failed={failed}"
        + (" (dry run)" if ns.dry_run else "")
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
