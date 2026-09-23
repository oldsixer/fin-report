#!/usr/bin/env python3
"""Shared primitives for the research-report TCEG extraction profile."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from copy import deepcopy
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "research-report-tceg-0.1"


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dump_json(path: str | Path, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def canonical_state_payload(graph: dict[str, Any]) -> dict[str, Any]:
    """Return only source and semantic state, excluding run diagnostics."""
    return {
        "schema_version": graph.get("schema_version"),
        "graph_id": graph.get("graph_id"),
        "document": deepcopy(graph.get("document")),
        "source_objects": deepcopy(graph.get("source_objects", [])),
        "nodes": deepcopy(graph.get("nodes", [])),
        "edges": deepcopy(graph.get("edges", [])),
    }


def compute_state_hash(graph: dict[str, Any]) -> str:
    payload = json.dumps(
        canonical_state_payload(graph), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    )
    return sha256_text(payload)


def refresh_state_hash(graph: dict[str, Any]) -> str:
    graph["state_hash"] = compute_state_hash(graph)
    return graph["state_hash"]


_CJK = r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"


def normalize_text(text: str) -> str:
    """Repair common PDF spacing while retaining line boundaries."""
    value = text.replace("\u00a0", " ").replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+", " ", value)
    previous = None
    while previous != value:
        previous = value
        value = re.sub(rf"([{_CJK}])[ \t]+([{_CJK}])", r"\1\2", value)
    value = re.sub(rf"([{_CJK}])[ \t]+([，。；：、！？）】])", r"\1\2", value)
    value = re.sub(rf"([（【])[ \t]+([{_CJK}])", r"\1\2", value)
    value = re.sub(r" *\n *", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def extract_pdf_pages(path: str | Path) -> list[str]:
    completed = subprocess.run(
        ["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"],
        check=True, capture_output=True,
    )
    text = completed.stdout.decode("utf-8", errors="replace")
    pages = text.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    return pages


def _object_type(text: str) -> str:
    normalized = normalize_text(text)
    if any(marker in normalized for marker in ("法律主体声明", "版权声明", "分析师声明", "评级说明")):
        return "legal"
    if re.match(r"^(?:图表|图)\s*\d+", normalized):
        return "figure_caption"
    lines = [line for line in normalized.splitlines() if line.strip()]
    numeric_lines = sum(
        1 for line in lines
        if len(re.findall(r"[-+]?\d[\d,.]*(?:%|倍|元|亿|万)?", line)) >= 2
    )
    if len(lines) >= 2 and numeric_lines >= max(1, len(lines) // 3):
        return "table_like"
    return "paragraph"


def _split_large_block(lines: list[str], max_chars: int) -> list[list[str]]:
    result: list[list[str]] = []
    current: list[str] = []
    current_len = 0
    for line in lines:
        extra = len(line) + (1 if current else 0)
        if current and current_len + extra > max_chars:
            result.append(current)
            current = []
            current_len = 0
        current.append(line)
        current_len += len(line) + (1 if current_len else 0)
    if current:
        result.append(current)
    return result


def build_source_objects(
    document_id: str, pages: list[str], max_block_chars: int = 2800,
) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    sequence = 0
    for page_no, page in enumerate(pages, start=1):
        raw_groups = re.split(r"\n\s*\n", page)
        page_block = 0
        page_cursor = 0
        for raw_group in raw_groups:
            if not raw_group.strip():
                continue
            lines = [line.rstrip() for line in raw_group.splitlines() if line.strip()]
            for part in _split_large_block(lines, max_block_chars):
                raw = "\n".join(part).strip()
                normalized = normalize_text(raw)
                if not normalized:
                    continue
                page_block += 1
                sequence += 1
                start = page.find(raw.splitlines()[0], page_cursor)
                if start < 0:
                    start = None
                    end = None
                else:
                    end = start + len(raw)
                    page_cursor = end
                object_id = f"SO_P{page_no:03d}_B{page_block:03d}"
                objects.append({
                    "id": object_id,
                    "document_id": document_id,
                    "object_type": _object_type(normalized),
                    "sequence": sequence,
                    "raw_text": raw,
                    "normalized_text": normalized,
                    "sha256": sha256_text(raw),
                    "locator": {
                        "page": page_no, "block": page_block,
                        "char_start": start, "char_end": end,
                    },
                    "processing_status": "NEEDS_REVIEW",
                    "candidate_count": 0,
                    "irrelevant_reason": None,
                    "metadata": {"extraction_method": "pdftotext-layout"},
                })
    return objects


def pack_source_chunks(
    source_objects: list[dict[str, Any]], max_chars: int = 9000,
) -> list[list[dict[str, Any]]]:
    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_len = 0
    for obj in source_objects:
        rendered_len = len(obj["normalized_text"]) + 100
        repeats_source = any(item["id"] == obj["id"] for item in current)
        if current and (current_len + rendered_len > max_chars or repeats_source):
            chunks.append(current)
            current = []
            current_len = 0
        current.append(obj)
        current_len += rendered_len
    if current:
        chunks.append(current)
    return chunks


def render_source_chunk(chunk: list[dict[str, Any]]) -> str:
    return "\n\n".join(
        f"[SOURCE_OBJECT id={obj['id']} page={obj['locator']['page']} type={obj['object_type']}]\n"
        f"{obj['normalized_text']}"
        for obj in chunk
    )


def load_dotenv(path: str | Path) -> None:
    env_path = Path(path)
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"").strip("'")
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            os.environ.setdefault(key, value)


def parse_json_content(content: str) -> Any:
    value = content.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s*```$", "", value)
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        start = value.find("{")
        end = value.rfind("}")
        if start >= 0 and end > start:
            return json.loads(value[start:end + 1])
        raise


class LLMClient:
    """Small OpenAI-compatible JSON client with auditable, secret-free traces."""

    def __init__(self, base_url: str, api_key: str, model: str, timeout: int = 180):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.calls: list[dict[str, Any]] = []

    def complete_json(
        self, purpose: str, system: str, user: str, max_tokens: int = 8000,
        retries: int = 2,
    ) -> Any:
        body = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            started = time.monotonic()
            request = urllib.request.Request(
                f"{self.base_url}/chat/completions", data=payload, method="POST",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read().decode("utf-8")
                envelope = json.loads(raw)
                content = envelope["choices"][0]["message"]["content"]
                json_repair_applied = False
                try:
                    parsed = parse_json_content(content)
                except json.JSONDecodeError:
                    try:
                        from json_repair import repair_json
                    except ImportError as exc:
                        raise RuntimeError(
                            "model returned malformed JSON and json-repair is not installed"
                        ) from exc
                    repair_source = content.strip()
                    if repair_source.startswith("```"):
                        repair_source = re.sub(r"^```(?:json)?\s*", "", repair_source, flags=re.IGNORECASE)
                        repair_source = re.sub(r"\s*```$", "", repair_source)
                    repaired = repair_json(repair_source)
                    parsed = json.loads(repaired)
                    json_repair_applied = True
                self.calls.append({
                    "id": f"CALL_{len(self.calls) + 1:03d}",
                    "purpose": purpose,
                    "model": envelope.get("model", self.model),
                    "attempt": attempt + 1,
                    "duration_seconds": round(time.monotonic() - started, 3),
                    "prompt_sha256": sha256_text(system + "\n" + user),
                    "response_sha256": sha256_text(content),
                    "finish_reason": envelope.get("choices", [{}])[0].get("finish_reason"),
                    "json_repair_applied": json_repair_applied,
                    "usage": envelope.get("usage", {}),
                    "status": "success",
                })
                return parsed
            except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt < retries:
                    time.sleep(1.5 * (attempt + 1))
        self.calls.append({
            "id": f"CALL_{len(self.calls) + 1:03d}",
            "purpose": purpose,
            "model": self.model,
            "attempt": retries + 1,
            "prompt_sha256": sha256_text(system + "\n" + user),
            "status": "error",
            "error": type(last_error).__name__ if last_error else "unknown",
        })
        raise RuntimeError(f"LLM call failed for {purpose}: {last_error}")


def stable_id(prefix: str, *parts: Any) -> str:
    material = "\x1f".join(str(part).strip() for part in parts)
    return f"{prefix}_{sha256_text(material)[:16].upper()}"


def unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))
