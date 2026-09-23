#!/usr/bin/env python3
"""Dependency-free regression tests for research-report TCEG invariants."""

from __future__ import annotations

import copy
import tempfile
from pathlib import Path

from extract_research_report_tceg import (
    GraphBuilder, canonical_evidence, extract_capacity_table_data,
    parse_numeric_confidence,
)
from research_report_tceg_core import refresh_state_hash, sha256_file, sha256_text, stable_id
from validate_research_report_tceg import validate


def fixture(source_path: Path) -> dict:
    text = "公司预计2026年营业收入增长20%，因此给予买入评级。"
    source_id = "SO_P001_B001"
    entity_id = "ENT_TEST"
    metric_id = "MET_REVENUE_GROWTH"
    period_id = "PER_2026E"
    data_id = "DATA_GROWTH"
    claim_forecast = "CLM_FORECAST"
    claim_rating = "CLM_RATING"
    step_id = "STEP_SUPPORT"
    quote_hash = sha256_text(text)
    graph = {
        "schema_version": "research-report-tceg-0.1",
        "graph_id": "TCEG_TEST",
        "state_hash": "0" * 64,
        "document": {
            "id": "DOC_TEST", "title": "test", "source_type": "research_text",
            "local_path": str(source_path), "sha256": sha256_file(source_path),
        },
        "source_objects": [{
            "id": source_id, "document_id": "DOC_TEST", "object_type": "paragraph",
            "sequence": 1, "raw_text": text, "normalized_text": text,
            "sha256": quote_hash, "locator": {"page": 1, "block": 1, "char_start": 0, "char_end": len(text)},
            "processing_status": "EXTRACTED", "candidate_count": 3,
            "irrelevant_reason": None, "metadata": {},
        }],
        "nodes": [
            {"id": entity_id, "node_type": "Entity", "label": "公司", "status": "active"},
            {"id": metric_id, "node_type": "Metric", "label": "营业收入增长率", "status": "active"},
            {"id": period_id, "node_type": "Period", "label": "2026E", "status": "active"},
            {
                "id": data_id, "node_type": "DataPoint", "label": "2026E营业收入增长20%", "status": "active",
                "subject_ref": entity_id, "metric_ref": metric_id, "period_ref": period_id,
                "assertion_level": "EXPLICIT", "qualifier": "forecast",
                "value": {"kind": "scalar", "raw": "20%", "normalized_decimal": "20", "range_low": None, "range_high": None, "unit": "percent", "currency": None, "scale": "0.01", "dimensions": {}},
                "evidence": [{"source_object_id": source_id, "quote": text, "quote_sha256": quote_hash, "match_mode": "exact"}],
            },
            {
                "id": claim_forecast, "node_type": "Claim", "label": "公司预计2026年营业收入增长20%", "status": "active",
                "claim_role": "forecast", "modality": "forecast", "importance": "core", "assertion_level": "EXPLICIT",
                "evidence": [{"source_object_id": source_id, "quote": text, "quote_sha256": quote_hash, "match_mode": "exact"}],
            },
            {
                "id": claim_rating, "node_type": "Claim", "label": "给予买入评级", "status": "active",
                "claim_role": "recommendation", "modality": "recommendation", "importance": "core", "assertion_level": "EXPLICIT",
                "evidence": [{"source_object_id": source_id, "quote": text, "quote_sha256": quote_hash, "match_mode": "exact"}],
            },
            {
                "id": step_id, "node_type": "ReasoningStep", "label": "收入预测支持买入", "status": "active",
                "premise_node_ids": [claim_forecast], "conclusion_claim_ids": [claim_rating],
                "assertion_level": "EXPLICIT",
            },
        ],
        "edges": [],
        "extraction_run": {},
        "coverage_manifest": {
            "total_source_objects": 1, "terminal_source_objects": 1,
            "source_object_status_counts": {"EXTRACTED": 1},
            "semantic_nodes": 3, "semantic_nodes_with_evidence": 3,
            "semantic_evidence_coverage": 1.0,
            "opaque_source_object_ids": [], "needs_review_source_object_ids": [],
        },
        "rejected_candidates": [],
    }
    for node_id in (data_id, claim_forecast, claim_rating):
        graph["edges"].append({
            "id": stable_id("EDGE", "EVIDENCED_BY", node_id, source_id),
            "edge_type": "EVIDENCED_BY", "source_id": node_id, "target_id": source_id,
            "assertion_level": "EXPLICIT", "status": "active", "confidence": 1.0,
        })
    graph["edges"].extend([
        {"id": "EDGE_ABOUT", "edge_type": "ABOUT", "source_id": data_id, "target_id": entity_id, "assertion_level": "EXPLICIT", "status": "active", "confidence": 1.0},
        {"id": "EDGE_MEASURES", "edge_type": "MEASURES", "source_id": data_id, "target_id": metric_id, "assertion_level": "EXPLICIT", "status": "active", "confidence": 1.0},
        {"id": "EDGE_PERIOD", "edge_type": "VALID_DURING", "source_id": data_id, "target_id": period_id, "assertion_level": "EXPLICIT", "status": "active", "confidence": 1.0},
        {"id": "EDGE_SUPPORT", "edge_type": "SUPPORTS", "source_id": claim_forecast, "target_id": claim_rating, "assertion_level": "EXPLICIT", "status": "active", "confidence": 1.0, "evidence": [{"source_object_id": source_id, "quote": text, "quote_sha256": quote_hash, "match_mode": "exact"}]},
        {"id": "EDGE_PREMISE", "edge_type": "PREMISE_OF", "source_id": claim_forecast, "target_id": step_id, "assertion_level": "EXPLICIT", "status": "active", "confidence": 1.0},
        {"id": "EDGE_CONCLUSION", "edge_type": "CONCLUDES", "source_id": step_id, "target_id": claim_rating, "assertion_level": "EXPLICIT", "status": "active", "confidence": 1.0},
    ])
    refresh_state_hash(graph)
    return graph


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="research_tceg_test_") as temp_name:
        source_path = Path(temp_name) / "report.txt"
        source_path.write_text("公司预计2026年营业收入增长20%，因此给予买入评级。", encoding="utf-8")
        base = fixture(source_path)
        cases = []

        cases.append(("valid", base, "PASS"))

        bad_quote = copy.deepcopy(base)
        next(node for node in bad_quote["nodes"] if node["id"] == "CLM_FORECAST")["evidence"][0]["quote"] = "不存在的证据"
        refresh_state_hash(bad_quote)
        cases.append(("fabricated_quote", bad_quote, "FAIL"))

        unverified = copy.deepcopy(base)
        edge = next(item for item in unverified["edges"] if item["id"] == "EDGE_SUPPORT")
        edge["assertion_level"] = "INFERRED"
        edge.pop("verification", None)
        refresh_state_hash(unverified)
        cases.append(("unverified_inference", unverified, "FAIL"))

        missing_context = copy.deepcopy(base)
        next(node for node in missing_context["nodes"] if node["id"] == "DATA_GROWTH")["period_ref"] = "PER_MISSING"
        refresh_state_hash(missing_context)
        cases.append(("missing_numeric_context", missing_context, "FAIL"))

        for name, graph, expected in cases:
            result = validate(graph)
            if result["status"] != expected:
                raise AssertionError(f"{name}: expected {expected}, got {result['status']}: {result['errors']}")
            print(f"PASS {name}: validator={result['status']}")

        if parse_numeric_confidence(0.82) != 0.82:
            raise AssertionError("numeric confidence was not accepted")
        for invalid in ("high", "0.82", "", None, True, -0.1, 1.1):
            if parse_numeric_confidence(invalid) is not None:
                raise AssertionError(f"invalid confidence was coerced: {invalid!r}")
        print("PASS strict_numeric_confidence")

        spaced_source = {
            "SO_TEST": {"normalized_text": "营业收入  100  百万元"},
        }
        evidence, error = canonical_evidence(
            {"evidence": [{"source_object_id": "SO_TEST", "quote": "营业收入 100 百万元"}]},
            spaced_source,
        )
        if error or evidence[0]["match_mode"] != "whitespace_normalized":
            raise AssertionError(f"whitespace evidence match failed: {error}, {evidence}")
        print("PASS whitespace_normalized_evidence")

        capacity_text = "iPhone 14 2022.09 6GB 128GB 内存容量：从 4GB 向 6GB 升级"
        capacity_source = {
            "id": "SO_CAPACITY", "document_id": "DOC_CAPACITY", "object_type": "table_like",
            "sequence": 1, "raw_text": capacity_text, "normalized_text": capacity_text,
            "sha256": sha256_text(capacity_text),
            "locator": {"page": 1, "block": 1, "char_start": 0, "char_end": len(capacity_text)},
            "processing_status": "NEEDS_REVIEW", "candidate_count": 0,
            "irrelevant_reason": None, "metadata": {},
        }
        builder = GraphBuilder({"id": "DOC_CAPACITY", "issuer": "Apple"}, [capacity_source])
        created = extract_capacity_table_data(builder)
        values = {
            node["value"]["raw"] for node in builder.nodes
            if node.get("node_type") == "DataPoint" and node["label"].startswith("iPhone 14 内存容量")
        }
        if created != 3 or values != {"4GB", "6GB"}:
            raise AssertionError(f"capacity extraction mismatch: created={created}, values={values}")
        print("PASS deterministic_capacity_table")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
