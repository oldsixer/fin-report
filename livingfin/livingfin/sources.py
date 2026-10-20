"""Source acquisition and citeable PDF/HTML text chunks."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from .graph import within_cutoff


class SourceError(RuntimeError):
    pass


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.hidden = 0
        self.dates: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag in {"script", "style", "nav", "footer"}:
            self.hidden += 1
        if tag in {"p", "div", "h1", "h2", "h3", "li", "tr", "br"}:
            self.parts.append("\n")
        if tag == "meta" and attributes.get("property") in {"article:published_time", "article:modified_time"}:
            if attributes.get("content"):
                self.dates.append(str(attributes["content"])[:10])
        if tag == "time" and attributes.get("datetime"):
            self.dates.append(str(attributes["datetime"])[:10])

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "nav", "footer"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


@dataclass
class Document:
    title: str
    url: str
    publisher: str
    published_at: str
    date_basis: str
    media_type: str
    pages: list[str]
    local_path: str


def load_manifest(path: Path, as_of: str) -> list[dict[str, str]]:
    if not path.exists():
        raise SourceError(f"Missing source manifest: {path}")
    items = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(items, list):
        raise SourceError("Source manifest must be a JSON array")
    result: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict) or not all(item.get(k) for k in ("url", "title", "publisher", "published_at")):
            raise SourceError("Each source requires url, title, publisher, published_at")
        date.fromisoformat(str(item["published_at"]))
        dated_url = re.search(r"/(20\d\d-\d\d-\d\d)/", str(item["url"]))
        if dated_url and dated_url.group(1) != str(item["published_at"]):
            raise SourceError(f"Source date disagrees with URL date: {item['url']}")
        if not within_cutoff(str(item["published_at"]), as_of):
            raise SourceError(f"Source after as-of date: {item['url']}")
        entry = {k: str(item[k]) for k in ("url", "title", "publisher", "published_at")}
        if item.get("source_role"):
            entry["source_role"] = str(item["source_role"])
        result.append(entry)
    return result


def _chunks(text: str, width: int = 2600) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    chunks: list[str] = []
    current = ""
    for line in lines:
        if len(current) + len(line) + 1 > width and current:
            chunks.append(current)
            current = ""
        if len(line) > width:
            for i in range(0, len(line), width):
                piece = line[i:i + width]
                if current:
                    chunks.append(current)
                    current = ""
                chunks.append(piece)
        else:
            current += ("\n" if current else "") + line
    if current:
        chunks.append(current)
    return chunks


def fetch_document(item: dict[str, str], directory: Path, index: int, as_of: str) -> Document:
    url = item["url"]
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise SourceError(f"Only HTTP(S) source URLs are accepted: {url}")
    directory.mkdir(parents=True, exist_ok=True)
    try:
        response = requests.get(url, timeout=60, headers={"User-Agent": "LivingFin research/0.1"})
        response.raise_for_status()
    except requests.RequestException as exc:
        raise SourceError(f"Source fetch failed: {url}: {type(exc).__name__}") from exc
    payload = response.content
    if len(payload) > 30_000_000:
        raise SourceError(f"Source exceeds 30 MB limit: {url}")
    pdf = payload.startswith(b"%PDF-")
    if pdf:
        path = directory / f"source_{index}.pdf"
        path.write_bytes(payload)
        try:
            result = subprocess.run(["pdftotext", "-layout", "-", "-"], input=payload, capture_output=True, timeout=60, check=True)
        except (subprocess.SubprocessError, FileNotFoundError) as exc:
            raise SourceError("pdftotext is required for PDF sources") from exc
        pages = [page for page in result.stdout.decode("utf-8", "replace").split("\f") if page.strip()]
        media_type = "application/pdf"
    else:
        path = directory / f"source_{index}.html"
        path.write_bytes(payload)
        parser = _TextParser()
        parser.feed(response.text)
        if item.get("date_basis") != "manifest":
            valid_dates = [d for d in parser.dates if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d)]
            if not valid_dates:
                raise SourceError(f"No verifiable publication date: {url}")
            published = min(valid_dates)
            if not within_cutoff(published, as_of):
                raise SourceError(f"Page after as-of date: {url}")
            item = {**item, "published_at": published, "date_basis": "page_metadata"}
        pages = ["".join(parser.parts)]
        media_type = "text/html"
    if not pages:
        raise SourceError(f"No extractable text: {url}")
    return Document(
        title=item["title"], url=url, publisher=item["publisher"],
        published_at=item["published_at"], date_basis=item.get("date_basis", "manifest"),
        media_type=media_type, pages=pages, local_path=str(path),
    )


def document_chunks(doc: Document) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for page_number, page in enumerate(doc.pages, start=1):
        for chunk_number, text in enumerate(_chunks(page), start=1):
            result.append({"page": page_number, "part": chunk_number, "text": text})
    return result
