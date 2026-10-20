#!/usr/bin/env python3
"""Extract readable messages from a public ChatGPT share page.

The public page embeds a devalue-style flattened JSON payload.  This utility
decodes the subset used by shared conversations and emits either Markdown or
JSON.  It intentionally keeps source retrieval separate from research claims:
shared-chat content is project context, not bibliographic evidence.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any


ENQUEUE_RE = re.compile(
    r"window\.__reactRouterContext\.streamController\.enqueue\((.*?)\);",
    re.DOTALL,
)


def fetch(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (research-context-extractor)"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def embedded_flat_payload(page: str) -> list[Any]:
    chunks: list[str] = []
    for match in ENQUEUE_RE.finditer(page):
        try:
            chunk = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(chunk, str):
            chunks.append(chunk)

    for chunk in chunks:
        try:
            payload = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, list) and payload:
            return payload
    raise ValueError("No flattened shared-conversation payload found")


class DevalueDecoder:
    """Decode the reference-array representation emitted by devalue."""

    def __init__(self, values: list[Any]) -> None:
        self.values = values
        self.cache: dict[int, Any] = {}

    def reference(self, value: Any) -> Any:
        if not isinstance(value, int) or isinstance(value, bool):
            return value
        if value >= 0:
            if value >= len(self.values):
                return value
            return self.hydrate(value)
        # Negative values are devalue sentinels. Only their JSON-safe meanings
        # are needed for shared-chat extraction.
        return {
            -1: None,
            -2: None,
            -3: math.nan,
            -4: math.inf,
            -5: None,
            -6: -0.0,
        }.get(value)

    def hydrate(self, index: int) -> Any:
        if index in self.cache:
            return self.cache[index]
        raw = self.values[index]

        if isinstance(raw, list):
            result: list[Any] = []
            self.cache[index] = result
            result.extend(self.reference(item) for item in raw)
            return result

        if isinstance(raw, dict):
            result_dict: dict[str, Any] = {}
            self.cache[index] = result_dict
            for encoded_key, encoded_value in raw.items():
                if encoded_key.startswith("_") and encoded_key[1:].isdigit():
                    key = self.hydrate(int(encoded_key[1:]))
                else:
                    key = encoded_key
                result_dict[str(key)] = self.reference(encoded_value)
            return result_dict

        self.cache[index] = raw
        return raw


def find_conversation(value: Any, seen: set[int] | None = None) -> dict[str, Any] | None:
    if seen is None:
        seen = set()
    if isinstance(value, (dict, list)):
        identity = id(value)
        if identity in seen:
            return None
        seen.add(identity)

    if isinstance(value, dict):
        if isinstance(value.get("linear_conversation"), list):
            return value
        for child in value.values():
            found = find_conversation(child, seen)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_conversation(child, seen)
            if found is not None:
                return found
    return None


def content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, dict):
        return ""

    parts = content.get("parts")
    if not isinstance(parts, list):
        parts = content.get("text")
        if isinstance(parts, str):
            return parts
        return ""

    rendered: list[str] = []
    for part in parts:
        if isinstance(part, str):
            rendered.append(part)
        elif isinstance(part, dict):
            text = part.get("text")
            if isinstance(text, str):
                rendered.append(text)
            elif part.get("content_type") == "image_asset_pointer":
                pointer = part.get("asset_pointer", "attachment")
                rendered.append(f"[Image attachment: {pointer}]")
    return "\n\n".join(piece for piece in rendered if piece).strip()


def messages(conversation: dict[str, Any]) -> list[dict[str, Any]]:
    extracted: list[dict[str, Any]] = []
    for node in conversation.get("linear_conversation", []):
        if not isinstance(node, dict):
            continue
        message = node.get("message")
        if not isinstance(message, dict):
            continue
        author = message.get("author")
        role = author.get("role", "unknown") if isinstance(author, dict) else "unknown"
        text = content_text(message.get("content"))
        if not text:
            continue
        extracted.append(
            {
                "id": message.get("id") or node.get("id"),
                "role": role,
                "create_time": message.get("create_time"),
                "text": text,
            }
        )
    return extracted


def render_markdown(url: str, conversation: dict[str, Any], items: list[dict[str, Any]]) -> str:
    title = conversation.get("title") or conversation.get("pageTitle") or "Shared ChatGPT conversation"
    lines = [
        f"# {title}",
        "",
        f"Source: {url}",
        "",
        "> Provenance note: this file archives user/assistant discussion as project context. "
        "It is not a verified scholarly source and must not be cited as evidence.",
        "",
    ]
    for number, item in enumerate(items, start=1):
        lines.extend(
            [
                f"## {number}. {str(item['role']).capitalize()}",
                "",
                item["text"],
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    page = fetch(args.url)
    decoded = DevalueDecoder(embedded_flat_payload(page)).hydrate(0)
    conversation = find_conversation(decoded)
    if conversation is None:
        raise ValueError("Decoded payload did not contain a conversation")
    items = messages(conversation)
    if not items:
        raise ValueError("Conversation contained no readable messages")

    if args.format == "json":
        output = json.dumps(
            {
                "source": args.url,
                "title": conversation.get("title"),
                "messages": items,
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n"
    else:
        output = render_markdown(args.url, conversation, items)

    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
