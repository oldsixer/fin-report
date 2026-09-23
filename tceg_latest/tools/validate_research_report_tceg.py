#!/usr/bin/env python3
"""Validate a research-report TCEG without trusting its extraction model."""

from __future__ import annotations

import argparse
import re
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from research_report_tceg_core import (
    SCHEMA_VERSION, compute_state_hash, dump_json, load_json, normalize_text,
    sha256_file, sha256_text,
)


ARGUMENT_TYPES = {"SUPPORTS", "CONTRADICTS", "CAUSES", "AFFECTS", "DEPENDS_ON"}
NODE_TYPES = {"Entity", "Metric", "Period", "DataPoint", "Claim", "Event", "ReasoningStep", "Assumption"}
EDGE_TYPES = {
    "EVIDENCED_BY", "ABOUT", "MEASURES", "VALID_DURING", "HAS_DATA",
    "SUPPORTS", "CONTRADICTS", "CAUSES", "AFFECTS", "DEPENDS_ON",
    "PREMISE_OF", "CONCLUDES", "ASSUMES", "SAME_AS",
}


def issue(code: str, message: str, object_id: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"code": code, "message": message}
    if object_id:
        result["object_id"] = object_id
    return result


def validate(graph: dict[str, Any], schema_path: str | Path | None = None) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []

    def check(name: str, condition: bool, detail: str, object_id: str | None = None) -> None:
        checks.append({"name": name, "status": "PASS" if condition else "FAIL", "detail": detail})
        if not condition:
            errors.append(issue(name, detail, object_id))

    check("SCHEMA_VERSION", graph.get("schema_version") == SCHEMA_VERSION, str(graph.get("schema_version")))
    required = {
        "schema_version", "graph_id", "state_hash", "document", "source_objects",
        "nodes", "edges", "extraction_run", "coverage_manifest", "rejected_candidates",
    }
    check("ROOT_FIELDS", required <= set(graph), f"missing={sorted(required - set(graph))}")
    if schema_path:
        schema = load_json(schema_path)
        check("SCHEMA_DOCUMENT_VERSION", schema.get("properties", {}).get("schema_version", {}).get("const") == SCHEMA_VERSION, str(schema_path))

    check("STATE_HASH", graph.get("state_hash") == compute_state_hash(graph), "canonical semantic payload hash")
    document = graph.get("document") or {}
    document_id = document.get("id")
    source_path = Path(document.get("local_path", ""))
    check("SOURCE_FILE_EXISTS", source_path.is_file(), str(source_path), document_id)
    if source_path.is_file():
        check("SOURCE_FILE_HASH", sha256_file(source_path) == document.get("sha256"), str(source_path), document_id)

    source_objects = graph.get("source_objects") or []
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    sources = {item.get("id"): item for item in source_objects if item.get("id")}
    node_by_id = {item.get("id"): item for item in nodes if item.get("id")}
    edge_by_id = {item.get("id"): item for item in edges if item.get("id")}

    all_ids = [document_id] + [item.get("id") for item in source_objects + nodes + edges]
    duplicate_ids = [item for item, count in Counter(all_ids).items() if item and count > 1]
    check("UNIQUE_IDS", not duplicate_ids, f"duplicates={duplicate_ids[:10]}")
    check("SOURCE_IDS", len(sources) == len(source_objects), "all source objects have IDs")
    check("NODE_IDS", len(node_by_id) == len(nodes), "all nodes have IDs")
    check("EDGE_IDS", len(edge_by_id) == len(edges), "all edges have IDs")

    status_counts = Counter()
    for source_id, source in sources.items():
        if source.get("document_id") != document_id:
            errors.append(issue("SOURCE_DOCUMENT", "wrong document_id", source_id))
        if sha256_text(source.get("raw_text", "")) != source.get("sha256"):
            errors.append(issue("SOURCE_HASH", "raw_text hash mismatch", source_id))
        status = source.get("processing_status")
        status_counts[status] += 1
        if status not in {"EXTRACTED", "NO_CLAIM", "OPAQUE", "NEEDS_REVIEW", "ERROR"}:
            errors.append(issue("SOURCE_STATUS", f"unknown status {status}", source_id))
        if status == "ERROR":
            errors.append(issue("SOURCE_ERROR", "source object extraction failed", source_id))

    semantic_nodes = []
    active_evidence_edges: dict[str, set[str]] = defaultdict(set)
    edge_keys: set[tuple[str, str, str]] = set()
    incoming_arguments: Counter[str] = Counter()
    argument_adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        edge_id = edge.get("id")
        edge_type = edge.get("edge_type")
        source_id = edge.get("source_id")
        target_id = edge.get("target_id")
        if edge_type not in EDGE_TYPES:
            errors.append(issue("EDGE_TYPE", str(edge_type), edge_id))
        if source_id not in node_by_id:
            errors.append(issue("EDGE_SOURCE", f"unknown node {source_id}", edge_id))
        if edge_type == "EVIDENCED_BY":
            if target_id not in sources:
                errors.append(issue("EVIDENCE_TARGET", f"unknown source object {target_id}", edge_id))
            active_evidence_edges[source_id].add(target_id)
        elif target_id not in node_by_id:
            errors.append(issue("EDGE_TARGET", f"unknown node {target_id}", edge_id))
        key = (str(edge_type), str(source_id), str(target_id))
        if key in edge_keys:
            errors.append(issue("DUPLICATE_EDGE", str(key), edge_id))
        edge_keys.add(key)
        if edge_type in ARGUMENT_TYPES and edge.get("status") == "active":
            incoming_arguments[target_id] += 1
            argument_adjacency[source_id].add(target_id)
            if edge.get("assertion_level") == "INFERRED":
                verification = edge.get("verification") or {}
                if verification.get("verdict") != "accept" or float(verification.get("confidence") or 0.0) < 0.65:
                    errors.append(issue("UNVERIFIED_INFERRED_EDGE", "active inferred relation lacks an accepting independent verdict", edge_id))
            if edge.get("assertion_level") == "EXPLICIT" and not edge.get("evidence"):
                errors.append(issue("EXPLICIT_RELATION_EVIDENCE", "explicit argument relation requires evidence", edge_id))

    def validate_evidence(node: dict[str, Any]) -> None:
        node_id = node["id"]
        evidence_ids: set[str] = set()
        for evidence in node.get("evidence") or []:
            source_id = evidence.get("source_object_id")
            quote = normalize_text(str(evidence.get("quote", "")))
            evidence_ids.add(source_id)
            source = sources.get(source_id)
            if not source:
                errors.append(issue("NODE_EVIDENCE_REF", f"unknown source {source_id}", node_id))
                continue
            if evidence.get("quote_sha256") != sha256_text(quote):
                errors.append(issue("EVIDENCE_QUOTE_HASH", "quote hash mismatch", node_id))
            source_text = source.get("normalized_text", "")
            match_mode = evidence.get("match_mode", "exact")
            if match_mode == "exact":
                matched = quote in source_text
            elif match_mode == "whitespace_normalized":
                matched = re.sub(r"\s+", "", quote) in re.sub(r"\s+", "", source_text)
            else:
                matched = False
            if not matched:
                errors.append(issue("EVIDENCE_QUOTE", "quote does not match source under declared match_mode", node_id))
        if evidence_ids != active_evidence_edges.get(node_id, set()):
            errors.append(issue("EVIDENCE_EDGE_PARITY", f"node={sorted(evidence_ids)} edge={sorted(active_evidence_edges.get(node_id, set()))}", node_id))

    for node_id, node in node_by_id.items():
        node_type = node.get("node_type")
        if node_type not in NODE_TYPES:
            errors.append(issue("NODE_TYPE", str(node_type), node_id))
            continue
        if not str(node.get("label", "")).strip():
            errors.append(issue("NODE_LABEL", "empty label", node_id))
        if node_type in {"Claim", "Event", "DataPoint"}:
            semantic_nodes.append(node)
            if node.get("assertion_level") == "EXPLICIT" and not node.get("evidence"):
                errors.append(issue("EXPLICIT_NODE_EVIDENCE", "explicit semantic node requires evidence", node_id))
            validate_evidence(node)
        if node_type == "DataPoint":
            for ref_field, expected_type in (("subject_ref", "Entity"), ("metric_ref", "Metric"), ("period_ref", "Period")):
                ref = node.get(ref_field)
                if not ref or node_by_id.get(ref, {}).get("node_type") != expected_type:
                    errors.append(issue("DATA_CONTEXT", f"{ref_field} must reference {expected_type}", node_id))
            value = node.get("value") or {}
            kind = value.get("kind")
            try:
                if kind == "scalar":
                    Decimal(value["normalized_decimal"])
                elif kind == "range":
                    low = Decimal(value["range_low"])
                    high = Decimal(value["range_high"])
                    if low > high:
                        errors.append(issue("DATA_RANGE", "range_low exceeds range_high", node_id))
                elif kind != "text":
                    errors.append(issue("DATA_VALUE_KIND", str(kind), node_id))
                if value.get("scale") is not None:
                    Decimal(value["scale"])
            except (InvalidOperation, KeyError, TypeError):
                errors.append(issue("DATA_DECIMAL", "invalid normalized value", node_id))
            raw = str(value.get("raw", ""))
            glyphs = re.findall(r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?", raw)
            evidence_text = " ".join(item.get("quote", "") for item in node.get("evidence", []))
            if any(glyph.replace(" ", "") not in evidence_text.replace(" ", "") for glyph in glyphs):
                errors.append(issue("DATA_RAW_EVIDENCE", "raw numeric glyph is absent from evidence", node_id))
        if node_type == "ReasoningStep":
            premises = node.get("premise_node_ids") or []
            conclusions = node.get("conclusion_claim_ids") or []
            if not premises or not conclusions:
                errors.append(issue("REASONING_SHAPE", "reasoning step needs premise and conclusion", node_id))
            for premise in premises:
                if premise not in node_by_id or ("PREMISE_OF", premise, node_id) not in edge_keys:
                    errors.append(issue("REASONING_PREMISE", str(premise), node_id))
            for conclusion in conclusions:
                if node_by_id.get(conclusion, {}).get("node_type") != "Claim" or ("CONCLUDES", node_id, conclusion) not in edge_keys:
                    errors.append(issue("REASONING_CONCLUSION", str(conclusion), node_id))

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> bool:
        if node_id in visiting:
            return False
        if node_id in visited:
            return True
        visiting.add(node_id)
        valid = all(visit(target) for target in argument_adjacency.get(node_id, set()))
        visiting.remove(node_id)
        visited.add(node_id)
        return valid

    argument_nodes = set(argument_adjacency) | {target for values in argument_adjacency.values() for target in values}
    check("ARGUMENT_DAG", all(visit(node_id) for node_id in argument_nodes), "argument relations are acyclic")

    for node in semantic_nodes:
        if node.get("node_type") != "Claim":
            continue
        if node.get("importance") == "core" and node.get("claim_role") in {"recommendation", "valuation", "forecast", "interpretation"}:
            if not incoming_arguments[node["id"]]:
                warnings.append(issue("CORE_CLAIM_WITHOUT_ARGUMENT", "core analytical claim has no incoming argument relation", node["id"]))

    coverage = graph.get("coverage_manifest") or {}
    expected_status_counts = dict(sorted(status_counts.items()))
    check("COVERAGE_STATUS_COUNTS", coverage.get("source_object_status_counts") == expected_status_counts, f"expected={expected_status_counts}")
    check("COVERAGE_TERMINAL", coverage.get("terminal_source_objects") == len(source_objects), f"total={len(source_objects)}")
    evidenced_count = sum(1 for node in semantic_nodes if node.get("evidence"))
    expected_evidence_coverage = round(evidenced_count / len(semantic_nodes), 6) if semantic_nodes else 1.0
    check("COVERAGE_EVIDENCE", coverage.get("semantic_evidence_coverage") == expected_evidence_coverage, str(expected_evidence_coverage))

    node_counts = Counter(node.get("node_type") for node in nodes)
    edge_counts = Counter(edge.get("edge_type") for edge in edges)
    result = {
        "status": "PASS" if not errors else "FAIL",
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
        "metrics": {
            "source_objects": len(source_objects),
            "nodes": len(nodes), "edges": len(edges),
            "node_type_counts": dict(sorted(node_counts.items())),
            "edge_type_counts": dict(sorted(edge_counts.items())),
            "semantic_nodes": len(semantic_nodes),
            "semantic_evidence_coverage": expected_evidence_coverage,
            "core_claims_without_argument": sum(1 for item in warnings if item["code"] == "CORE_CLAIM_WITHOUT_ARGUMENT"),
            "rejected_candidates": len(graph.get("rejected_candidates") or []),
        },
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("graph", type=Path)
    parser.add_argument("--schema", type=Path, default=Path("schemas/research_report_tceg.schema.json"))
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    graph = load_json(args.graph)
    result = validate(graph, args.schema)
    output = args.output or args.graph.with_name("validation.json")
    dump_json(output, result)
    print(f"{result['status']}: {len(result['errors'])} errors, {len(result['warnings'])} warnings -> {output}")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
