"""One physical graph with semantic and research-agenda projections."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")
EDGE_TYPES = {
    "CONTAINS": ("Source", "EvidenceUnit"),
    "ABOUT": ("Proposition", "Entity"),
    "GROUNDED_IN": ("Proposition", "EvidenceUnit"),
    "CALCULATED_FROM": ("Proposition", "Proposition"),
    "PREMISE_OF": ("Proposition", "Proposition"),
    "ANSWERS": ("Proposition", "Question"),
    "IN_SECTION": ("Question", "Section"),
    "SUBQUESTION_OF": ("Question", "Question"),
    "SUBSECTION_OF": ("Section", "Section"),
    "EXPRESSES": ("ReportSpan", "Proposition"),
}
PREFIX = {
    "Source": "S",
    "EvidenceUnit": "E",
    "Entity": "N",
    "Proposition": "P",
    "Question": "Q",
    "Section": "C",
    "ReportSpan": "R",
}
SEMANTIC_TYPES = {"Source", "EvidenceUnit", "Entity", "Proposition"}
AGENDA_TYPES = {"Section", "Question", "Proposition"}


def cutoff_exclusive(as_of: str) -> datetime:
    """A date means the end of that calendar day in Shanghai, exclusive."""
    day = date.fromisoformat(as_of)
    return datetime.combine(day + timedelta(days=1), time.min, SHANGHAI)


def ms_to_shanghai(ms: int | float) -> datetime:
    return datetime.fromtimestamp(float(ms) / 1000, timezone.utc).astimezone(SHANGHAI)


def within_cutoff(published_at: str, as_of: str) -> bool:
    return date.fromisoformat(published_at) < cutoff_exclusive(as_of).date()


def normalize_quote(value: str) -> str:
    return re.sub(r"\s+", "", value).replace("，", ",")


def quote_is_in(quote: str, context: str) -> bool:
    return bool(quote.strip()) and normalize_quote(quote) in normalize_quote(context)


def decimal_text(value: Any) -> str:
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError("Non-finite financial number")
    return format(number, "f")


def display_number(value: Any, unit: str) -> str:
    number = Decimal(str(value))
    if unit == "CNY":
        if abs(number) >= Decimal("100000000"):
            return f"{number / Decimal('100000000'):.2f}亿元"
        if abs(number) >= Decimal("10000"):
            return f"{number / Decimal('10000'):.2f}万元"
        return f"{number:.2f}元"
    if unit == "CNY/share":
        return f"{number:.2f}元/股"
    if unit == "%":
        return f"{number:.2f}%"
    return f"{number:f}{unit}"


@dataclass
class Graph:
    meta: dict[str, Any]
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    edges: list[dict[str, Any]] = field(default_factory=list)
    counters: dict[str, int] = field(default_factory=dict)

    def add(self, node_type: str, **data: Any) -> str:
        if node_type not in PREFIX:
            raise ValueError(f"Unknown node type: {node_type}")
        self.counters[node_type] = self.counters.get(node_type, 0) + 1
        node_id = f"{PREFIX[node_type]}{self.counters[node_type]}"
        self.nodes[node_id] = {"id": node_id, "type": node_type, **data}
        return node_id

    def link(self, source: str, relation: str, target: str, **data: Any) -> None:
        if relation not in EDGE_TYPES:
            raise ValueError(f"Unknown relation: {relation}")
        source_kind, target_kind = EDGE_TYPES[relation]
        if source not in self.nodes or target not in self.nodes:
            raise ValueError(f"Missing edge endpoint: {source} -> {target}")
        if (self.nodes[source]["type"], self.nodes[target]["type"]) != (source_kind, target_kind):
            raise ValueError(f"Invalid {relation} endpoints: {source}, {target}")
        edge = {"from": source, "type": relation, "to": target, **data}
        if edge not in self.edges:
            self.edges.append(edge)

    def outgoing(self, node_id: str, relation: str) -> list[str]:
        return [edge["to"] for edge in self.edges if edge["from"] == node_id and edge["type"] == relation]

    def incoming(self, node_id: str, relation: str) -> list[str]:
        return [edge["from"] for edge in self.edges if edge["to"] == node_id and edge["type"] == relation]

    def by_type(self, kind: str) -> list[dict[str, Any]]:
        return [node for node in self.nodes.values() if node["type"] == kind]

    def proposition_reportable(self, node_id: str, visited: set[str] | None = None) -> bool:
        visited = set() if visited is None else visited
        if node_id in visited:
            return False
        visited.add(node_id)
        node = self.nodes[node_id]
        if node["type"] != "Proposition" or node.get("status") != "reportable":
            return False
        kind = node.get("kind")
        if kind in {"fact", "attributed"}:
            return bool(self.outgoing(node_id, "GROUNDED_IN"))
        if kind == "computed":
            inputs = self.outgoing(node_id, "CALCULATED_FROM")
            return bool(node.get("formula")) and len(inputs) >= 2 and all(self.proposition_reportable(pid, visited.copy()) for pid in inputs)
        if kind in {"analysis", "forecast"}:
            premises = self.incoming(node_id, "PREMISE_OF")
            return node.get("review") == "accepted" and bool(premises) and all(self.proposition_reportable(pid, visited.copy()) for pid in premises)
        return False

    def validate(self) -> None:
        for edge in self.edges:
            expected = EDGE_TYPES.get(edge["type"])
            if expected is None or edge["from"] not in self.nodes or edge["to"] not in self.nodes:
                raise ValueError(f"Invalid edge: {edge}")
            actual = (self.nodes[edge["from"]]["type"], self.nodes[edge["to"]]["type"])
            if actual != expected:
                raise ValueError(f"Wrong endpoint types for {edge['type']}: {actual}")
        for node in self.by_type("Proposition"):
            if node.get("status") == "reportable" and not self.proposition_reportable(node["id"]):
                raise ValueError(f"Untraceable reportable proposition: {node['id']}")
        for span in self.by_type("ReportSpan"):
            claims = self.outgoing(span["id"], "EXPRESSES")
            if not claims or not all(self.proposition_reportable(pid) for pid in claims):
                raise ValueError(f"Report span without valid claim path: {span['id']}")

    def view(self, name: str) -> dict[str, Any]:
        kinds = SEMANTIC_TYPES if name == "semantic" else AGENDA_TYPES if name == "agenda" else None
        if kinds is None:
            raise ValueError(f"Unknown view: {name}")
        nodes = [node for node in self.nodes.values() if node["type"] in kinds]
        ids = {node["id"] for node in nodes}
        return {"nodes": nodes, "edges": [e for e in self.edges if e["from"] in ids and e["to"] in ids]}

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {"meta": self.meta, "nodes": list(self.nodes.values()), "edges": self.edges}
