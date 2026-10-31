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
import re
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
_SEARCH_STOPWORDS = frozenset(
    """
    about above after again against all also among and any are because been before being below
    between both but can could did does doing down during each few for from further had has have
    having her here hers herself him himself his how into its itself just mainly more most only
    other our ours ourselves over own same she should some such than that the their theirs them
    themselves then there these they this those through under until very was were what when where
    which while who whom why will with would year years reported report
    """.split()
)


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


async def search_pdf_pages(
    memory: Any,
    question: str,
    limit: int = 10,
) -> tuple[MemoryCitation, ...]:
    """Return up to ``limit`` distinct evidence pages as exact citations."""

    from powercontext.builtin.artifacts.memory.models import MemoryCitation
    from powercontext.builtin.runtime.models import GetMemoryEntryRequest, SearchMemoryRequest

    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError("limit must be a positive integer")  # noqa: TRY003
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-empty string")  # noqa: TRY003

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


def _search_queries(question: str) -> tuple[str, ...]:
    tokens = [token.lower() for token in _TOKEN.findall(question)]
    keywords = [token for token in tokens if len(token) >= 3 and token not in _SEARCH_STOPWORDS]
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
