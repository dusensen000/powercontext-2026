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

"""Physical-page PDF Sources and evidence-page retrieval."""

from __future__ import annotations

import hashlib
import io
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, unquote

from pydantic import BaseModel
from pypdf import PdfReader

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources import TEXT_EVIDENCE_PROJECTION_KEY, AdapterSourceDefinition, TextEvidence
from powercontext.sources.models import Source, SourceMaterialization

if TYPE_CHECKING:
    from powercontext.builtin.artifacts.memory.models import MemoryCitation

PDF_PAGE_SOURCE_NAME = "pdf-page"
_TOKEN = re.compile(r"[A-Za-z]+|\d+")
_PERCENT_NUMBER = re.compile(r"(\d+)\s*%")
_STOPWORDS = frozenset(
    """
    about above after again against all also among and any are because been before being below
    between both but can could did does doing done down during each few for from further had has
    have having her here hers herself him himself his how into its itself just mainly more most
    only other our ours ourselves over own same she should some such than that the their theirs
    them themselves then there these they this those through under until very was were what when
    where which while who whom why will with would year years reported report
    answer question questions respond response give given show shown within detail details assume
    assuming perspective analyst analysts use using calculate calculation define definition
    exact quote kindly please explain explanation state stated mention provide format output number
    numbers usd dollar dollars million millions billion billions percentage percent company like
    useful metric profile improving reasonably healthy relevant outlined explicitly quantity
    much many not able
    """.split()
)
# Morphological bridges between the wording of a question and that of a filing.
_SYNONYMS = {
    "battl": ("litigation", "proceedings", "lawsuit"),
    "litigat": ("proceedings",),
    "retain": ("retention",),
    "cycl": ("cyclical",),
    "acquisit": ("acquire",),
    "primar": ("major", "principal"),
    "major": ("primary",),
    "restructur": ("impairment", "charges"),
    "drov": ("driven", "drive", "driving"),
}
# Question intents that no single content word carries.
_EXPANSIONS = {
    "geograph": (
        "geographic regions countries territories united states europe asia africa latin america "
        "north america middle east canada china japan international worldwide emea apac",
    ),
    "leg": ("litigation proceedings lawsuits claims contingencies investigations",),
    "cycl": ("seasonality cyclical",),
}
# Financial-statement intents and the page titles that answer them.
_CONCEPTS = (
    (
        ("balance sheet", "quick ratio", "current ratio", "liquidity", "liabilit", "asset"),
        ("balance sheet", "balance sheets"),
    ),
    (
        (
            "income statement",
            "statements of income",
            "statement of income",
            "statement of operations",
            "statements of operations",
            "gross margin",
            "operating margin",
            "margin",
            "tax rate",
            "profit",
            "earnings",
            "ebitda",
            "income",
        ),
        ("statement of income", "statements of income", "statement of operations", "statements of operations"),
    ),
    (
        (
            "cash flow",
            "cash flows",
            "operating activities",
            "investing",
            "financing",
            "ebitda",
            "depreciation",
            "amortization",
        ),
        ("statement of cash flows", "statements of cash flows"),
    ),
)
_HEADING_WEIGHT = 3.0
_BIGRAM_WEIGHT = 0.6
_STATEMENT_WEIGHT = 10.0
_SYNONYM_WEIGHT = 1.0
_HEADING_MAX_TF = 5
_BM25_K1 = 1.2
_BM25_B = 0.75


class PDFDocumentInput(BaseModel):
    """One complete original PDF and the caller's document identity."""

    document_id: str
    content: bytes


class PDFPageInput(BaseModel):
    """One physical page extracted from the original PDF bytes."""

    document_id: str
    document_sha256: str
    page_number: int
    text: str


class PDFPageSource(Source):
    """Captured evidence for exactly one physical PDF page."""

    source_id: str
    document_id: str
    document_sha256: str
    page_number: int
    text: str


def parse_pdf_document(value: PDFDocumentInput, /) -> tuple[PDFPageInput, ...]:
    """Extract every physical page, in order, or fail without partial pages."""

    if not isinstance(value.document_id, str) or not value.document_id.strip():
        raise ValueError("document_id must not be blank")  # noqa: TRY003
    content = value.content
    if not isinstance(content, bytes) or not content:
        raise ValueError("PDF content must be non-empty bytes")  # noqa: TRY003
    digest = hashlib.sha256(content).hexdigest()

    try:
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("PDF requires a user password")  # noqa: TRY003
        raw_pages = tuple(reader.pages)
        if not raw_pages:
            raise ValueError("PDF contains no physical pages")  # noqa: TRY003
        pages = tuple(
            PDFPageInput(
                document_id=value.document_id,
                document_sha256=digest,
                page_number=number,
                text=page.extract_text() or "",
            )
            for number, page in enumerate(raw_pages, start=1)
        )
    except ValueError:
        raise
    except Exception as error:
        raise ValueError(f"PDF could not be parsed completely: {error}") from error
    return pages


class _PDFPageAdapter:
    """Resolve extracted pages into captured Sources and back."""

    input_class = PDFPageInput
    name = PDF_PAGE_SOURCE_NAME
    source_class = PDFPageSource

    async def resolve(self, value: PDFPageInput, /) -> PDFPageSource:
        source_id = _page_source_id(value.document_id, value.document_sha256, value.page_number)
        return PDFPageSource(
            name=source_id,
            materialization=SourceMaterialization.CAPTURED,
            source_id=source_id,
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


class _PDFPageTextEvidence:
    """Name the page by document identity and physical page number."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PDFPageSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PDFPageSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=PDF_PAGE_SOURCE_NAME,
            source_id=source.name,
            content=f"{source.document_id}\n{source.text}",
            metadata={
                "document_id": source.document_id,
                "document_sha256": source.document_sha256,
                "page_number": source.page_number,
            },
        )


PDF_PAGE_SOURCE_DEFINITION = AdapterSourceDefinition(
    _PDFPageAdapter(),
    projections=(_PDFPageTextEvidence(),),
)


@dataclass
class _PageRecord:
    """One stored page ready for local evidence ranking."""

    document_id: str
    page_number: int
    text: str
    citation: MemoryCitation
    stems: list[str] = field(default_factory=list)
    tf: Counter = field(default_factory=Counter)
    heading: frozenset[str] = frozenset()
    pairs: frozenset[tuple[str, str]] = frozenset()

    @property
    def key(self) -> tuple[str, int]:
        return (self.document_id, self.page_number)


async def search_pdf_pages(
    memory: Any,
    question: str,
    limit: int = 10,
) -> tuple[MemoryCitation, ...]:
    """Return up to ``limit`` distinct evidence pages as exact citations.

    The page set is ranked locally on the exact stored entry texts so that
    evidence pages are ordered by relevance instead of by retrieval order.
    """

    from powercontext.builtin.artifacts.memory.models import MemoryCitation
    from powercontext.builtin.runtime.models import GetMemoryEntryRequest, SearchMemoryRequest

    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError("limit must be a positive integer")  # noqa: TRY003
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-empty string")  # noqa: TRY003

    records = await _load_page_records(memory)
    ranked = _rank_pages(records, question, limit) if records else ()
    if ranked:
        return ranked

    query_limit = min(max(limit * 4, 40), 160)
    fused: dict[tuple[str, int], float] = {}
    citations: dict[tuple[str, int], MemoryCitation] = {}
    for query_index, query in enumerate(_search_queries(question)):
        page = await memory.search(SearchMemoryRequest(query=query, mode="fts", limit=query_limit))
        for rank, hit in enumerate(page.hits, start=1):
            citation = MemoryCitation(
                memory_ref=hit.memory_ref,
                entry_id=hit.entry_id,
                entry_version_id=hit.entry_version_id,
            )
            entry = (await memory.get(GetMemoryEntryRequest(citation=citation))).entry
            page_key = _page_from_entry(entry)
            if page_key is None:
                continue
            weight = 1.0 / (60 + rank) + (0.001 / (query_index + 1))
            fused[page_key] = fused.get(page_key, 0.0) + weight
            citations.setdefault(page_key, citation)
    ordered = sorted(fused, key=lambda key: (-fused[key], key[0], key[1]))
    return tuple(citations[key] for key in ordered[:limit])


async def _load_page_records(memory: Any) -> tuple[_PageRecord, ...]:
    """Read every stored page entry without issuing a search per question."""

    if not hasattr(memory, "list"):
        return ()
    page = await memory.list()
    records: dict[tuple[str, int], _PageRecord] = {}
    for record in page.entries:
        for reference in record.entry.sources:
            if reference.source_type != PDF_PAGE_SOURCE_NAME:
                continue
            parsed = _parse_page_source_id(reference.source_id)
            if parsed is None or parsed in records:
                continue
            document_id, page_number = parsed
            text = record.entry.text
            prefix = f"{document_id}\n"
            if text.startswith(prefix):
                text = text[len(prefix) :]
            elif text == document_id:
                text = ""
            records[parsed] = _PageRecord(
                document_id=document_id,
                page_number=page_number,
                text=text.lower(),
                citation=record.citation,
            )
            break
    return tuple(records.values())


def _prepare_page(record: _PageRecord) -> None:
    if record.stems or not record.text:
        return
    record.stems = [_stem(token) for token in _TOKEN.findall(record.text)]
    record.tf = Counter(record.stems)
    headings: set[str] = set()
    for line in record.text.splitlines():
        words = _TOKEN.findall(line)
        if not 1 <= len(words) <= 10 or "contents" in words:
            continue
        headings.update(_stem(word) for word in words)
    record.heading = frozenset(headings)
    record.pairs = frozenset(zip(record.stems, record.stems[1:]))


def _rank_pages(
    records: tuple[_PageRecord, ...],
    question: str,
    limit: int,
) -> tuple[MemoryCitation, ...]:
    documents = dict.fromkeys(record.document_id for record in records)
    target, matched = _select_document(question, tuple(documents))
    pool = [record for record in records if record.document_id == target] if target is not None else list(records)
    weights, pairs = _query_model(question)
    if target is not None:
        identity_stems = {_stem(token) for token in matched}
        weights = {term: weight for term, weight in weights.items() if term not in identity_stems}
        pairs = tuple((left, right) for left, right in pairs if left in weights and right in weights)
    if not pool or not weights:
        return ()

    for record in pool:
        _prepare_page(record)
    idf, _ = _idf_map(pool, tuple(weights))
    avgdl = sum(len(record.stems) for record in pool) / len(pool) or 1.0
    concepts = tuple(
        titles for triggers, titles in _CONCEPTS if any(trigger in question.lower() for trigger in triggers)
    )

    scores: dict[tuple[str, int], float] = {}
    for record in pool:
        length = len(record.stems)
        score = 0.0
        for term, weight in weights.items():
            frequency = record.tf.get(term, 0)
            if frequency:
                score += (
                    weight
                    * idf[term]
                    * frequency
                    * (_BM25_K1 + 1)
                    / (frequency + _BM25_K1 * (1 - _BM25_B + _BM25_B * length / avgdl))
                )
        for term, weight in weights.items():
            if (
                term in record.heading
                and record.tf.get(term, 0) < _HEADING_MAX_TF
            ):
                score += weight * _HEADING_WEIGHT * idf[term]
        for left, right in pairs:
            if (left, right) in record.pairs:
                score += _BIGRAM_WEIGHT * (idf.get(left, 0.0) + idf.get(right, 0.0))
        for titles in concepts:
            if any(title in record.text for title in titles):
                score += _STATEMENT_WEIGHT
        scores[record.key] = score

    ordered = sorted(pool, key=lambda record: (-scores[record.key], record.document_id, record.page_number))
    return tuple(record.citation for record in ordered[:limit])


def _idf_map(pages: list[_PageRecord], terms: tuple[str, ...]) -> tuple[dict[str, float], Counter]:
    total = len(pages)
    document_frequency: Counter = Counter()
    for record in pages:
        seen = set(record.stems)
        for term in terms:
            if term in seen:
                document_frequency[term] += 1
    idf = {
        term: math.log(1 + (total - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5))
        for term in terms
    }
    return idf, document_frequency


def _query_model(question: str) -> tuple[dict[str, float], tuple[tuple[str, str], ...]]:
    percent_numbers = set(_PERCENT_NUMBER.findall(question))
    base: list[str] = []
    for token in _question_tokens(question):
        if token.isdigit():
            if len(token) < 4 and token not in percent_numbers:
                continue
        elif len(token) < 3 or token in _STOPWORDS:
            continue
        term = _stem(token)
        if term not in base:
            base.append(term)
    weights: dict[str, float] = dict.fromkeys(base, 1.0)
    variants: dict[str, list[str]] = {}
    for term in base:
        expanded = [_stem(item) for item in _SYNONYMS.get(term, ())]
        expanded += [_stem(item) for phrase in _EXPANSIONS.get(term, ()) for item in phrase.split()]
        variants[term] = expanded
        for item in expanded:
            weights.setdefault(item, _SYNONYM_WEIGHT)
    pairs: list[tuple[str, str]] = []
    for left, right in zip(base, base[1:]):
        for left_variant in (left, *variants[left]):
            for right_variant in (right, *variants[right]):
                pairs.append((left_variant, right_variant))
    return weights, tuple(pairs)


def _question_tokens(question: str) -> list[str]:
    return [token.lower() for token in _TOKEN.findall(question)]


def _select_document(question: str, documents: tuple[str, ...]) -> tuple[str | None, set[str]]:
    scored = sorted(
        ((document, *_identity(question, document)) for document in documents),
        key=lambda item: (-item[1], item[0]),
    )
    if not scored:
        return None, set()
    best_document, best_score, matched = scored[0]
    runner_up = scored[1][1] if len(scored) > 1 else 0.0
    if best_score >= 1.0 and best_score - runner_up >= 1.0:
        return best_document, matched
    return None, set()


def _identity(question: str, document_id: str) -> tuple[float, set[str]]:
    normalized = re.sub(r"[^a-z0-9]+", "", document_id.lower())
    score = 0.0
    matched: set[str] = set()
    tokens = _question_tokens(question)
    for token in tokens:
        if token.isdigit():
            if len(token) == 4 and token in normalized:
                score += 0.5
                matched.add(token)
        elif len(token) >= 3 and token not in _STOPWORDS and token in normalized:
            score += 1.0
            matched.add(token)
    for left, right in zip(tokens, tokens[1:]):
        if left.isalpha() and right.isalpha():
            joined = left + right
            if len(joined) >= 6 and joined in normalized:
                score += 2.0
    return score, matched


def _stem(word: str) -> str:
    if not word.isalpha() or len(word) <= 3:
        return word
    value = word
    for _ in range(5):
        previous = value
        length = len(value)
        if value.endswith("ies") and length > 4:
            value = value[:-3] + "y"
        elif value.endswith("sses"):
            value = value[:-2]
        elif value.endswith("es") and length > 4:
            value = value[:-2]
        elif value.endswith("s") and not value.endswith("ss") and length > 3:
            value = value[:-1]
        elif value.endswith("ing") and length > 5:
            value = value[:-3]
        elif value.endswith("ed") and length > 4:
            value = value[:-2]
        elif value.endswith("ions") and length > 5:
            value = value[:-4]
        elif value.endswith("ion") and length > 4:
            value = value[:-3]
        elif value.endswith("ity") and length > 5:
            value = value[:-3]
        elif value.endswith("ical") and length > 6:
            value = value[:-4]
        elif value.endswith("ic") and length > 5:
            value = value[:-2]
        elif value.endswith("al") and length > 4:
            value = value[:-2]
        elif value.endswith("ly") and length > 4:
            value = value[:-2]
        elif value.endswith("ment") and length > 6:
            value = value[:-4]
        elif value.endswith("y") and length > 3:
            value = value[:-1] + "i"
        elif value.endswith("i") and length > 4:
            value = value[:-1]
        elif value.endswith("e") and length > 4:
            value = value[:-1]
        if value == previous:
            break
    return value


def _search_queries(question: str) -> tuple[str, ...]:
    tokens = _question_tokens(question)
    keywords = [token for token in tokens if len(token) >= 3 and token not in _STOPWORDS]
    numbers = [token for token in tokens if token.isdigit()]
    queries: list[str] = [question.strip()]
    if keywords:
        keyword_query = " ".join(dict.fromkeys(keywords))
        if keyword_query != queries[0]:
            queries.append(keyword_query)
    if numbers and keywords:
        numeric_query = " ".join(dict.fromkeys(numbers + keywords[:6]))
        if numeric_query not in queries:
            queries.append(numeric_query)
    return tuple(queries)


def _page_from_entry(entry: Any) -> tuple[str, int] | None:
    for reference in entry.sources:
        if reference.source_type != PDF_PAGE_SOURCE_NAME:
            continue
        parsed = _parse_page_source_id(reference.source_id)
        if parsed is not None:
            return parsed
    return None


def _page_source_id(document_id: str, document_sha256: str, page_number: int) -> str:
    source_id = f"pdf:{quote(document_id, safe='')}:{document_sha256}:{page_number}"
    if len(source_id) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(  # noqa: TRY003
            f"pdf page source_id must not exceed {MAX_SOURCE_ID_LENGTH} characters"
        )
    return source_id


def _parse_page_source_id(source_id: str) -> tuple[str, int] | None:
    parts = source_id.split(":")
    if len(parts) != 4 or parts[0] != "pdf" or len(parts[2]) != 64:
        return None
    try:
        page_number = int(parts[3])
    except ValueError:
        return None
    if page_number < 1:
        return None
    return unquote(parts[1]), page_number


__all__ = [
    "PDF_PAGE_SOURCE_DEFINITION",
    "PDFDocumentInput",
    "PDFPageInput",
    "PDFPageSource",
    "parse_pdf_document",
    "search_pdf_pages",
]
