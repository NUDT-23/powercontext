from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Iterable

import fitz
import httpx

from .seekdb_store import SeekDBStore


ARXIV_URL_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE)
ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"


def chunk_text(
    text: str,
    max_chars: int = 1100,
    overlap: int = 140,
    section: str = "body",
    page: int = 0,
) -> list[dict]:
    text = re.sub(r"[ \t]+", " ", text).strip()
    if not text:
        return []
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks: list[dict] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append({"text": current, "section": section, "page": page})
            tail = current[-overlap:] if overlap else ""
            current = f"{tail}\n\n{paragraph}".strip()
        else:
            for start in range(0, len(paragraph), max_chars - overlap):
                piece = paragraph[start : start + max_chars]
                if piece.strip():
                    chunks.append({"text": piece.strip(), "section": section, "page": page})
            current = ""
    if current.strip():
        chunks.append({"text": current.strip(), "section": section, "page": page})
    return chunks


def parse_pdf(data: bytes) -> dict:
    document = fitz.open(stream=data, filetype="pdf")
    metadata = document.metadata or {}
    pages: list[dict] = []
    full_text: list[str] = []
    for index, page in enumerate(document):
        text = page.get_text("text")
        if text and text.strip():
            pages.append({"page": index + 1, "text": text})
            full_text.append(text)
    return {
        "title": (metadata.get("title") or "").strip(),
        "authors": (metadata.get("author") or "").strip(),
        "pages": pages,
        "text": "\n\n".join(full_text).strip(),
        "page_count": document.page_count,
    }


def chunks_from_pdf(data: bytes) -> tuple[dict, list[dict]]:
    parsed = parse_pdf(data)
    chunks: list[dict] = []
    for page in parsed["pages"]:
        chunks.extend(
            chunk_text(page["text"], section=f"page-{page['page']}", page=page["page"])
        )
    if not chunks and parsed["text"]:
        chunks = chunk_text(parsed["text"])
    return parsed, chunks


def fetch_arxiv(arxiv_id: str) -> dict:
    url = f"https://export.arxiv.org/api/query?id_list={arxiv_id}"
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        response = client.get(url)
    response.raise_for_status()
    root = ET.fromstring(response.text)
    entry = root.find(f"{ATOM}entry")
    if entry is None:
        raise RuntimeError(f"arXiv metadata not found for {arxiv_id}")
    title = _xml_text(entry.find(f"{ATOM}title"))
    summary = _xml_text(entry.find(f"{ATOM}summary"))
    published = _xml_text(entry.find(f"{ATOM}published"))
    authors = [
        _xml_text(author.find(f"{ATOM}name"))
        for author in entry.findall(f"{ATOM}author")
    ]
    journal_ref = _xml_text(entry.find(f"{ARXIV_NS}journal_ref"))
    return {
        "arxiv_id": arxiv_id,
        "title": title,
        "authors": ", ".join([author for author in authors if author]),
        "year": int(published[:4]) if published[:4].isdigit() else None,
        "venue": journal_ref or "arXiv",
        "abstract": summary,
        "source": "arxiv",
    }


def _xml_text(node) -> str:
    if node is None or node.text is None:
        return ""
    return re.sub(r"\s+", " ", node.text).strip()


def download_arxiv_pdf(arxiv_id: str) -> bytes | None:
    url = f"https://arxiv.org/pdf/{arxiv_id}"
    try:
        with httpx.Client(timeout=90.0, follow_redirects=True) as client:
            response = client.get(url, headers={"User-Agent": "PaperLens/0.1"})
        if response.status_code >= 400:
            return None
        if not response.content.startswith(b"%PDF"):
            return None
        return response.content
    except Exception:  # noqa: BLE001
        return None


def ingest_arxiv(store: SeekDBStore, project_id: str, url_or_id: str) -> dict:
    match = ARXIV_URL_RE.search(url_or_id)
    arxiv_id = match.group(1) if match else url_or_id.strip()
    if not re.fullmatch(r"\d{4}\.\d{4,5}", arxiv_id):
        raise ValueError("请输入合法的 arXiv 链接或形如 2401.12345 的编号")

    if store.paper_exists(project_id, arxiv_id):
        raise ValueError(f"文献 {arxiv_id} 已导入")

    paper = fetch_arxiv(arxiv_id)
    chunks: list[dict] = []
    pdf = download_arxiv_pdf(arxiv_id)
    if pdf:
        parsed, chunks = chunks_from_pdf(pdf)
        if not paper["title"]:
            paper["title"] = parsed.get("title") or f"arXiv {arxiv_id}"
        if not paper["authors"]:
            paper["authors"] = parsed.get("authors") or ""
    if not chunks:
        abstract = paper.get("abstract") or paper.get("title") or arxiv_id
        chunks = chunk_text(f"Title: {paper['title']}\n\nAbstract: {abstract}", section="abstract")

    return store.add_paper(project_id, paper, chunks)


def ingest_pdf(
    store: SeekDBStore,
    project_id: str,
    filename: str,
    data: bytes,
    title: str = "",
    authors: str = "",
    year: int | None = None,
    venue: str = "",
) -> dict:
    parsed, chunks = chunks_from_pdf(data)
    paper = {
        "title": title.strip() or parsed.get("title") or filename.rsplit(".", 1)[0],
        "authors": authors.strip() or parsed.get("authors") or "",
        "year": year,
        "venue": venue.strip() or "Uploaded PDF",
        "arxiv_id": "",
        "abstract": (chunks[0]["text"][:1500] if chunks else ""),
        "source": "upload",
    }
    if not chunks:
        raise ValueError("PDF 未解析出文本（可能是扫描件），请先 OCR")
    return store.add_paper(project_id, paper, chunks[:80])
