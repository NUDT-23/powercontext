# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Page-level PDF Sources with exact evidence pages and offline question search."""

from __future__ import annotations

import hashlib
import re
from io import BytesIO
from urllib.parse import quote

from pydantic import BaseModel

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.definitions import AdapterSourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

try:  # pypdf is provided by the shared self-test environment.
    from pypdf import PasswordType, PdfReader
except ImportError:  # pragma: no cover - keeps import-time behavior explicit
    PdfReader = None
    PasswordType = None

PDF_PAGE_SOURCE_NAME = "pdf-page"
_WORD_PATTERN = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    "a an and are as at be been by did do does for from had has have how in is it its of on or that the this to was "
    "were what when where which who will with you your company corporation inc ltd "
    "between much many any into within across during under over than then also based state stated "
    "not if yes no true false primarily".split()
)

_STRUCTURE_WORDS = frozenset(
    "with which table tables content contents note notes following page pages see certain information report "
    "reports year years december including consolidated statements statement million millions total "
    "according respective respectively other such based have this business financial".split()
)


class PDFDocumentInput(BaseModel):
    """One complete original PDF document captured by identity."""

    document_id: str
    content: bytes


class PDFPageInput(BaseModel):
    """One physical PDF page with its document digest and extracted text."""

    document_id: str
    document_sha256: str
    page_number: int
    text: str


class PDFPageSource(Source):
    """A CAPTURED physical PDF page keeping its extractable text."""

    source_id: str
    document_id: str
    document_sha256: str
    page_number: int
    text: str


def pdf_page_source_id(document_id: str, document_sha256: str, page_number: int) -> str:
    """Return the stable identity for one page of one exact document revision."""

    if not isinstance(document_id, str) or not document_id or not document_id.strip():
        raise ValueError("document_id must be a non-blank string")  # noqa: TRY003
    identity = f"pdf:{quote(document_id, safe='')}:{document_sha256}:{page_number}"
    if len(identity) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"page identity must not exceed {MAX_SOURCE_ID_LENGTH} characters")  # noqa: TRY003
    return identity


def parse_pdf_document(value: PDFDocumentInput, /) -> tuple[PDFPageInput, ...]:
    """Parse every physical page of one complete PDF, or fail atomically."""

    if PdfReader is None:
        raise ValueError("pypdf is required to parse PDF documents")  # noqa: TRY003
    document_id = value.document_id
    if not isinstance(document_id, str) or not document_id or not document_id.strip():
        raise ValueError("document_id must be a non-blank string")  # noqa: TRY003
    digest = hashlib.sha256(value.content).hexdigest()
    try:
        reader = PdfReader(BytesIO(value.content))
        if getattr(reader, "is_encrypted", False) and reader.decrypt("") == PasswordType.NOT_DECRYPTED:
            raise ValueError("encrypted PDF requires a password")  # noqa: TRY003
        pages = tuple(reader.pages)
    except ValueError:
        raise
    except Exception as error:
        raise ValueError(f"PDF document cannot be parsed: {error}") from error
    parsed: list[PDFPageInput] = []
    try:
        for index, page in enumerate(pages, start=1):
            text = page.extract_text() or ""
            parsed.append(
                PDFPageInput(
                    document_id=document_id,
                    document_sha256=digest,
                    page_number=index,
                    text=text,
                )
            )
    except Exception as error:
        raise ValueError(f"PDF page {len(parsed) + 1} cannot be extracted: {error}") from error
    return tuple(parsed)


async def search_pdf_pages(memory: object, question: str, limit: int = 10) -> tuple[object, ...]:
    """Search stored page evidence for one natural-language question.

    Pages are scored by band votes collected from keyword probes of the
    question. Probe families cover whole-question views, adjacent
    content-word phrases, single content words and their morphological
    variants, so a page dense in one rare question term (the
    legal-proceedings page for a question about lawsuits, the
    geographic-operations note for a question about geographies, the
    balance-sheet statement for a question about liabilities) earns a top
    band in at least one probe instead of being drowned by pages that
    merely mention many common words. Every probe goes through the public
    Memory search API; phrases whose every word is common in this corpus
    (a company name, for example) carry no ranking signal and are skipped.
    """

    from powercontext.builtin.artifacts.memory.models import MemoryCitation
    from powercontext.builtin.runtime import SearchMemoryRequest

    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-blank string")  # noqa: TRY003
    if type(limit) is not int or limit < 1:
        raise ValueError("limit must be a positive integer")  # noqa: TRY003

    pool = 150
    kind_weight = {"view": 0.7, "ngram": 1.3, "term": 1.0, "variant": 0.6, "expansion": 0.5}

    async def search(query: str):
        return (await memory.search(SearchMemoryRequest(query=query, mode="fts", limit=pool))).hits

    words = _content_words(question)
    support = {word: await search(word) for word in words}

    probes: list[tuple[str, str, list]] = []
    for view in _query_views(question):
        probes.append(("view", view, await search(view)))
    for ngram in _adjacent_ngrams(question):
        gram_words = ngram.split()
        if all(support.get(word) and len(support[word]) >= 50 for word in gram_words):
            continue
        hits = await search(ngram)
        rarest = min((len(support.get(word) or ()) for word in gram_words), default=0)
        if rarest > 0 and len(hits) > 8 * rarest:
            continue
        probes.append(("ngram", ngram, hits))
    for word in words:
        probes.append(("term", word, support[word]))
    for variant in _word_variants(question):
        probes.append(("variant", variant, await search(variant)))

    scores: dict[tuple[str, str, str], float] = {}
    citations: dict[tuple[str, str, str], object] = {}
    order: dict[tuple[str, str, str], int] = {}
    navigational: dict[tuple[str, str, str], float] = {}
    seen = 0

    def accumulate(kind: str, hits: list) -> None:
        nonlocal seen
        if not hits:
            return
        df = len(hits)
        rarity = 2.0 if df < 20 else 1.4 if df < 60 else 1.0 if df < 120 else 0.7
        weight = rarity * kind_weight.get(kind, 1.0)
        if kind in {"variant", "expansion"}:
            if df >= 100:
                return
            if df >= 60:
                weight *= 0.6
        for rank, hit in enumerate(hits, start=1):
            if rank == 1:
                band = 3.5
            elif rank <= 3:
                band = 3.0
            elif rank <= 10:
                band = 2.0
            elif rank <= 25:
                band = 1.0
            elif rank <= 50:
                band = 0.4
            else:
                band = 0.1
            key = (str(hit.memory_ref), str(hit.entry_id), str(hit.entry_version_id))
            if key not in order:
                order[key] = seen
                seen += 1
            if key not in navigational:
                navigational[key] = _navigational_factor(hit.text or "")
            scores[key] = scores.get(key, 0.0) + weight * band * navigational[key]
            citations[key] = MemoryCitation(
                memory_ref=hit.memory_ref, entry_id=hit.entry_id, entry_version_id=hit.entry_version_id
            )

    for kind, _query, hits in probes:
        accumulate(kind, hits)

    seeds = sorted(scores, key=lambda key: (-scores[key], order[key]))[:10]
    for term in await _expansion_terms(memory, question, [citations[key] for key in seeds]):
        accumulate("expansion", await search(term))

    ranked = sorted(scores, key=lambda key: (-scores[key], order[key]))
    return tuple(citations[key] for key in ranked[:limit])


async def _expansion_terms(memory, question: str, seed_citations, count: int = 8) -> tuple[str, ...]:
    """Salient corpus terms shared by seed pages but absent from the question.

    The first fusion round already surfaces pages that mention the question
    words; pages that answer the question through other vocabulary (a
    balance-sheet statement for a question about liabilities, for example)
    share distinctive terms with those seeds. Reading seed texts through
    the public Memory read API and probing their common terms is
    deterministic offline query expansion.
    """

    from collections import Counter

    from powercontext.builtin.runtime import GetMemoryEntryRequest

    question_terms = set(_content_words(question))
    for variant in _word_variants(question):
        question_terms.add(variant)
    question_terms.update(_STRUCTURE_WORDS)
    presence: Counter = Counter()
    totals: Counter = Counter()
    seeds = 0
    for citation in seed_citations:
        result = await memory.get(GetMemoryEntryRequest(citation=citation))
        text = result.entry.text.lower()
        if not text:
            continue
        seeds += 1
        tokens = _WORD_PATTERN.findall(text)
        for token in set(tokens):
            if len(token) >= 4 and token not in _STOPWORDS and token not in _STRUCTURE_WORDS and token not in question_terms and not token.isdigit():
                presence[token] += 1
        for token in tokens:
            if len(token) >= 4 and token not in _STOPWORDS and token not in _STRUCTURE_WORDS and token not in question_terms and not token.isdigit():
                totals[token] += 1
    if seeds < 3:
        return ()
    ranked_terms = sorted(presence, key=lambda term: (-presence[term] * 1000 - min(totals[term], 999), term))
    return tuple(ranked_terms[:count])


def _query_views(question: str) -> tuple[str, ...]:
    """Deterministic keyword views of one question for full-text search."""

    lowered = question.lower()
    words = _WORD_PATTERN.findall(lowered)
    content = [word for word in words if word not in _STOPWORDS and len(word) > 1]
    distinctive = sorted(set(content), key=lambda word: (-len(word), word))
    views = [question.strip()]
    if content:
        views.append(" ".join(content))
    if len(distinctive) >= 3:
        views.append(" ".join(distinctive[:3]))
    if len(distinctive) >= 6:
        views.append(" ".join(distinctive[:6]))
    seen: set[str] = set()
    unique = []
    for view in views:
        if view and view not in seen:
            seen.add(view)
            unique.append(view)
    return tuple(unique)


def _content_words(question: str) -> tuple[str, ...]:
    """Distinct content words of one question in first-appearance order."""

    lowered = question.lower()
    words = _WORD_PATTERN.findall(lowered)
    content: list[str] = []
    known: set[str] = set()
    for word in words:
        if word in _STOPWORDS or len(word) < 2 or word in known:
            continue
        known.add(word)
        content.append(word)
    return tuple(content)


def _adjacent_ngrams(question: str, cap: int = 14) -> tuple[str, ...]:
    """Adjacent two- and three-word content phrases over the compressed sequence.

    Financial phrasing binds key words with function words ("products and
    services", "consolidated statements of operations"), so phrases are built
    over the question's content words in order, ignoring the stopwords
    between them. Three-word phrases matter most: full-text admission for a
    three-or-more-term query requires a page to match several distinct terms
    at once, which keeps a phrase probe on pages that genuinely discuss the
    phrase instead of every page that mentions one common word.
    """

    lowered = question.lower()
    words = _WORD_PATTERN.findall(lowered)
    sequence: list[str] = []
    for word in words:
        if word in _STOPWORDS or len(word) < 2:
            continue
        if sequence and sequence[-1] == word:
            continue
        sequence.append(word)
    sequences: list[str] = []
    for size in (3, 2):
        if len(sequence) >= size:
            for offset in range(len(sequence) - size + 1):
                gram = " ".join(sequence[offset : offset + size])
                if gram not in sequences:
                    sequences.append(gram)
    return tuple(sequences[:cap])


_REFERENCE_PATTERN = re.compile(r"\bexhibit\w*\b", re.IGNORECASE)
_HEAD_EXHIBIT_PATTERN = re.compile(r"exhibits?\s+\d")


def _navigational_factor(text: str) -> float:
    """Downweight navigational pages: exhibit checklists and exhibit documents.

    Exhibit checklists name every product, customer and agreement the company
    has ever used, and exhibit documents (subsidiary lists, consents,
    certifications) are dense boilerplate, so keyword probes rank them above
    pages that actually discuss a topic while they never hold report
    evidence. A dense run of exhibit references, or an exhibit banner at the
    head of the page, marks them deterministically; content pages and the
    cover page (whose checkbox text says "filed" and "pursuant" but never
    "exhibit") stay far from both marks in every observed annual report.
    """

    if len(_REFERENCE_PATTERN.findall(text)) >= 8:
        return 0.15
    if _HEAD_EXHIBIT_PATTERN.search(text.lower()[:90]):
        return 0.15
    return 1.0


_VARIANT_STEMS = ("ies", "es", "s", "ing", "ed", "ion", "y")
_VARIANT_ENDINGS = ("", "y", "ic", "ical", "s", "es", "ies", "ing", "ed", "ion", "ions")
_IRREGULAR_FAMILIES = {
    "sells": ("sell", "sold", "selling"),
    "sell": ("sold", "selling", "sells"),
    "sold": ("sell", "sells", "selling"),
    "buy": ("bought", "buying", "buys"),
    "bought": ("buy", "buys", "buying"),
    "hold": ("held", "holding", "holds"),
    "held": ("hold", "holds", "holding"),
    "holds": ("hold", "held", "holding"),
    "pay": ("paid", "paying", "pays"),
    "paid": ("pay", "pays", "paying"),
    "make": ("made", "making", "makes"),
    "made": ("make", "makes", "making"),
}


def _word_variants(question: str, cap: int = 40) -> tuple[str, ...]:
    """Deterministic morphological variants of the question's content words.

    Full-text matching is exact-token, so inflected question words cannot
    hit pages that use another member of the same word family (geographies
    versus geographic, operates versus operating, liability versus
    liabilities). Variants are probed like any other keyword; variants
    absent from the corpus simply return no hits and cost nothing in the
    fusion.
    """

    out: list[str] = []
    known: set[str] = set()
    for word in _content_words(question):
        if len(word) < 5 or word.isdigit():
            continue
        stems = {word}
        for suffix in _VARIANT_STEMS:
            if word.endswith(suffix) and len(word) - len(suffix) >= 4:
                stem = word[: -len(suffix)]
                stems.add(stem)
                if suffix == "y":
                    stems.add(stem + "ie")
        for family in _IRREGULAR_FAMILIES.get(word, ()):
            if len(family) >= 4:
                stems.add(family)
        for stem in sorted(stems):
            for ending in _VARIANT_ENDINGS:
                variant = stem + ending
                if variant != word and len(variant) >= 4 and variant not in known:
                    known.add(variant)
                    out.append(variant)
                    if len(out) >= cap:
                        return tuple(out)
    return tuple(out)


class PDFPageSourceAdapter:
    """Resolve and read page-level PDF Sources."""

    input_class = PDFPageInput
    name = PDF_PAGE_SOURCE_NAME
    source_class = PDFPageSource

    async def resolve(self, value: PDFPageInput, /) -> PDFPageSource:
        identity = pdf_page_source_id(value.document_id, value.document_sha256, value.page_number)
        return PDFPageSource(
            name=identity,
            materialization=SourceMaterialization.CAPTURED,
            source_id=identity,
            document_id=value.document_id,
            document_sha256=value.document_sha256,
            page_number=value.page_number,
            text=value.text,
        )

    async def read(self, source: PDFPageSource, /) -> PDFPageInput:
        return PDFPageInput(
            document_id=source.document_id,
            document_sha256=source.document_sha256,
            page_number=source.page_number,
            text=source.text,
        )


class PDFPageTextEvidenceProjection:
    """Project one PDF page as canonical text evidence."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PDFPageSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PDFPageSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=PDF_PAGE_SOURCE_NAME,
            source_id=source.source_id,
            content=f"{source.document_id}\n{source.text}",
            metadata={
                "document_id": source.document_id,
                "document_sha256": source.document_sha256,
                "page_number": source.page_number,
            },
        )


PDF_PAGE_SOURCE_DEFINITION = AdapterSourceDefinition(
    PDFPageSourceAdapter(),
    version="1",
    projections=(PDFPageTextEvidenceProjection(),),
)


__all__ = [
    "PDF_PAGE_SOURCE_DEFINITION",
    "PDFDocumentInput",
    "PDFPageInput",
    "PDFPageSource",
    "parse_pdf_document",
    "pdf_page_source_id",
    "search_pdf_pages",
]
