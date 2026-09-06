"""The wiki: every Markdown and plain-text file under the wiki folder, chunked, indexed
twice (BM25 over words, cosine over embeddings), fused with reciprocal rank fusion.

The folder is watched (`backend.main`): `folder_signature` is what changes when a file is
added, edited or removed, and `WikiIndex.build(..., previous=)` reuses the embeddings of
every chunk whose text did not change, so a one-file edit costs one file of embeddings.

Two indexes because the client asks in one of four languages and the documents are in
whichever language they were written in. Words match within a language; embeddings match
across them. The confidence decision that gates the web fallback (MISSION hard invariant
2) reads both: the top hit must either cover most of the question's content words or sit
above the similarity floor.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from backend.config import (
    WIKI_MAX_CHUNKS_PER_DOCUMENT,
    WIKI_MIN_SIMILARITY,
    WIKI_MIN_TERM_COVERAGE,
    WIKI_MIN_TERM_MATCHES,
    WIKI_TOP_K,
)
from backend.languages import _ARABIC, _FUNCTION_WORDS, tokenize

logger = logging.getLogger(__name__)

WIKI_EXTENSIONS = (".md", ".txt")
CHUNK_TARGET_CHARS = 700
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")

# Words a question is made of and a document is not. Function words come from the
# language module (it needs them to tell the languages apart); these are the question
# words on top, which detection deliberately leaves alone because they mark a question,
# not a topic: "combien de temps dure la garantie" is about the guarantee.
_QUESTION_WORDS: frozenset[str] = frozenset(
    """combien quel quelle quels quelles lequel laquelle lesquels lesquelles pourquoi comment
    quand encore aussi svp
    how what which when where why much many long often whether
    wie was welche welcher welches wann wo warum wieviel viel viele lange oft
    كم ما ماذا كيف متى اين أين هل لماذا""".split()
)
_STOPWORDS: frozenset[str] = frozenset().union(*_FUNCTION_WORDS.values()) | _QUESTION_WORDS

# Conservative stemming, one rule set for the three Latin-script languages and one for
# Arabic, so that "garantie" and "garantis", "produit" and "produits", "hour" and
# "hours", "Öffnungszeit" and "Öffnungszeiten", "ساعة" and "ساعات" meet in the index.
# Cut a long word to its first six letters, drop a plural s/x from a shorter one; strip the
# article and the common suffixes from Arabic. A false merge costs a little ranking noise;
# a missed one costs the answer, so the rules lean towards merging.
_ARABIC_PREFIXES = ("وال", "بال", "لل", "ال", "و", "ب", "ل", "ف")
_ARABIC_SUFFIXES = ("ات", "ون", "ين", "ية", "ها", "هم", "ة", "ه")
_MIN_CONTENT_LETTERS = 3
# A passage joins the lexical ranking only above this BM25 score. A word that appears in
# every passage ("bonsai", in a bonsai wiki) scores about 0.01 everywhere, and ranking 54
# near-zero scores puts the passages in an order that means nothing, which the fusion then
# weighed as much as the embeddings. A term in half the passages scores about 0.7; a rare
# one 3 or more. Below the bar the passage is ranked by meaning alone.
_MIN_LEXICAL_SCORE = 0.5


def stem(token: str) -> str:
    if _ARABIC.search(token):
        for p in _ARABIC_PREFIXES:
            if token.startswith(p) and len(token) - len(p) >= 3:
                token = token[len(p) :]
                break
        for s in _ARABIC_SUFFIXES:
            if token.endswith(s) and len(token) - len(s) >= 3:
                token = token[: -len(s)]
                break
        return token
    if len(token) > 6:
        return token[:6]
    if len(token) > 3 and token.endswith(("s", "x")):
        return token[:-1]
    return token


def content_stems(tokens: list[str]) -> list[str]:
    """The stems of the words that carry a question's topic: no function words, no question
    words, nothing shorter than three letters (\"y a-t-il\" is three tokens about nothing)."""
    return [
        stem(t)
        for t in tokens
        if t not in _STOPWORDS and (len(t) >= _MIN_CONTENT_LETTERS or _ARABIC.search(t))
    ]


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
    lexical_coverage: float  # matched content stems / content stems in the question
    cosine: float
    matched: int = 0  # how many of the question's content stems the passage contains
    content: int = 0  # how many content stems the question has


def _wiki_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return [
        p
        for p in sorted(root.rglob("*"))
        if p.is_file()
        and p.suffix.lower() in WIKI_EXTENSIONS
        and p.name.lower() != "readme.md"
        and not p.name.startswith(".")
    ]


def folder_signature(root: Path) -> str:
    """A short digest of which wiki files exist and when they last changed. Equal
    signatures mean nothing to re-index; a file added, edited (mtime or size) or removed
    changes it. Cheap enough to compute every few seconds over a folder of documents."""
    h = hashlib.sha1()
    for p in _wiki_files(root):
        try:
            st = p.stat()
        except OSError:
            continue
        h.update(f"{p.relative_to(root).as_posix()}|{st.st_size}|{st.st_mtime_ns}\n".encode())
    return h.hexdigest()


def _read_documents(root: Path) -> list[tuple[str, str, str]]:
    """(title, location, body) for every wiki file, README excluded: it describes the
    folder, it is not knowledge."""
    docs = []
    for path in _wiki_files(root):
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
    def __init__(
        self,
        chunks: list[Chunk],
        vectors: list[list[float]],
        documents: int,
        signature: str = "",
    ) -> None:
        self.chunks = chunks
        self.vectors = vectors
        self.document_count = documents
        self.signature = signature
        self.built_at = datetime.now(UTC)
        self._embedder: Embedder | None = None
        self._tokens = [[stem(t) for t in tokenize(c.text)] for c in chunks]
        self._df: Counter[str] = Counter()
        for toks in self._tokens:
            self._df.update(set(toks))
        self._avgdl = (sum(len(t) for t in self._tokens) / len(self._tokens)) if chunks else 0.0

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)

    @classmethod
    async def build(
        cls, root: Path, embedder: Embedder, previous: WikiIndex | None = None
    ) -> WikiIndex:
        """Read, chunk and embed the folder. With `previous`, chunks whose text is unchanged
        keep their embedding instead of being sent to the provider again."""
        signature = folder_signature(root)
        docs = _read_documents(root)
        chunks: list[Chunk] = []
        for title, location, body in docs:
            chunks.extend(chunk_document(title, location, body))
        known: dict[str, list[float]] = {}
        if previous is not None:
            known = {c.text: v for c, v in zip(previous.chunks, previous.vectors, strict=False)}
        vectors: list[list[float] | None] = [known.get(c.text) for c in chunks]
        todo = [i for i, v in enumerate(vectors) if v is None]
        for start in range(0, len(todo), 64):
            batch = todo[start : start + 64]
            fresh = await embedder.embed([chunks[i].text for i in batch])
            for i, v in zip(batch, fresh, strict=False):
                vectors[i] = v
        if not docs:
            logger.warning("wiki folder %s has no documents; every question will fall back", root)
        index = cls(chunks, [v or [] for v in vectors], len(docs), signature)
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
        q_stems = [stem(t) for t in q_tokens]
        content = content_stems(q_tokens) or q_stems
        lexical = self._bm25(q_stems)
        cosines = [0.0] * len(self.chunks)
        if self._embedder is not None and self.vectors:
            qv = (await self._embedder.embed([query]))[0]
            cosines = [_cosine(qv, v) for v in self.vectors]

        def ranks(scores: list[float], floor: float = 0.0) -> dict[int, int]:
            order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
            return {i: r for r, i in enumerate(order) if scores[i] > floor}

        fused: dict[int, float] = {}
        for rank_map in (ranks(lexical, _MIN_LEXICAL_SCORE), ranks(cosines)):
            for i, r in rank_map.items():
                fused[i] = fused.get(i, 0.0) + 1.0 / (60 + r)
        # Best first, but no document may fill the excerpts on its own: a client's question
        # in French ranks every passage of a French document above the English passage
        # that actually answers it, and the model can only decline what it never saw.
        best: list[int] = []
        per_document: Counter[str] = Counter()
        for i in sorted(fused, key=lambda i: fused[i], reverse=True):
            location = self.chunks[i].location
            if per_document[location] >= WIKI_MAX_CHUNKS_PER_DOCUMENT:
                continue
            per_document[location] += 1
            best.append(i)
            if len(best) >= top_k:
                break
        hits = []
        for i in best:
            present = set(self._tokens[i])
            matched = sum(1 for t in content if t in present)
            hits.append(
                Hit(
                    chunk=self.chunks[i],
                    score=fused[i],
                    lexical_coverage=round(matched / len(content), 3),
                    cosine=round(cosines[i], 3),
                    matched=matched,
                    content=len(content),
                )
            )
        return hits

    def is_confident(self, hits: list[Hit]) -> bool:
        """The wiki has the answer when its best hit covers enough of the question's content
        stems or is semantically close to it. Either tolerance alone is a judgement value.
        The bar is not the last line of defence: excerpts that pass it but do not answer
        are declined by the model ([[NO_ANSWER]]) and the pipeline moves on to the web."""
        if not hits:
            return False
        top = hits[0]
        by_words = top.lexical_coverage >= WIKI_MIN_TERM_COVERAGE and top.matched >= min(
            WIKI_MIN_TERM_MATCHES, top.content
        )
        return by_words or top.cosine >= WIKI_MIN_SIMILARITY
