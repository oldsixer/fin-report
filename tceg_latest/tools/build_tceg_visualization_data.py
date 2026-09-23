#!/usr/bin/env python3
"""Build a browser-friendly, self-contained data bundle for the TCEG viewer."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXPERIMENT = ROOT / "experiments" / "research_report_tceg_jiangbolong"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def compact_node(node: dict[str, Any]) -> dict[str, Any]:
    keep = {
        "id",
        "node_type",
        "label",
        "entity_type",
        "canonical_name",
        "normalized_label",
        "claim_role",
        "modality",
        "polarity",
        "importance",
        "assertion_level",
        "subject_ref",
        "predicate",
        "object_text",
        "metric_ref",
        "period_ref",
        "qualifier",
        "value",
        "category",
        "reasoning_method",
        "premise_node_ids",
        "conclusion_claim_ids",
        "rationale",
        "verification",
        "status",
        "evidence",
    }
    return {key: value for key, value in node.items() if key in keep and value is not None}


def compact_edge(edge: dict[str, Any]) -> dict[str, Any]:
    keep = {
        "id",
        "edge_type",
        "source_id",
        "target_id",
        "assertion_level",
        "confidence",
        "status",
        "rationale",
        "evidence",
        "extraction_origin",
        "verification",
    }
    return {key: value for key, value in edge.items() if key in keep and value is not None}


def build_payload(experiment: Path) -> dict[str, Any]:
    """Read current experiment artifacts and return the frontend payload."""
    graph = read_json(experiment / "tceg.json")
    validation = read_json(experiment / "validation.json")
    evaluation = read_json(experiment / "core_evaluation.json")

    benchmark_ids: set[str] = set()
    benchmark_lookup: dict[str, list[dict[str, str]]] = defaultdict(list)
    for group in ("semantic_items", "data_items", "relation_items"):
        for item in evaluation.get(group, []):
            ids = item.get("matching_node_ids", []) + item.get("matching_edge_ids", [])
            for object_id in ids:
                benchmark_ids.add(object_id)
                benchmark_lookup[object_id].append(
                    {
                        "id": item["id"],
                        "description": item["description"],
                        "status": item["status"],
                    }
                )

    nodes = [compact_node(node) for node in graph["nodes"]]
    edges = [compact_edge(edge) for edge in graph["edges"]]
    for item in nodes:
        if item["id"] in benchmark_lookup:
            item["benchmark_matches"] = benchmark_lookup[item["id"]]
    for item in edges:
        if item["id"] in benchmark_lookup:
            item["benchmark_matches"] = benchmark_lookup[item["id"]]

    source_objects = []
    for source in graph["source_objects"]:
        source_objects.append(
            {
                "id": source["id"],
                "object_type": source.get("object_type"),
                "sequence": source.get("sequence"),
                "text": source.get("normalized_text") or source.get("raw_text", ""),
                "raw_text": source.get("raw_text", ""),
                "page": source.get("locator", {}).get("page"),
                "block": source.get("locator", {}).get("block"),
                "processing_status": source.get("processing_status"),
                "candidate_count": source.get("candidate_count", 0),
                "irrelevant_reason": source.get("irrelevant_reason"),
            }
        )

    warning_ids = {warning.get("object_id") for warning in validation.get("warnings", [])}
    return {
        "generated_from": str(experiment / "tceg.json"),
        "document": graph["document"],
        "graph": {
            "schema_version": graph.get("schema_version"),
            "graph_id": graph.get("graph_id"),
            "state_hash": graph.get("state_hash"),
        },
        "run": {
            "finished_at": graph.get("extraction_run", {}).get("finished_at"),
            "model": graph.get("extraction_run", {}).get("model"),
            "verification_model": graph.get("extraction_run", {}).get("verification_model"),
            "deterministic_table_points_created": graph.get("extraction_run", {}).get(
                "deterministic_table_points_created", 0
            ),
            "deterministic_capacity_points_created": graph.get("extraction_run", {}).get(
                "deterministic_capacity_points_created", 0
            ),
        },
        "coverage": graph.get("coverage_manifest", {}),
        "validation": {
            "status": validation.get("status"),
            "error_count": len(validation.get("errors", [])),
            "warning_count": len(validation.get("warnings", [])),
            "warnings": validation.get("warnings", []),
            "metrics": validation.get("metrics", {}),
        },
        "evaluation": {
            "benchmark": evaluation.get("benchmark"),
            "summary": evaluation.get("summary", {}),
            "interpretation": evaluation.get("interpretation"),
        },
        "counts": {
            "nodes": len(nodes),
            "edges": len(edges),
            "sources": len(source_objects),
            "node_types": dict(Counter(node["node_type"] for node in nodes)),
            "edge_types": dict(Counter(edge["edge_type"] for edge in edges)),
        },
        "warning_node_ids": sorted(object_id for object_id in warning_ids if object_id),
        "benchmark_object_ids": sorted(benchmark_ids),
        "source_objects": source_objects,
        "nodes": nodes,
        "edges": edges,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", type=Path, default=DEFAULT_EXPERIMENT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    experiment = args.experiment.resolve()
    output = (args.output or experiment / "visualization" / "tceg_visualization_data.js").resolve()
    payload = build_payload(experiment)

    output.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    output.write_text(
        "/* Generated by tools/build_tceg_visualization_data.py; do not edit manually. */\n"
        f"window.TCEG_DATA={serialized};\n",
        encoding="utf-8",
    )
    print(f"wrote {output} ({output.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
