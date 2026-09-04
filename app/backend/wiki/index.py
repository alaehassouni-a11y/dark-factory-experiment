"""The wiki: every Markdown and plain-text file under `virtualagent/resources`, chunked,
indexed twice (BM25 over words, cosine over embeddings), fused with reciprocal rank fusion.

Two indexes because the client asks in one of four languages and the documents are in
whichever language they were written in. Words match within a language; embeddings match
across them. The confidence decision that gates the web fallback (MISSION hard invariant
2) reads both: the top hit must either cover most of the question's content words or sit
above the similarity floor.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from backend.config import WIKI_MIN_SIMILARITY, WIKI_MIN_TERM_COVERAGE, WIKI_TOP_K
from backend.languages import _FUNCTION_WORDS, tokenize

logger = logging.getLogger(__name__)

WIKI_EXTENSIONS = (".md", ".txt")
CHUNK_TARGET_CHARS = 700
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_STOPWORDS: frozenset[str] = frozenset().union(*_FUNCTION_WORDS.values())


class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class Chunk:
    title: str
    location: str
    index: int
    text: str


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float
    lexical_coverage: float
    cosine: float


def _read_documents(root: Path) -> list[tuple[str, str, str]]:
    """(title, location, body) for every wiki file, README excluded: it describes the
    folder, it is not knowledge."""
    if not root.is_dir():
        return []
    docs = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in WIKI_EXTENSIONS:
            continue
        if path.name.lower() == "readme.md" or path.name.startswith("."):
            continue
        body = path.read_text(encoding="utf-8", errors="replace")
        title = path.stem.replace("-", " ").replace("_", " ").strip()
        for line in body.splitlines():
            m = _HEADING.match(line.strip())
            if m:
                title = m.group(2).strip() or title
                break
        docs.append((title, path.relative_to(root).as_posix(), body))
    return docs


def chunk_document(title: str, location: str, body: str) -> list[Chunk]:
    """Split on headings, then pack paragraphs up to CHUNK_TARGET_CHARS. Each chunk carries
    the section heading so a fragment still says what it is about."""
    sections: list[tuple[str, list[str]]] = [("", [])]
    for raw in body.splitlines():
        line = raw.rstrip()
        m = _HEADING.match(line.strip())
        if m:
            sections.append((m.group(2).strip(), []))
        else:
            sections[-1][1].append(line)

    chunks: list[Chunk] = []
    for heading, lines in sections:
        paragraphs = [p.strip() for p in "\n".join(lines).split("\n\n") if p.strip()]
        buf = ""
        for p in paragraphs:
            candidate = f"{buf}\n\n{p}".strip() if buf else p
            if buf and len(candidate) > CHUNK_TARGET_CHARS:
                chunks.append(_make(title, location, len(chunks), heading, buf))
                buf = p
            else:
                buf = candidate
        if buf:
            chunks.append(_make(title, location, len(chunks), heading, buf))
    return chunks


def _make(title: str, location: str, index: int, heading: str, text: str) -> Chunk:
    prefixed = f"{heading}\n{text}" if heading and not text.startswith(heading) else text
    return Chunk(title=title, location=location, index=index, text=prefixed)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


class WikiIndex:
    def __init__(self, chunks: list[Chunk], vectors: list[list[float]], documents: int) -> None:
        self.chunks = chunks
        self.vectors = vectors
        self.document_count = documents
        self._embedder: Embedder | None = None
        self._tokens = [tokenize(c.text) for c in chunks]
        self._df: Counter[str] = Counter()
        for toks in self._tokens:
            self._df.update(set(toks))
        self._avgdl = (sum(len(t) for t in self._tokens) / len(self._tokens)) if chunks else 0.0

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)

    @classmethod
    async def build(cls, root: Path, embedder: Embedder) -> WikiIndex:
        docs = _read_documents(root)
        chunks: list[Chunk] = []
        for title, location, body in docs:
            chunks.extend(chunk_document(title, location, body))
        vectors: list[list[float]] = []
        for start in range(0, len(chunks), 64):
            batch = chunks[start : start + 64]
            vectors.extend(await embedder.embed([c.text for c in batch]))
        if not docs:
            logger.warning("wiki folder %s has no documents; every question will fall back", root)
        index = cls(chunks, vectors, len(docs))
        index._embedder = embedder
        return index

    # ------------------------------------------------------------------ scoring
    def _bm25(self, query_tokens: list[str], k1: float = 1.5, b: float = 0.75) -> list[float]:
        n = len(self._tokens)
        scores = [0.0] * n
        for i, toks in enumerate(self._tokens):
            tf = Counter(toks)
            dl = len(toks)
            for q in query_tokens:
                if q not in tf:
                    continue
                idf = math.log(1 + (n - self._df[q] + 0.5) / (self._df[q] + 0.5))
                denom = tf[q] + k1 * (1 - b + b * dl / (self._avgdl or 1.0))
                scores[i] += idf * tf[q] * (k1 + 1) / denom
        return scores

    async def search(self, query: str, top_k: int | None = None) -> list[Hit]:
        top_k = top_k or WIKI_TOP_K
        if not self.chunks:
            return []
        q_tokens = tokenize(query)
        if not q_tokens:
            return []
        content = [t for t in q_tokens if t not in _STOPWORDS] or q_tokens
        lexical = self._bm25(q_tokens)
        cosines = [0.0] * len(self.chunks)
        if self._embedder is not None and self.vectors:
            qv = (await self._embedder.embed([query]))[0]
            cosines = [_cosine(qv, v) for v in self.vectors]

        def ranks(scores: list[float]) -> dict[int, int]:
            order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
            return {i: r for r, i in enumerate(order) if scores[i] > 0}

        fused: dict[int, float] = {}
        for rank_map in (ranks(lexical), ranks(cosines)):
            for i, r in rank_map.items():
                fused[i] = fused.get(i, 0.0) + 1.0 / (60 + r)
        best = sorted(fused, key=lambda i: fused[i], reverse=True)[:top_k]
        hits = []
        for i in best:
            present = set(self._tokens[i])
            coverage = sum(1 for t in content if t in present) / len(content)
            hits.append(
                Hit(
                    chunk=self.chunks[i],
                    score=fused[i],
                    lexical_coverage=round(coverage, 3),
                    cosine=round(cosines[i], 3),
                )
            )
        return hits

    def is_confident(self, hits: list[Hit]) -> bool:
        """The wiki has the answer when its best hit covers the question's content words or
        is semantically close to it. Either tolerance alone is a judgement value."""
        if not hits:
            return False
        top = hits[0]
        return top.lexical_coverage >= WIKI_MIN_TERM_COVERAGE or top.cosine >= WIKI_MIN_SIMILARITY
