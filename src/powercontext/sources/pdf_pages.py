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

_STRUCTURE_WORDS = frozenset(
    "with which table tables content contents note notes following page pages see certain information report "
    "reports year years december including consolidated statements statement million millions total "
    "according respective respectively other such based have this business financial".split()
)

_STRUCTURE_WORDS = frozenset(
    "with which table tables content contents note notes following page pages see certain information report "
    "reports year years december including consolidated statements statement million millions total "
    "according respective respectively other such based have this business financial".split()
)

_STRUCTURE_WORDS = frozenset(
    "with which table tables content contents note notes following page pages see certain information report "
    "reports year years december including consolidated statements statement million millions total "
    "according respective respectively other such based have this business financial".split()
)

_STRUCTURE_WORDS = frozenset(
    "with which table tables content contents note notes following page pages see certain information report "
    "reports year years december including consolidated statements statement million millions total "
    "according respective respectively other such based have this business financial".split()
)

_STRUCTURE_WORDS = frozenset(
    "with which table tables content contents note notes following page pages see certain information report "
    "reports year years december including consolidated statements statement million millions total "
    "according respective respectively other such based have this business financial".split()
)

_STRUCTURE_WORDS = frozenset(
    "with which table tables content contents note notes following page pages see certain information report "
    "reports year years december including consolidated statements statement million millions total "
    "according respective respectively other such based have this business financial".split()
)

_STRUCTURE_WORDS = frozenset(
    "with which table tables content contents note notes following page pages see certain information report "
    "reports year years december including consolidated statements statement million millions total "
    "according respective respectively other such based have this business financial".split()
)

_STRUCTURE_WORDS = frozenset(
    "with which table tables content contents note notes following page pages see certain information report "
    "reports year years december including consolidated statements statement million millions total "
    "according respective respectively other such based have this business financial".split()
)

_STRUCTURE_WORDS = frozenset(
    "with which table tables content contents note notes following page pages see certain information report "
    "reports year years december including consolidated statements statement million millions total "
    "according respective respectively other such based have this business financial".split()
)

_STRUCTURE_WORDS = frozenset(
    "with which table tables content contents note notes following page pages see certain information report "
    "reports year years december including consolidated statements statement million millions total "
    "according respective respectively other such based have this business financial".split()
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
    merely mention many common words. Metric-shaped questions additionally
    fire financial-intent probes: standard line-item labels and the titles
    of the audited statements, whose wording a question borrows only
    loosely ("how fast did it sell its inventory" -> the Inventories row of
    the balance sheet next to the cost-of-sales line of the income
    statement). Every probe goes through the public Memory search API;
    phrases whose every word is common in this corpus (a company name, for
    example) carry no ranking signal and are skipped.
    """

    from powercontext.builtin.artifacts.memory.models import MemoryCitation
    from powercontext.builtin.runtime import SearchMemoryRequest

    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-blank string")  # noqa: TRY003
    if type(limit) is not int or limit < 1:
        raise ValueError("limit must be a positive integer")  # noqa: TRY003

    pool = 150
    kind_weight = {
        "view": 0.7,
        "ngram": 1.3,
        "term": 1.0,
        "variant": 0.6,
        "expansion": 0.5,
        "intent": 1.1,
        "title": 2.0,
    }

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
    for terms in _finance_intent_terms(question):
        expanded = list(terms)
        for term in terms:
            if " " not in term and len(term) > 4:
                if term.endswith("ies"):
                    expanded.append(term[:-3] + "y")
                elif term.endswith("s") and not term.endswith("ss"):
                    expanded.append(term[:-1])
        for term in expanded:
            probes.append(("intent", term, await search(term)))
        probes.append(("intent", " ".join(terms), await search(" ".join(terms))))
    for title in _finance_intent_titles(question):
        probes.append(("intent", title, await search(title)))
    page_tokens: dict[str, frozenset[str]] = {}
    func_words = frozenset({"of", "and", "the", "to", "for"})
    for title in _finance_intent_titles(question):
        hits = await search(title)
        required = [token for token in _WORD_PATTERN.findall(title.lower()) if token not in func_words]
        strict: list = []
        for hit in hits:
            text = hit.text or ""
            tokens = page_tokens.get(text)
            if tokens is None:
                tokens = frozenset(_WORD_PATTERN.findall(text.lower()))
                page_tokens[text] = tokens
            if all(token in tokens for token in required):
                strict.append(hit)
        probes.append(("title", title, strict))

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

    # Adjacency propagation: annual-report evidence arrives in contiguous
    # blocks (the audited statements span a handful of facing pages, the
    # litigation note runs over several). A page whose neighbours earned
    # strong fusion scores is part of such a block even when its own votes
    # are thin -- the balance sheet next to the income statement it was
    # asked about -- so each page receives a share of its best neighbour's
    # score. Page numbers come from the source references of the leading
    # entries through the public Memory read API.
    from powercontext.builtin.runtime import GetMemoryEntryRequest

    async def page_number(citation) -> int | None:
        result = await memory.get(GetMemoryEntryRequest(citation=citation))
        for reference in result.entry.sources:
            tail = str(reference.source_id).rsplit(":", 1)[-1]
            if tail.isdigit():
                return int(tail)
        return None

    page_of_key: dict[tuple[str, str, str], int] = {}
    for key in ranked[:90]:
        number = await page_number(citations[key])
        if number is not None:
            page_of_key[key] = number
    # Statement pages can fuse far below the leading scores -- a balance
    # sheet beaten at its own title by management summaries and subsidiary
    # schedules has almost no votes of its own -- yet they all appear in the
    # strict title probes, so map those pages too instead of letting the
    # block bonus miss them.
    title_keys: list[tuple[str, str, str]] = []
    title_seen: set[tuple[str, str, str]] = set()
    for kind, _query, hits in probes:
        if kind != "title":
            continue
        for hit in hits:
            key = (str(hit.memory_ref), str(hit.entry_id), str(hit.entry_version_id))
            if key not in page_of_key and key not in title_seen:
                title_seen.add(key)
                title_keys.append(key)
    for key in title_keys[:100]:
        number = await page_number(citations[key])
        if number is not None:
            page_of_key[key] = number

    # Audited-statement block bonus: management discussion condenses the
    # same statements under the same titles pages before the audit report,
    # and subsidiary schedules reprint them pages after the notes, so title
    # probes alone cannot say which occurrence carries the audited figures.
    # The auditor's report ("we have audited ...") opens the audited block,
    # and for a statement-seeking question the pages that follow it are the
    # primary statements, whatever else in the corpus repeats their names.
    # A report preceding the subsidiary schedules says it too, so the
    # earliest audit page is the one that opens the primary block.
    if _finance_intent_titles(question):
        audit_pages: list[int] = []
        for hit in await search("we have audited"):
            if "we have audited" not in (hit.text or "").lower():
                continue
            number = await page_number(
                MemoryCitation(memory_ref=hit.memory_ref, entry_id=hit.entry_id, entry_version_id=hit.entry_version_id)
            )
            if number is not None:
                audit_pages.append(number)
            if len(audit_pages) >= 6:
                break
        if audit_pages:
            audit_page = min(audit_pages)
            for key, number in page_of_key.items():
                if audit_page < number <= audit_page + 12:
                    scores[key] = scores.get(key, 0.0) + 30.0

    if len(page_of_key) >= 3:
        best_by_page: dict[int, float] = {}
        for key, page in page_of_key.items():
            best_by_page[page] = max(best_by_page.get(page, 0.0), scores[key])
        for key, page in page_of_key.items():
            neighbour = max(best_by_page.get(page - 1, 0.0), best_by_page.get(page + 1, 0.0))
            if neighbour > 0.0:
                scores[key] = scores.get(key, 0.0) + 0.35 * neighbour
        ranked = sorted(scores, key=lambda key: (-scores[key], order[key]))

    top = list(ranked[:limit])
    if limit >= 12 and len(top) == limit:
        # Champion coverage: evidence pages that bridge vocabulary ("sold its
        # inventory" -> the Inventories row) often rank first in one intent
        # probe while fusing below the cutoff because the question words
        # themselves never occur on them. The best pages of the rarest intent
        # probes take tail slots, but pages that already rank high, and pages
        # that lead some other rare intent probe, are never evicted for it.
        protected = set(top[:15])
        candidates: list[tuple[str, str, str]] = []
        seen_champ: set[tuple[str, str, str]] = set()
        for champion_kind, budget in (("intent", 3), ("title", 2)):
            shortlist = [
                (len(hits), index, hits)
                for index, (kind, _query, hits) in enumerate(probes)
                if kind == champion_kind and hits and len(hits) <= 80
            ]
            shortlist.sort(key=lambda item: (item[0], -item[1]))
            taken = 0
            for _df, _index, hits in shortlist:
                if taken >= budget or len(candidates) >= 5:
                    break
                for hit in hits[:3]:
                    key = (str(hit.memory_ref), str(hit.entry_id), str(hit.entry_version_id))
                    if key in seen_champ or _navigational_factor(hit.text or "") < 1.0:
                        continue
                    seen_champ.add(key)
                    protected.add(key)
                    if key not in top:
                        candidates.append(key)
                        taken += 1
                        if key not in citations:
                            citations[key] = MemoryCitation(
                                memory_ref=hit.memory_ref, entry_id=hit.entry_id, entry_version_id=hit.entry_version_id
                            )
                        if len(candidates) >= 5:
                            break
        idx = len(top) - 1
        for key in candidates:
            while idx >= 15 and top[idx] in protected:
                idx -= 1
            if idx < 15:
                break
            top[idx] = key
            idx -= 1
    return tuple(citations[key] for key in top)


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


_INCOME_TITLES = (
    "consolidated statements of income",
    "consolidated statement of income",
    "consolidated statements of operations",
    "consolidated statement of operations",
    "consolidated statements of earnings",
    "consolidated statement of earnings",
)
_BALANCE_TITLES = (
    "consolidated balance sheets",
    "consolidated balance sheet",
    "consolidated statements of financial position",
    "consolidated statement of financial position",
)
_CASHFLOW_TITLES = (
    "consolidated statements of cash flows",
    "consolidated statement of cash flows",
)

_FINANCE_INTENTS: tuple[tuple[re.Pattern[str], tuple[str, ...], tuple[str, ...]], ...] = (
    (
        re.compile(r"capital[ -]intens|capex|capital expenditure|pp&e|ppne|property plant", re.IGNORECASE),
        ("capital expenditures", "net property", "property plant equipment"),
        _INCOME_TITLES + _BALANCE_TITLES + _CASHFLOW_TITLES,
    ),
    (
        re.compile(r"inventor|turnover", re.IGNORECASE),
        ("inventories", "cost of sales", "cost of goods sold"),
        _INCOME_TITLES + _BALANCE_TITLES,
    ),
    (
        re.compile(r"legal|litigat|lawsuit", re.IGNORECASE),
        ("litigation", "legal proceedings", "legal actions"),
        (),
    ),
    (
        re.compile(r"debt", re.IGNORECASE),
        ("long-term debt", "total debt", "short-term borrowings", "debt maturities", "maturities"),
        _BALANCE_TITLES + _CASHFLOW_TITLES,
    ),
    (
        re.compile(r"liquid|quick ratio|current ratio", re.IGNORECASE),
        ("cash and cash equivalents", "current assets", "working capital"),
        _BALANCE_TITLES + _CASHFLOW_TITLES,
    ),
    (
        re.compile(r"tax", re.IGNORECASE),
        ("effective tax rate", "income taxes"),
        _INCOME_TITLES,
    ),
    (
        re.compile(r"gross (margin|profit)", re.IGNORECASE),
        ("cost of products", "cost of revenues", "gross margin"),
        _INCOME_TITLES,
    ),
    (
        re.compile(r"operating (margin|income|profit|profile)", re.IGNORECASE),
        ("operating income", "operating margin"),
        _INCOME_TITLES,
    ),
    (
        re.compile(r"balance sheet|financial position", re.IGNORECASE),
        ("total assets", "total liabilities"),
        _BALANCE_TITLES,
    ),
    (
        re.compile(r"cash flow", re.IGNORECASE),
        ("operating activities", "investing activities", "capital expenditures"),
        _CASHFLOW_TITLES,
    ),
    (
        re.compile(r"segment|categor", re.IGNORECASE),
        ("business segment", "segment data", "products and services"),
        _INCOME_TITLES,
    ),
    (re.compile(r"customer", re.IGNORECASE), ("customers",), ()),
    (re.compile(r"acquisition|m&a|merger", re.IGNORECASE), ("acquisitions",), ()),
    (re.compile(r"dividend", re.IGNORECASE), ("dividends", "cash dividends"), ()),
    (re.compile(r"liabilit", re.IGNORECASE), ("total liabilities", "long-term debt", "deposits"), _BALANCE_TITLES),
    (re.compile(r"income statement|statement of (operations|income|earnings)", re.IGNORECASE), (), _INCOME_TITLES),
    (re.compile(r"restructuring", re.IGNORECASE), ("restructuring", "restructuring charges"), _INCOME_TITLES),
)


def _finance_intent_terms(question: str) -> tuple[tuple[str, ...], ...]:
    """Financial-intent term groups triggered by the question wording.

    Metric-shaped questions cite statements and notes whose wording uses standard
    line-item labels instead of the question's phrasing ("sold its inventory" ->
    the Inventories row; "legal battles" -> the Legal Proceedings note). Each
    triggered intent contributes its label terms plus one combined co-occurrence
    probe: three or more distinct terms push the backend's coverage threshold to
    two required matches, which statement tables satisfy together and prose pages
    rarely do.
    """

    groups: list[tuple[str, ...]] = []
    seen_terms: set[str] = set()
    for pattern, terms, _titles in _FINANCE_INTENTS:
        if not pattern.search(question):
            continue
        fresh = tuple(term for term in terms if term not in seen_terms)
        seen_terms.update(fresh)
        if len(fresh) >= 2:
            groups.append(fresh)
    return tuple(groups)


def _finance_intent_titles(question: str) -> tuple[str, ...]:
    """Statement-title probes triggered by the question wording.

    The audited statements answer metric questions in every sector with the
    same page titles, while their line items vary by industry (an airline's
    income statement never says "cost of revenues"). Questions about
    margins, taxes, capital intensity, liquidity or named statements
    therefore also probe the statement titles themselves, in the singular
    and plural spellings annual reports use. The phrases are rare in the
    corpus, so their votes concentrate on the statement pages; the
    required-match semantics of multi-term queries keep prose mentions of
    "consolidated" from earning bands.
    """

    titles: list[str] = []
    seen: set[str] = set()
    for pattern, _terms, family in _FINANCE_INTENTS:
        if not pattern.search(question):
            continue
        for title in family:
            if title not in seen:
                seen.add(title)
                titles.append(title)
    return tuple(titles)


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
_AUDIT_REPORT_PATTERN = re.compile(r"we have audited", re.IGNORECASE)


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

    Auditor reports repeat every statement title ("we have audited the
    accompanying consolidated statements of income ..."), which lets them
    outrank the statements themselves on title probes; they precede the
    statements instead of carrying them and never hold report evidence.
    """

    if len(_REFERENCE_PATTERN.findall(text)) >= 8:
        return 0.15
    if _HEAD_EXHIBIT_PATTERN.search(text.lower()[:90]):
        return 0.15
    if _AUDIT_REPORT_PATTERN.search(text[:1200]):
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
