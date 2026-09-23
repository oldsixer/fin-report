#!/usr/bin/env python3
"""Evaluate a research-report TCEG against a manually curated core inventory."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from research_report_tceg_core import dump_json, load_json


def compact(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def node_text(node: dict[str, Any], node_by_id: dict[str, dict[str, Any]]) -> str:
    fields = [node.get("label"), node.get("object_text"), node.get("predicate")]
    for key in ("subject_ref", "metric_ref", "period_ref"):
        fields.append(node_by_id.get(node.get(key), {}).get("label"))
    return compact(" ".join(str(item or "") for item in fields))


def matches_node(
    node: dict[str, Any], spec: dict[str, Any], node_by_id: dict[str, dict[str, Any]],
) -> bool:
    if spec.get("node_types") and node.get("node_type") not in set(spec["node_types"]):
        return False
    text = node_text(node, node_by_id)
    if any(compact(term) not in text for term in spec.get("all_terms", [])):
        return False
    for group in spec.get("any_term_groups", []):
        if not any(compact(term) in text for term in group):
            return False
    return True


def matches_data(
    node: dict[str, Any], spec: dict[str, Any], node_by_id: dict[str, dict[str, Any]],
) -> bool:
    if node.get("node_type") != "DataPoint":
        return False
    subject = compact(node_by_id.get(node.get("subject_ref"), {}).get("label"))
    metric = compact(node_by_id.get(node.get("metric_ref"), {}).get("label"))
    period = compact(node_by_id.get(node.get("period_ref"), {}).get("label"))
    value = node.get("value") or {}
    if spec.get("subject_terms") and any(compact(term) not in subject for term in spec["subject_terms"]):
        return False
    if spec.get("subject_any") and not any(compact(term) in subject for term in spec["subject_any"]):
        return False
    if spec.get("metric_any") and not any(compact(term) == metric for term in spec["metric_any"]):
        return False
    if spec.get("metric_terms") and any(compact(term) not in metric for term in spec["metric_terms"]):
        return False
    if spec.get("period_any") and period not in {compact(item) for item in spec["period_any"]}:
        return False
    raw = compact(value.get("raw"))
    if spec.get("raw_any") and raw not in {compact(item) for item in spec["raw_any"]}:
        return False
    if spec.get("scale") is not None and str(value.get("scale")) != str(spec["scale"]):
        return False
    return True


def score_items(
    specs: list[dict[str, Any]], nodes: list[dict[str, Any]], node_by_id: dict[str, dict[str, Any]],
    data: bool = False,
) -> list[dict[str, Any]]:
    output = []
    matcher = matches_data if data else matches_node
    for spec in specs:
        matches = [node["id"] for node in nodes if matcher(node, spec, node_by_id)]
        output.append({
            "id": spec["id"], "description": spec["description"],
            "status": "PASS" if matches else "MISS", "matching_node_ids": matches,
        })
    return output


def score_relations(
    specs: list[dict[str, Any]], nodes: list[dict[str, Any]], edges: list[dict[str, Any]],
    node_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    output = []
    for spec in specs:
        source_ids = {
            node["id"] for node in nodes if matches_node(node, spec["source"], node_by_id)
        }
        target_ids = {
            node["id"] for node in nodes if matches_node(node, spec["target"], node_by_id)
        }
        allowed = set(spec["edge_types"])
        matches = [
            edge["id"] for edge in edges
            if edge.get("source_id") in source_ids
            and edge.get("target_id") in target_ids
            and edge.get("edge_type") in allowed
            and edge.get("status") == "active"
        ]
        output.append({
            "id": spec["id"], "description": spec["description"],
            "status": "PASS" if matches else "MISS", "matching_edge_ids": matches,
        })
    return output


def category_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    passed = sum(item["status"] == "PASS" for item in items)
    total = len(items)
    return {"passed": passed, "total": total, "recall": round(passed / total, 6) if total else 1.0}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("graph", type=Path)
    parser.add_argument("gold", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args()

    graph = load_json(args.graph)
    gold = load_json(args.gold)
    nodes = graph["nodes"]
    node_by_id = {node["id"]: node for node in nodes}
    semantic = score_items(gold.get("semantic_items", []), nodes, node_by_id)
    data = score_items(gold.get("data_items", []), nodes, node_by_id, data=True)
    relations = score_relations(gold.get("relation_items", []), nodes, graph["edges"], node_by_id)
    result = {
        "benchmark": gold.get("benchmark"),
        "graph_state_hash": graph.get("state_hash"),
        "summary": {
            "semantic": category_summary(semantic),
            "data": category_summary(data),
            "relations": category_summary(relations),
        },
        "semantic_items": semantic,
        "data_items": data,
        "relation_items": relations,
        "interpretation": "Manual core recall; it does not estimate precision or exhaustive full-report recall.",
    }
    dump_json(args.output, result)
    if args.markdown:
        lines = ["# TCEG 核心语义评估", ""]
        for name, summary in result["summary"].items():
            lines.append(f"- {name}: {summary['passed']}/{summary['total']} ({summary['recall']:.1%})")
        for title, key in (("语义缺失", "semantic_items"), ("数字缺失", "data_items"), ("关系缺失", "relation_items")):
            lines.extend(["", f"## {title}", ""])
            missed = [item for item in result[key] if item["status"] == "MISS"]
            lines.extend(f"- `{item['id']}` {item['description']}" for item in missed)
            if not missed:
                lines.append("- 无")
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
