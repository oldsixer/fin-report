#!/usr/bin/env python3
"""Extract facts, data points and argument structure from an equity report.

The extractor deliberately separates three layers:

1. deterministic PDF/source registration;
2. LLM-produced semantic candidates;
3. deterministic evidence checks plus an independent relation-verification pass.

The LLM never writes the canonical graph directly.  Invalid evidence locators,
quotes that are absent from the registered source object, unknown references and
unverified inferred relations are rejected before graph construction.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from research_report_tceg_core import (
    LLMClient, SCHEMA_VERSION, build_source_objects, dump_json,
    extract_pdf_pages, load_dotenv, load_json, normalize_text, pack_source_chunks,
    refresh_state_hash, render_source_chunk, sha256_file, sha256_text,
    stable_id, unique,
)


CLAIM_ROLES = {
    "observation", "forecast", "interpretation", "valuation",
    "recommendation", "risk", "guidance",
}
MODALITIES = {"actual", "forecast", "opinion", "recommendation", "risk", "conditional"}
ARGUMENT_EDGE_TYPES = {"SUPPORTS", "CONTRADICTS", "CAUSES", "AFFECTS", "DEPENDS_ON"}
ALL_RELATION_TYPES = ARGUMENT_EDGE_TYPES | {"ASSUMES", "SAME_AS", "HAS_DATA"}
MATERIAL_CLASSIFICATIONS = {"material", "administrative", "legal", "opaque"}


def parse_numeric_confidence(value: Any) -> float | None:
    """Accept only an actual JSON number in [0, 1]; never coerce labels or strings."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    confidence = float(value)
    if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        return None
    return confidence


def build_extraction_views(
    source_objects: list[dict[str, Any]], max_chars: int,
) -> list[dict[str, Any]]:
    """Split only the LLM view of dense objects; canonical source objects stay intact."""
    views: list[dict[str, Any]] = []
    for obj in source_objects:
        lines = obj["normalized_text"].splitlines()
        parts: list[list[str]] = []
        current: list[str] = []
        current_length = 0
        for line in lines:
            extra = len(line) + (1 if current else 0)
            if current and current_length + extra > max_chars:
                parts.append(current)
                current = []
                current_length = 0
            current.append(line)
            current_length += len(line) + (1 if current_length else 0)
        if current:
            parts.append(current)
        for index, part in enumerate(parts, start=1):
            view = dict(obj)
            view["normalized_text"] = "\n".join(part)
            view["metadata"] = {
                **obj.get("metadata", {}),
                "extraction_view_index": index,
                "extraction_view_count": len(parts),
            }
            views.append(view)
    return views


def audit_candidates_to_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Adapt externally generated candidates to the normal extraction contract."""
    result: dict[str, Any] = {
        "source_reviews": payload.get("source_reviews") or [],
        "entities": [], "claims": [], "data_points": [], "events": [], "relations": [],
    }
    for candidate in payload.get("candidates") or []:
        if not isinstance(candidate, dict):
            continue
        kind = str(candidate.get("kind") or "")
        item = {
            key: value for key, value in candidate.items()
            if key not in {"kind", "candidate_id", "confidence"}
        }
        local_id = str(candidate.get("local_id") or candidate.get("candidate_id") or "")
        if kind == "claim":
            item["local_id"] = local_id
            result["claims"].append(item)
        elif kind == "data_point":
            item["local_id"] = local_id
            result["data_points"].append(item)
        elif kind == "event":
            item["local_id"] = local_id
            result["events"].append(item)
        elif kind == "relation":
            result["relations"].append({
                "source_local_id": candidate.get("source_local_id") or candidate.get("source_candidate_id"),
                "target_local_id": candidate.get("target_local_id") or candidate.get("target_candidate_id"),
                "relation_type": candidate.get("relation_type"),
                "assertion_level": candidate.get("assertion_level"),
                "confidence": candidate.get("confidence"),
                "rationale": candidate.get("rationale"),
                "evidence": candidate.get("evidence") or [],
            })
    return result


EXTRACTION_SYSTEM = """你是金融研报语义抽取器。目标是把研报表达的事实、数字、预测、假设、观点、风险和论证关系转换为结构化候选，不是总结文章。

严格规则：
1. 只能使用输入中给出的 SOURCE_OBJECT ID；不得补充外部知识。
2. 每条 Claim 必须是原文明确表达的原子命题，并提供逐字 evidence quote。分析师观点也是 EXPLICIT（明确写在研报里），不是客观真理。
3. 正文和不规则表格中的关键数字单独输出为 data_points，不要把不同期间合并为一个数字。具有清晰五期表头的标准财务表会由后续确定性程序逐格展开；不要在本步骤重复枚举其全部单元格，只抽取其明确表达的核心预测或观点。
4. prediction/forecast、风险、评级、假设与历史事实必须区分。
5. relations 只输出当前输入片段中明确表达或强烈蕴含的关系。不得把共现当因果。
6. evidence quote 必须是对应 SOURCE_OBJECT normalized text 的连续子串；不要改写 quote。
7. 法律声明、联系方式、页眉页脚可以标为 legal/administrative，不生成投资语义 Claim。
8. 图表只有标题而没有可读取数值时标为 opaque，不猜测图中数据。
9. 只返回合法 JSON，不使用 Markdown。不要输出隐藏思维过程；rationale 只写可审计的简短理由。
10. relations.confidence 必须直接输出为 0.0 到 1.0 之间的 JSON number；禁止 high/medium/low、百分数字符串、空字符串或 null。
11. “从 A 升至 B / A 向 B 升级”必须把起点 A 和终点 B 分别建成 data_point，并用 dimensions.endpoint 标记 before/after；明确写出的 CAGR、复合增长率、“最高 X%”也必须建 data_point。
12. 业务覆盖范围、关键假设、催化剂、风险机制都属于必须抽取的 Claim。标题或正文若把“公司地位”和“行业趋势”等不同命题合在一起，必须拆成多个原子 Claim，不得照抄为一个复合 Claim。
13. normalized_decimal 保留 raw 中的数字尾数，scale 单独表示换算倍率；unit 使用基础单位 CNY、USD、CNY/share、percent、GB、multiple 或 ratio。
"""


def extraction_prompt(source_text: str, source_ids: list[str]) -> str:
    contract = {
        "source_reviews": [{
            "source_object_id": "SO_...",
            "classification": "material|administrative|legal|opaque",
            "reason": "short reason",
        }],
        "entities": [{
            "local_id": "E1", "name": "实体名称",
            "entity_type": "company|product|industry|region|institution|other",
        }],
        "claims": [{
            "local_id": "C1",
            "text": "原子命题",
            "claim_role": "observation|forecast|interpretation|valuation|recommendation|risk|guidance",
            "modality": "actual|forecast|opinion|recommendation|risk|conditional",
            "polarity": "positive|negative|neutral|mixed",
            "importance": "core|supporting|context",
            "subject_name": "主体或null",
            "predicate": "规范化的大写关系名",
            "object_text": "宾语或命题补语",
            "metric_name": "指标或null",
            "period_label": "期间或null",
            "data_point_local_ids": ["D1"],
            "evidence": [{"source_object_id": "SO_...", "quote": "原文连续片段"}],
        }],
        "data_points": [{
            "local_id": "D1", "subject_name": "主体", "metric_name": "指标",
            "period_label": "2025E", "qualifier": "actual|forecast|market_data|assumption",
            "value": {
                "kind": "scalar|range|text", "raw": "37.4%",
                "normalized_decimal": "37.4 or null",
                "range_low": "null or number", "range_high": "null or number",
                "unit": "percent|CNY|CNY/share|multiple|million CNY|billion USD|GB|other|null",
                "currency": "CNY|USD|null", "scale": "1|0.01|1000000|100000000|null",
                "dimensions": {},
            },
            "evidence": [{"source_object_id": "SO_...", "quote": "包含该数字的连续原文"}],
        }],
        "events": [{
            "local_id": "V1", "text": "事件", "category": "supply|demand|price|strategy|technology|competition|macro|other",
            "subject_name": "事件主体或null", "period_label": "时间或null",
            "evidence": [{"source_object_id": "SO_...", "quote": "原文连续片段"}],
        }],
        "relations": [{
            "source_local_id": "C1|D1|V1", "target_local_id": "C2|D2|V2",
            "relation_type": "SUPPORTS|CONTRADICTS|CAUSES|AFFECTS|DEPENDS_ON|ASSUMES|HAS_DATA|SAME_AS",
            "assertion_level": "EXPLICIT|INFERRED", "confidence": 0.0,
            "rationale": "short auditable reason",
            "evidence": [{"source_object_id": "SO_...", "quote": "显式关系原文；推断关系可为空"}],
        }],
    }
    special_instruction = ""
    if "iPhone" in source_text and "内存容量" in source_text and "存储容量" in source_text:
        special_instruction = (
            "\n本片段含规则容量表。后续确定性程序会逐行保存机型、期间、内存和存储数值，"
            "因此不要重复输出逐行 data_points 或把每一行建成 Event；只把原文明确写出的容量升级变化抽取为原子 Claim，"
            "并保留对应逐字证据。\n"
        )
    return (
        "对下列研报来源对象做完整抽取。source_reviews 必须恰好覆盖这些 ID："
        + json.dumps(source_ids, ensure_ascii=False)
        + "\n输出结构必须遵守：\n"
        + json.dumps(contract, ensure_ascii=False, indent=2)
        + special_instruction
        + "\n\n研报来源对象：\n" + source_text
    )


RELATION_SYSTEM = """你是金融论证图构建器。输入是已经过证据校验的研报 Claim/Event 节点。只识别对投资论点有实质意义的跨段依赖。

规则：
1. 只能引用给定 node_id；不得创造新事实。
2. SUPPORTS 表示前者是后者的理由；CAUSES 要求因果方向；AFFECTS 表示影响但未必是充分原因；DEPENDS_ON 表示结论依赖某假设/前提；CONTRADICTS 表示实质冲突。
3. 不因主题相似或共现建立关系。
4. 一个预测值本身不能证明买入评级，除非结合增长、估值或竞争优势命题。
5. 关系均标为 INFERRED，之后会由独立验证步骤复核。
6. confidence 必须是 0.0 到 1.0 之间的 JSON number，例如 0.82；严禁输出 \"high\"、\"medium\"、百分数字符串或其他文字等级。
7. 只返回合法 JSON：{\"relations\":[...]}。rationale 只写可审计的短理由。"""


VERIFY_SYSTEM = """你是独立的金融论证关系审计器。逐条判断候选关系是否被给出的两个命题及其证据支持。

accept：方向和关系类型合理，且没有加入来源不存在的关键前提。
reject：只是共现、方向错误、因果过强、需要未披露中间前提或语义不相干。
关系必须由给定证据中的研报论证支持，而不只是金融常识上“可能有关”。DEPENDS_ON 的 source 必须是 target 的必要假设或前提；不要仅因两个预测同属一张财务表就建立依赖。具体事实可以支持概括性趋势，概括性趋势不能反向证明某个具体事实。SUPPORTS 表示对结论有实质性贡献，不要求单个前提独立充分；当结论明确由多个因素共同组成时，每个有证据的组成因素都可作为 contributory SUPPORTS，但 rationale 必须说明只是联合前提之一。
confidence 必须是 0.0 到 1.0 之间的 JSON number，例如 0.82；严禁使用 high/medium/low 等文字等级。
只返回合法 JSON：{\"verdicts\":[{\"proposal_id\":...,\"verdict\":\"accept|reject\",\"confidence\":0.82,\"reason\":...}]}。"""


def canonical_evidence(
    candidate: dict[str, Any], source_by_id: dict[str, dict[str, Any]],
    allowed_ids: set[str] | None = None,
) -> tuple[list[dict[str, str]], str | None]:
    result: list[dict[str, str]] = []
    for evidence in candidate.get("evidence") or []:
        source_id = str(evidence.get("source_object_id", "")).strip()
        quote = normalize_text(str(evidence.get("quote", "")))
        if not source_id or source_id not in source_by_id:
            return [], f"unknown evidence source object: {source_id}"
        if allowed_ids is not None and source_id not in allowed_ids:
            return [], f"evidence outside current extraction chunk: {source_id}"
        if not quote:
            return [], "empty evidence quote"
        source_text = source_by_id[source_id]["normalized_text"]
        if quote in source_text:
            match_mode = "exact"
        elif re.sub(r"\s+", "", quote) in re.sub(r"\s+", "", source_text):
            match_mode = "whitespace_normalized"
        else:
            return [], f"evidence quote is not a source substring: {source_id}"
        result.append({
            "source_object_id": source_id,
            "quote": quote,
            "quote_sha256": sha256_text(quote),
            "match_mode": match_mode,
        })
    return result, None


def canonical_value(raw_value: Any) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(raw_value, dict):
        return None, "value must be an object"
    kind = str(raw_value.get("kind") or "scalar").lower()
    raw = normalize_text(str(raw_value.get("raw", "")))
    if kind not in {"scalar", "range", "text"} or not raw:
        return None, "invalid value kind or empty raw value"

    def decimal_or_none(value: Any) -> str | None:
        if value is None or str(value).strip().lower() in {"", "null", "none"}:
            return None
        normalized = str(value).strip().replace(",", "")
        Decimal(normalized)
        return normalized

    try:
        normalized_decimal = decimal_or_none(raw_value.get("normalized_decimal"))
        range_low = decimal_or_none(raw_value.get("range_low"))
        range_high = decimal_or_none(raw_value.get("range_high"))
    except InvalidOperation:
        return None, "invalid normalized decimal"
    if kind == "scalar" and normalized_decimal is None:
        return None, "scalar value requires normalized_decimal"
    if kind == "range" and (range_low is None or range_high is None):
        return None, "range value requires range_low and range_high"
    scale = raw_value.get("scale")
    scale_string = None if scale is None or str(scale).lower() in {"null", "none", ""} else str(scale)
    if scale_string is not None:
        try:
            Decimal(scale_string)
        except InvalidOperation:
            return None, "invalid scale"
    if kind == "scalar":
        scalar_match = re.search(r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?", raw)
        if not scalar_match:
            return None, "scalar raw value has no numeric literal"
        normalized_decimal = str(Decimal(scalar_match.group(0).replace(",", "")))
    return {
        "kind": kind,
        "raw": raw,
        "normalized_decimal": normalized_decimal,
        "range_low": range_low,
        "range_high": range_high,
        "unit": raw_value.get("unit"),
        "currency": raw_value.get("currency"),
        "scale": scale_string,
        "dimensions": raw_value.get("dimensions") if isinstance(raw_value.get("dimensions"), dict) else {},
    }, None


def numeric_glyph_present(raw: str, evidence: list[dict[str, str]]) -> bool:
    glyphs = re.findall(r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?", raw)
    if not glyphs:
        return True
    corpus = " ".join(item["quote"] for item in evidence)
    return all(glyph.replace(" ", "") in corpus.replace(" ", "") for glyph in glyphs)


def canonicalize_value_unit(value: dict[str, Any], evidence: list[dict[str, str]]) -> None:
    """Resolve explicit source units to a base unit plus a decimal scale."""
    raw = str(value.get("raw") or "")
    corpus = " ".join(item["quote"] for item in evidence)
    compact = re.sub(r"\s+", "", raw + " " + corpus)
    if "%" in raw or value.get("unit") == "percent":
        value.update({"unit": "percent", "currency": None, "scale": "0.01"})
    elif "亿美元" in compact:
        value.update({"unit": "USD", "currency": "USD", "scale": "100000000"})
    elif "亿元" in compact:
        value.update({"unit": "CNY", "currency": "CNY", "scale": "100000000"})
    elif "百万元" in compact:
        value.update({"unit": "CNY", "currency": "CNY", "scale": "1000000"})
    elif "万元" in compact:
        value.update({"unit": "CNY", "currency": "CNY", "scale": "10000"})
    elif "元/股" in compact or "元／股" in compact:
        value.update({"unit": "CNY/share", "currency": "CNY", "scale": "1"})
    elif re.search(r"(?i)GB", raw):
        value.update({"unit": "GB", "currency": None, "scale": "1"})


def make_edge(
    edge_type: str, source_id: str, target_id: str, assertion_level: str = "EXPLICIT",
    confidence: float = 1.0, status: str = "active", **extra: Any,
) -> dict[str, Any]:
    payload = {
        "id": stable_id("EDGE", edge_type, source_id, target_id),
        "edge_type": edge_type,
        "source_id": source_id,
        "target_id": target_id,
        "assertion_level": assertion_level,
        "confidence": max(0.0, min(1.0, float(confidence))),
        "status": status,
    }
    payload.update(extra)
    return payload


class GraphBuilder:
    def __init__(self, document: dict[str, Any], source_objects: list[dict[str, Any]]):
        self.document = document
        self.source_objects = source_objects
        self.source_by_id = {item["id"]: item for item in source_objects}
        self.nodes: list[dict[str, Any]] = []
        self.edges: list[dict[str, Any]] = []
        self.node_by_id: dict[str, dict[str, Any]] = {}
        self.edge_keys: set[tuple[str, str, str]] = set()
        self.entities: dict[tuple[str, str], str] = {}
        self.metrics: dict[str, str] = {}
        self.periods: dict[str, str] = {}
        self.local_to_node: dict[str, str] = {}
        self.rejected: list[dict[str, Any]] = []

    def reject(self, candidate_type: str, reason: str, candidate: Any, chunk_id: str | None = None) -> None:
        self.rejected.append({
            "id": f"REJECT_{len(self.rejected) + 1:04d}",
            "candidate_type": candidate_type,
            "chunk_id": chunk_id,
            "reason": reason,
            "candidate": candidate,
        })

    def add_node(self, node: dict[str, Any]) -> str:
        node_id = node["id"]
        if node_id not in self.node_by_id:
            self.nodes.append(node)
            self.node_by_id[node_id] = node
        return node_id

    def add_edge(self, edge: dict[str, Any]) -> None:
        key = (edge["edge_type"], edge["source_id"], edge["target_id"])
        if key in self.edge_keys:
            return
        self.edge_keys.add(key)
        self.edges.append(edge)

    def entity(self, name: Any, entity_type: str = "other") -> str | None:
        label = normalize_text(str(name or ""))
        if not label:
            return None
        entity_type = entity_type if entity_type in {"company", "product", "industry", "region", "institution", "other"} else "other"
        key = (label.casefold(), entity_type)
        if key not in self.entities:
            node_id = stable_id("ENT", entity_type, label.casefold())
            self.entities[key] = node_id
            self.add_node({
                "id": node_id, "node_type": "Entity", "label": label,
                "entity_type": entity_type, "status": "active",
            })
        return self.entities[key]

    def metric(self, name: Any) -> str | None:
        label = normalize_text(str(name or ""))
        if not label:
            return None
        key = label.casefold()
        if key not in self.metrics:
            node_id = stable_id("MET", key)
            self.metrics[key] = node_id
            self.add_node({
                "id": node_id, "node_type": "Metric", "label": label,
                "canonical_name": label, "status": "active",
            })
        return self.metrics[key]

    def period(self, label_value: Any) -> str | None:
        label = normalize_text(str(label_value or ""))
        if not label:
            return None
        key = label.casefold()
        if key not in self.periods:
            node_id = stable_id("PER", key)
            self.periods[key] = node_id
            self.add_node({
                "id": node_id, "node_type": "Period", "label": label,
                "normalized_label": label, "status": "active",
            })
        return self.periods[key]

    def add_evidence_edges(self, node_id: str, evidence: list[dict[str, str]]) -> None:
        for item in evidence:
            self.add_edge(make_edge(
                "EVIDENCED_BY", node_id, item["source_object_id"], "EXPLICIT", 1.0,
                evidence_quote_sha256=item["quote_sha256"],
            ))

    def add_semantic_links(
        self, node_id: str, subject_ref: str | None = None,
        metric_ref: str | None = None, period_ref: str | None = None,
    ) -> None:
        if subject_ref:
            self.add_edge(make_edge("ABOUT", node_id, subject_ref))
        if metric_ref:
            self.add_edge(make_edge("MEASURES", node_id, metric_ref))
        if period_ref:
            self.add_edge(make_edge("VALID_DURING", node_id, period_ref))


FINANCIAL_METRIC_NAMES = sorted({
    "营业总收入", "营业收入增速", "营业收入", "同比增长率", "同比增长",
    "归母净利润增速", "归母净利润", "净利润", "营业利润增速", "营业利润",
    "毛利率", "净利率", "ROE", "ROIC", "每股经营性现金流", "每股净资产", "每股收益",
    "市盈率", "市销率", "市净率", "EV/EBITDA", "EV/EBIT",
    "货币资金", "应收款项", "存货", "流动资产", "长期股权投资", "固定资产", "在建工程",
    "无形资产", "非流动资产", "资产合计", "短期借款", "应付款项", "流动负债", "长期借款",
    "应付债券", "非流动负债", "负债合计", "股本", "资本公积", "留存收益", "归母股东权益",
    "少数股东权益", "负债和权益总计", "折旧摊销", "营运资本变动", "经营活动现金流",
    "资本开支", "投资变动", "投资活动现金流", "银行借款", "筹资活动现金流", "现金净增加额",
    "期初现金", "期末现金", "营业成本", "税金及附加", "销售费用", "管理费用", "研发费用",
    "财务费用", "资产减值损失", "公允价值变动", "投资净收益", "营业外收支", "利润总额",
    "所得税", "少数股东损益", "EBITDA", "资产负债率", "净负债比率", "流动比率", "速动比率",
    "总资产周转率", "应收账款周转率", "存货周转率",
}, key=len, reverse=True)


_TABLE_NUMBER = re.compile(r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?")
_TABLE_PERIOD = re.compile(r"\b20\d{2}[AE]?\b")


def _metric_occurrences(line: str) -> list[tuple[int, int, str]]:
    candidates: list[tuple[int, int, str]] = []
    for metric_name in FINANCIAL_METRIC_NAMES:
        for match in re.finditer(re.escape(metric_name), line, flags=re.IGNORECASE):
            candidates.append((match.start(), match.end(), metric_name))
    candidates.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    selected: list[tuple[int, int, str]] = []
    occupied_until = -1
    for start, end, name in candidates:
        if start < occupied_until:
            continue
        selected.append((start, end, name))
        occupied_until = end
    return selected


def _table_unit(metric_name: str, raw_values: list[str]) -> tuple[str, str | None, str]:
    if any(value.endswith("%") for value in raw_values):
        return "percent", None, "0.01"
    if metric_name.startswith("每股"):
        return "CNY/share", "CNY", "1"
    if metric_name in {"市盈率", "市销率", "市净率", "EV/EBIT", "EV/EBITDA"}:
        return "multiple", None, "1"
    if any(token in metric_name for token in ("比率", "周转率", "ROE", "ROIC")):
        return "ratio", None, "1"
    return "CNY", "CNY", "1000000"


def extract_periodic_table_data(builder: GraphBuilder) -> int:
    """Materialize five-period financial rows with exact deterministic values.

    The LLM identifies narrative meaning, while this pass expands regular table
    rows so a model cannot silently omit most visible cells.  It only activates
    on pages that contain an explicit period header with at least five periods.
    """
    by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for obj in builder.source_objects:
        by_page[int(obj["locator"]["page"])].append(obj)
    issuer_ref = builder.entity(builder.document.get("issuer"), "company")
    created = 0
    for page, objects in by_page.items():
        periods: list[str] | None = None
        for obj in objects:
            if obj["object_type"] not in {"table_like", "paragraph"}:
                continue
            lines = obj["normalized_text"].splitlines()
            for line in lines:
                tokens = _TABLE_PERIOD.findall(line)
                if len(tokens) >= 5:
                    periods = tokens[:5]
                    break
            if not periods:
                continue
            for line in lines:
                occurrences = _metric_occurrences(line)
                for index, (start, end, metric_name) in enumerate(occurrences):
                    segment_end = occurrences[index + 1][0] if index + 1 < len(occurrences) else len(line)
                    segment = line[start:segment_end].strip()
                    values = _TABLE_NUMBER.findall(line[end:segment_end])
                    if len(values) < len(periods):
                        continue
                    raw_values = values[:len(periods)]
                    unit, currency, scale = _table_unit(metric_name, raw_values)
                    metric_ref = builder.metric(metric_name)
                    evidence = [{
                        "source_object_id": obj["id"], "quote": segment,
                        "quote_sha256": sha256_text(segment), "match_mode": "exact",
                    }]
                    for period_label, raw in zip(periods, raw_values):
                        period_ref = builder.period(period_label)
                        qualifier = "forecast" if period_label.endswith("E") else "actual"
                        numeric = str(Decimal(raw.rstrip("%").replace(",", "")))
                        value = {
                            "kind": "scalar", "raw": raw,
                            "normalized_decimal": numeric, "range_low": None, "range_high": None,
                            "unit": unit, "currency": currency, "scale": scale, "dimensions": {},
                        }
                        node_id = stable_id(
                            "DATA", issuer_ref, metric_ref, period_ref, "scalar", raw,
                            numeric, None, None, qualifier,
                        )
                        if node_id in builder.node_by_id:
                            node = builder.node_by_id[node_id]
                            known = {
                                (item["source_object_id"], item["quote_sha256"])
                                for item in node.get("evidence", [])
                            }
                            evidence_key = (evidence[0]["source_object_id"], evidence[0]["quote_sha256"])
                            if evidence_key not in known:
                                node.setdefault("evidence", []).append(evidence[0].copy())
                        else:
                            builder.add_node({
                                "id": node_id, "node_type": "DataPoint",
                                "label": f"{metric_name} {period_label} = {raw}",
                                "subject_ref": issuer_ref, "metric_ref": metric_ref, "period_ref": period_ref,
                                "qualifier": qualifier, "assertion_level": "EXPLICIT", "value": value,
                                "evidence": [evidence[0].copy()], "status": "active",
                                "extraction_method": "deterministic_periodic_table",
                            })
                            builder.add_semantic_links(node_id, issuer_ref, metric_ref, period_ref)
                            created += 1
                        builder.add_evidence_edges(node_id, evidence)
    return created


_CAPACITY_ROW = re.compile(
    r"^(?P<model>iPhone\s+\S+)\s+(?P<period>20\d{2}\.\d{2})\s+"
    r"(?P<memory>\d+GB)\s+(?P<storage>\d+GB)(?:\s+.*)?$",
    flags=re.IGNORECASE,
)
_CAPACITY_TRANSITION = re.compile(
    r"(?P<metric>内存容量|存储容量)\s*[：:]\s*从\s*(?P<before>\d+GB)\s*向\s*"
    r"(?P<after>\d+GB)\s*升级",
    flags=re.IGNORECASE,
)


def _add_capacity_point(
    builder: GraphBuilder, subject_name: str, metric_name: str, period_label: str,
    raw: str, evidence: dict[str, str], endpoint: str,
) -> bool:
    subject_ref = builder.entity(subject_name, "product")
    metric_ref = builder.metric(metric_name)
    period_ref = builder.period(period_label)
    numeric = str(Decimal(re.search(r"\d+", raw).group(0)))
    node_id = stable_id(
        "DATA", subject_ref, metric_ref, period_ref, "scalar", raw,
        numeric, None, None, "actual",
    )
    evidence_key = (evidence["source_object_id"], evidence["quote_sha256"])
    if node_id in builder.node_by_id:
        node = builder.node_by_id[node_id]
        known = {
            (item["source_object_id"], item["quote_sha256"])
            for item in node.get("evidence", [])
        }
        if evidence_key not in known:
            node.setdefault("evidence", []).append(evidence.copy())
        created = False
    else:
        builder.add_node({
            "id": node_id, "node_type": "DataPoint",
            "label": f"{subject_name} {metric_name} {period_label} = {raw}",
            "subject_ref": subject_ref, "metric_ref": metric_ref, "period_ref": period_ref,
            "qualifier": "actual", "assertion_level": "EXPLICIT",
            "value": {
                "kind": "scalar", "raw": raw, "normalized_decimal": numeric,
                "range_low": None, "range_high": None, "unit": "GB",
                "currency": None, "scale": "1", "dimensions": {"endpoint": endpoint},
            },
            "evidence": [evidence.copy()], "status": "active",
            "extraction_method": "deterministic_capacity_table",
        })
        builder.add_semantic_links(node_id, subject_ref, metric_ref, period_ref)
        created = True
    builder.add_evidence_edges(node_id, [evidence])
    return created


def extract_capacity_table_data(builder: GraphBuilder) -> int:
    """Expand regular product/date/memory/storage rows and transition endpoints."""
    created = 0
    for obj in builder.source_objects:
        for line in obj["normalized_text"].splitlines():
            row = _CAPACITY_ROW.match(line.strip())
            if not row:
                continue
            evidence = {
                "source_object_id": obj["id"], "quote": line.strip(),
                "quote_sha256": sha256_text(line.strip()), "match_mode": "exact",
            }
            subject = normalize_text(row.group("model"))
            period = row.group("period")
            created += int(_add_capacity_point(
                builder, subject, "内存容量", period, row.group("memory"), evidence, "reported",
            ))
            created += int(_add_capacity_point(
                builder, subject, "存储容量", period, row.group("storage"), evidence, "reported",
            ))
            for transition in _CAPACITY_TRANSITION.finditer(line):
                metric = transition.group("metric")
                created += int(_add_capacity_point(
                    builder, subject, metric, period, transition.group("before"), evidence, "before",
                ))
                created += int(_add_capacity_point(
                    builder, subject, metric, period, transition.group("after"), evidence, "after",
                ))
    return created


def register_chunk_candidates(
    builder: GraphBuilder, result: dict[str, Any], chunk_id: str,
    allowed_source_ids: set[str],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
    pending_relations: list[dict[str, Any]] = []
    source_reviews: dict[str, dict[str, str]] = {}
    local_prefix = chunk_id + ":"

    for review in result.get("source_reviews") or []:
        source_id = str(review.get("source_object_id", ""))
        classification = str(review.get("classification", "")).lower()
        if source_id in allowed_source_ids and classification in MATERIAL_CLASSIFICATIONS:
            source_reviews[source_id] = {
                "classification": classification,
                "reason": normalize_text(str(review.get("reason", ""))),
            }

    for entity in result.get("entities") or []:
        local_id = str(entity.get("local_id", "")).strip()
        node_id = builder.entity(entity.get("name"), str(entity.get("entity_type", "other")))
        if local_id and node_id:
            builder.local_to_node[local_prefix + local_id] = node_id

    deferred_data_links: list[tuple[str, list[str]]] = []

    for point in result.get("data_points") or []:
        local_id = str(point.get("local_id", "")).strip()
        evidence, error = canonical_evidence(point, builder.source_by_id, allowed_source_ids)
        value, value_error = canonical_value(point.get("value"))
        if not local_id or error or value_error or not evidence:
            builder.reject("data_point", error or value_error or "missing local_id/evidence", point, chunk_id)
            continue
        if not numeric_glyph_present(value["raw"], evidence):
            builder.reject("data_point", "raw numeric glyph is absent from evidence", point, chunk_id)
            continue
        canonicalize_value_unit(value, evidence)
        qualifier = str(point.get("qualifier") or "actual")
        subject_name = point.get("subject_name")
        if not normalize_text(str(subject_name or "")) and qualifier in {"actual", "forecast", "assumption"}:
            subject_name = builder.document.get("issuer")
        subject_ref = builder.entity(subject_name, "company")
        metric_ref = builder.metric(point.get("metric_name"))
        period_ref = builder.period(point.get("period_label"))
        if not metric_ref or not period_ref:
            builder.reject("data_point", "metric_name and period_label are required", point, chunk_id)
            continue
        key = (
            subject_ref, metric_ref, period_ref, value["kind"], value["raw"],
            value.get("normalized_decimal"), value.get("range_low"), value.get("range_high"),
            qualifier,
        )
        node_id = stable_id("DATA", *key)
        node = {
            "id": node_id, "node_type": "DataPoint",
            "label": f"{point.get('metric_name')} {point.get('period_label')} = {value['raw']}",
            "subject_ref": subject_ref, "metric_ref": metric_ref, "period_ref": period_ref,
            "qualifier": qualifier,
            "assertion_level": "EXPLICIT", "value": value,
            "evidence": evidence, "status": "active",
        }
        if node_id in builder.node_by_id:
            existing = builder.node_by_id[node_id]
            known = {
                (item["source_object_id"], item["quote_sha256"])
                for item in existing.get("evidence", [])
            }
            existing.setdefault("evidence", []).extend(
                item for item in evidence
                if (item["source_object_id"], item["quote_sha256"]) not in known
            )
        else:
            builder.add_node(node)
            builder.add_semantic_links(node_id, subject_ref, metric_ref, period_ref)
        builder.add_evidence_edges(node_id, evidence)
        builder.local_to_node[local_prefix + local_id] = node_id

    for event in result.get("events") or []:
        local_id = str(event.get("local_id", "")).strip()
        evidence, error = canonical_evidence(event, builder.source_by_id, allowed_source_ids)
        text = normalize_text(str(event.get("text", "")))
        if not local_id or not text or error or not evidence:
            builder.reject("event", error or "missing local_id/text/evidence", event, chunk_id)
            continue
        subject_ref = builder.entity(event.get("subject_name"), "company")
        period_ref = builder.period(event.get("period_label"))
        node_id = stable_id("EVT", text.casefold(), *[item["source_object_id"] for item in evidence])
        builder.add_node({
            "id": node_id, "node_type": "Event", "label": text,
            "category": str(event.get("category") or "other"),
            "subject_ref": subject_ref, "period_ref": period_ref,
            "assertion_level": "EXPLICIT", "evidence": evidence, "status": "active",
        })
        builder.add_evidence_edges(node_id, evidence)
        builder.add_semantic_links(node_id, subject_ref, None, period_ref)
        builder.local_to_node[local_prefix + local_id] = node_id

    for claim in result.get("claims") or []:
        local_id = str(claim.get("local_id", "")).strip()
        evidence, error = canonical_evidence(claim, builder.source_by_id, allowed_source_ids)
        text = normalize_text(str(claim.get("text", "")))
        role = str(claim.get("claim_role") or "interpretation").lower()
        modality = str(claim.get("modality") or "opinion").lower()
        if role not in CLAIM_ROLES:
            role = "interpretation"
        if modality not in MODALITIES:
            modality = "opinion"
        if not local_id or not text or error or not evidence:
            builder.reject("claim", error or "missing local_id/text/evidence", claim, chunk_id)
            continue
        subject_ref = builder.entity(claim.get("subject_name"), "company")
        metric_ref = builder.metric(claim.get("metric_name"))
        period_ref = builder.period(claim.get("period_label"))
        node_id = stable_id("CLM", text.casefold(), *[item["source_object_id"] for item in evidence])
        builder.add_node({
            "id": node_id, "node_type": "Claim", "label": text,
            "claim_role": role, "modality": modality,
            "polarity": str(claim.get("polarity") or "neutral"),
            "importance": str(claim.get("importance") or "supporting"),
            "assertion_level": "EXPLICIT", "subject_ref": subject_ref,
            "predicate": str(claim.get("predicate") or "ASSERTS"),
            "object_text": normalize_text(str(claim.get("object_text") or "")),
            "metric_ref": metric_ref, "period_ref": period_ref,
            "evidence": evidence, "status": "active",
        })
        builder.add_evidence_edges(node_id, evidence)
        builder.add_semantic_links(node_id, subject_ref, metric_ref, period_ref)
        builder.local_to_node[local_prefix + local_id] = node_id
        deferred_data_links.append((node_id, [local_prefix + str(item) for item in claim.get("data_point_local_ids") or []]))

    for claim_id, local_data_ids in deferred_data_links:
        for local_data_id in local_data_ids:
            data_id = builder.local_to_node.get(local_data_id)
            if data_id and builder.node_by_id.get(data_id, {}).get("node_type") == "DataPoint":
                builder.add_edge(make_edge("HAS_DATA", claim_id, data_id))

    for relation in result.get("relations") or []:
        relation_type = str(relation.get("relation_type", "")).upper()
        source_key = local_prefix + str(relation.get("source_local_id", ""))
        target_key = local_prefix + str(relation.get("target_local_id", ""))
        source_id = builder.local_to_node.get(source_key)
        target_id = builder.local_to_node.get(target_key)
        if relation_type not in ALL_RELATION_TYPES or not source_id or not target_id or source_id == target_id:
            builder.reject("relation", "unknown relation type/reference or self-loop", relation, chunk_id)
            continue
        level = str(relation.get("assertion_level") or "INFERRED").upper()
        evidence, error = canonical_evidence(relation, builder.source_by_id, allowed_source_ids)
        if level == "EXPLICIT" and (error or not evidence):
            builder.reject("relation", error or "explicit relation requires evidence", relation, chunk_id)
            continue
        confidence = parse_numeric_confidence(relation.get("confidence"))
        if confidence is None:
            builder.reject("relation", "confidence must be a JSON number in [0, 1]", relation, chunk_id)
            continue
        proposal = {
            "proposal_id": stable_id("RELPROP", chunk_id, relation_type, source_id, target_id),
            "source_id": source_id, "target_id": target_id,
            "relation_type": relation_type,
            "assertion_level": "EXPLICIT" if level == "EXPLICIT" else "INFERRED",
            "confidence": confidence,
            "rationale": normalize_text(str(relation.get("rationale") or "")),
            "evidence": evidence if not error else [],
            "origin": "within_chunk",
        }
        pending_relations.append(proposal)
    return pending_relations, source_reviews


def compact_semantic_nodes(builder: GraphBuilder) -> list[dict[str, Any]]:
    result = []
    for node in builder.nodes:
        if node["node_type"] not in {"Claim", "Event"}:
            continue
        result.append({
            "node_id": node["id"],
            "node_type": node["node_type"],
            "text": node["label"],
            "role": node.get("claim_role") or node.get("category"),
            "importance": node.get("importance"),
            "evidence": [
                {"page": builder.source_by_id[item["source_object_id"]]["locator"]["page"], "quote": item["quote"]}
                for item in node.get("evidence", [])[:2]
            ],
        })
    return result


def propose_cross_relations(
    client: LLMClient, nodes: list[dict[str, Any]], checkpoint_dir: Path | None = None,
    target_batch_size: int = 4,
) -> list[dict[str, Any]]:
    if len(nodes) < 2:
        return []
    core_targets = [
        item for item in nodes
        if item["node_type"] == "Claim"
        and item.get("importance") == "core"
        and item.get("role") in {"recommendation", "forecast", "interpretation", "valuation", "risk", "guidance"}
    ]
    core_target_ids = {item["node_id"] for item in core_targets}
    supporting_risk_targets = [
        item for item in nodes
        if item["node_type"] == "Claim"
        and item.get("role") == "risk"
        and item["node_id"] not in core_target_ids
    ]
    targets = core_targets + supporting_risk_targets
    if not targets:
        targets = [item for item in nodes if item["node_type"] == "Claim"]
    proposals: list[dict[str, Any]] = []
    valid_ids = {item["node_id"] for item in nodes}
    seen: set[tuple[str, str, str]] = set()
    for batch_start in range(0, len(targets), target_batch_size):
        batch_number = batch_start // target_batch_size + 1
        target_batch = targets[batch_start:batch_start + target_batch_size]
        target_ids = [item["node_id"] for item in target_batch]
        prompt = (
            "只为 target_node_ids 中的结论寻找必要前提；source_id可以来自全部节点，target_id必须属于target_node_ids。"
            "输出 relations 数组，每项字段为 proposal_id、source_id、target_id、"
            "relation_type（SUPPORTS/CONTRADICTS/CAUSES/AFFECTS/DEPENDS_ON）、confidence、rationale。"
            "proposal_id 使用 R1、R2...。confidence 必须是0到1之间的JSON数字，例如0.82，禁止high/medium/low。"
            "对推荐/评级结论，优先检查收入、利润、毛利率、估值、竞争地位和核心行业逻辑，避免只选同类叙事。"
            "每个目标最多5个最关键且不重复的前提，整批最多20条关系。\n"
            f"target_node_ids={json.dumps(target_ids, ensure_ascii=False)}\n\n"
            + json.dumps(nodes, ensure_ascii=False, indent=2)
        )
        batch_digest = sha256_text(RELATION_SYSTEM + "\n" + prompt)
        checkpoint_path = checkpoint_dir / f"CROSS_{batch_number:03d}.json" if checkpoint_dir else None
        checkpoint = load_json(checkpoint_path) if checkpoint_path and checkpoint_path.is_file() else None
        if (
            checkpoint
            and checkpoint.get("model") == client.model
            and checkpoint.get("batch_digest") == batch_digest
            and checkpoint.get("finish_reason") == "stop"
        ):
            result = checkpoint["result"]
        else:
            result = client.complete_json(
                f"cross_chunk_argument_relations_{batch_number}", RELATION_SYSTEM, prompt, max_tokens=12000,
            )
            if checkpoint_path:
                call = client.calls[-1]
                dump_json(checkpoint_path, {
                    "model": client.model, "batch_digest": batch_digest,
                    "finish_reason": call.get("finish_reason"), "result": result,
                })
                if call.get("finish_reason") != "stop":
                    raise RuntimeError(
                        f"cross-relation batch {batch_number} was truncated; refusing an incomplete graph"
                    )
        for item in result.get("relations") or []:
            source_id = str(item.get("source_id", ""))
            target_id = str(item.get("target_id", ""))
            relation_type = str(item.get("relation_type", "")).upper()
            key = (relation_type, source_id, target_id)
            if source_id not in valid_ids or target_id not in set(target_ids) or source_id == target_id:
                continue
            if relation_type not in ARGUMENT_EDGE_TYPES or key in seen:
                continue
            confidence = parse_numeric_confidence(item.get("confidence"))
            if confidence is None:
                continue
            seen.add(key)
            proposals.append({
                "proposal_id": stable_id("RELPROP", "cross", relation_type, source_id, target_id),
                "source_id": source_id, "target_id": target_id,
                "relation_type": relation_type, "assertion_level": "INFERRED",
                "confidence": confidence,
                "rationale": normalize_text(str(item.get("rationale") or "")),
                "evidence": [], "origin": "cross_chunk",
            })
    return proposals


def verify_inferred_relations(
    client: LLMClient, builder: GraphBuilder, proposals: list[dict[str, Any]], batch_size: int = 6,
    checkpoint_dir: Path | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for start in range(0, len(proposals), batch_size):
        batch = proposals[start:start + batch_size]
        review_payload = []
        for proposal in batch:
            source = builder.node_by_id[proposal["source_id"]]
            target = builder.node_by_id[proposal["target_id"]]
            review_payload.append({
                "proposal_id": proposal["proposal_id"],
                "relation_type": proposal["relation_type"],
                "source": {"text": source["label"], "evidence": source.get("evidence", [])},
                "target": {"text": target["label"], "evidence": target.get("evidence", [])},
                "proposed_rationale": proposal.get("rationale"),
            })
        batch_number = start // batch_size + 1
        serialized_review = json.dumps(review_payload, ensure_ascii=False, indent=2)
        batch_digest = sha256_text(VERIFY_SYSTEM + "\n" + serialized_review)
        checkpoint_path = checkpoint_dir / f"VERIFY_{batch_number:03d}.json" if checkpoint_dir else None
        checkpoint = load_json(checkpoint_path) if checkpoint_path and checkpoint_path.is_file() else None
        if (
            checkpoint
            and checkpoint.get("model") == client.model
            and checkpoint.get("batch_digest") == batch_digest
            and checkpoint.get("finish_reason") == "stop"
        ):
            result = checkpoint["result"]
        else:
            result = client.complete_json(
                f"verify_argument_relations_{batch_number}", VERIFY_SYSTEM,
                serialized_review, max_tokens=8000,
            )
            if checkpoint_path:
                call = client.calls[-1]
                dump_json(checkpoint_path, {
                    "model": client.model, "batch_digest": batch_digest,
                    "finish_reason": call.get("finish_reason"), "result": result,
                })
                if call.get("finish_reason") != "stop":
                    raise RuntimeError(
                        f"relation-verification batch {batch_number} was truncated; refusing an incomplete graph"
                    )
        verdicts = {str(item.get("proposal_id")): item for item in result.get("verdicts") or []}
        for proposal in batch:
            verdict = verdicts.get(proposal["proposal_id"], {})
            confidence = parse_numeric_confidence(verdict.get("confidence"))
            if confidence is None:
                proposal["verification"] = {
                    "verdict": "reject",
                    "confidence": None,
                    "reason": "verifier confidence must be a JSON number in [0, 1]",
                    "model": client.model,
                }
                rejected.append(proposal)
                continue
            proposal["verification"] = {
                "verdict": str(verdict.get("verdict") or "reject").lower(),
                "confidence": confidence,
                "reason": normalize_text(str(verdict.get("reason") or "missing verifier verdict")),
                "model": client.model,
            }
            if proposal["verification"]["verdict"] == "accept" and confidence >= 0.65:
                accepted.append(proposal)
            else:
                rejected.append(proposal)
    return accepted, rejected


def creates_argument_cycle(
    adjacency: dict[str, set[str]], source_id: str, target_id: str,
) -> bool:
    stack = [target_id]
    seen: set[str] = set()
    while stack:
        current = stack.pop()
        if current == source_id:
            return True
        if current in seen:
            continue
        seen.add(current)
        stack.extend(adjacency.get(current, set()))
    return False


def materialize_relations(builder: GraphBuilder, relations: list[dict[str, Any]]) -> None:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for relation in sorted(
        relations, key=lambda item: (
            item["assertion_level"] != "EXPLICIT", -float(item.get("confidence", 0.0)), item["proposal_id"],
        ),
    ):
        source_id = relation["source_id"]
        target_id = relation["target_id"]
        relation_type = relation["relation_type"]
        if relation_type in ARGUMENT_EDGE_TYPES and creates_argument_cycle(adjacency, source_id, target_id):
            builder.reject("relation", "would create an argument cycle", relation)
            continue
        if relation_type in ARGUMENT_EDGE_TYPES:
            adjacency[source_id].add(target_id)
        verification = relation.get("verification")
        builder.add_edge(make_edge(
            relation_type, source_id, target_id, relation["assertion_level"],
            relation.get("confidence", 0.5), "active",
            rationale=relation.get("rationale"), evidence=relation.get("evidence", []),
            extraction_origin=relation.get("origin"), verification=verification,
        ))
        if relation_type in ARGUMENT_EDGE_TYPES and builder.node_by_id.get(target_id, {}).get("node_type") == "Claim":
            step_id = stable_id("STEP", relation_type, source_id, target_id)
            builder.add_node({
                "id": step_id, "node_type": "ReasoningStep",
                "label": f"{relation_type}: {builder.node_by_id[source_id]['label']} → {builder.node_by_id[target_id]['label']}",
                "reasoning_method": relation_type.lower(),
                "premise_node_ids": [source_id], "conclusion_claim_ids": [target_id],
                "rationale": relation.get("rationale", ""),
                "assertion_level": relation["assertion_level"],
                "verification": verification, "status": "active",
            })
            builder.add_edge(make_edge("PREMISE_OF", source_id, step_id, relation["assertion_level"], relation.get("confidence", 0.5)))
            builder.add_edge(make_edge("CONCLUDES", step_id, target_id, relation["assertion_level"], relation.get("confidence", 0.5)))


def finalize_source_coverage(
    source_objects: list[dict[str, Any]], builder: GraphBuilder,
    source_reviews: dict[str, dict[str, str]],
) -> dict[str, Any]:
    counts = Counter()
    referenced = Counter()
    for node in builder.nodes:
        for evidence in node.get("evidence", []):
            referenced[evidence["source_object_id"]] += 1
    for obj in source_objects:
        count = referenced[obj["id"]]
        review = source_reviews.get(obj["id"])
        obj["candidate_count"] = count
        if count:
            obj["processing_status"] = "EXTRACTED"
            obj["irrelevant_reason"] = None
        elif review and review["classification"] in {"administrative", "legal"}:
            obj["processing_status"] = "NO_CLAIM"
            obj["irrelevant_reason"] = review["reason"] or review["classification"]
        elif (review and review["classification"] == "opaque") or obj["object_type"] == "figure_caption":
            obj["processing_status"] = "OPAQUE"
            obj["irrelevant_reason"] = (review or {}).get("reason") or "figure values are not present in the PDF text layer"
        else:
            obj["processing_status"] = "NEEDS_REVIEW"
            obj["irrelevant_reason"] = (review or {}).get("reason") or "material source object produced no accepted semantic node"
        counts[obj["processing_status"]] += 1
    total = len(source_objects)
    terminal = counts["EXTRACTED"] + counts["NO_CLAIM"] + counts["OPAQUE"] + counts["NEEDS_REVIEW"] + counts["ERROR"]
    semantic_nodes = [node for node in builder.nodes if node["node_type"] in {"Claim", "DataPoint", "Event"}]
    evidenced = [node for node in semantic_nodes if node.get("evidence")]
    return {
        "total_source_objects": total,
        "terminal_source_objects": terminal,
        "source_object_status_counts": dict(sorted(counts.items())),
        "source_processing_coverage": round(terminal / total, 6) if total else 1.0,
        "semantic_nodes": len(semantic_nodes),
        "semantic_nodes_with_evidence": len(evidenced),
        "semantic_evidence_coverage": round(len(evidenced) / len(semantic_nodes), 6) if semantic_nodes else 1.0,
        "opaque_source_object_ids": [obj["id"] for obj in source_objects if obj["processing_status"] == "OPAQUE"],
        "needs_review_source_object_ids": [obj["id"] for obj in source_objects if obj["processing_status"] == "NEEDS_REVIEW"],
        "definition": "Coverage records processing disposition; it is not a gold-label recall estimate.",
    }


def write_summary(path: Path, graph: dict[str, Any], validation: dict[str, Any] | None = None) -> None:
    node_counts = Counter(node["node_type"] for node in graph["nodes"])
    edge_counts = Counter(edge["edge_type"] for edge in graph["edges"])
    coverage = graph["coverage_manifest"]
    lines = [
        "# 研报 TCEG 抽取结果", "",
        f"- 文档：{graph['document']['title']}",
        f"- 图状态哈希：`{graph['state_hash']}`",
        f"- 来源对象：{coverage['total_source_objects']}",
        f"- 语义节点：{coverage['semantic_nodes']}",
        f"- 语义节点证据覆盖率：{coverage['semantic_evidence_coverage']:.1%}",
        f"- 待人工复核来源对象：{len(coverage['needs_review_source_object_ids'])}",
        f"- 图像/不可读来源对象：{len(coverage['opaque_source_object_ids'])}",
        f"- 拒绝候选：{len(graph['rejected_candidates'])}", "",
        "## 节点", "",
    ]
    lines.extend(f"- {name}: {count}" for name, count in sorted(node_counts.items()))
    lines.extend(["", "## 关系", ""])
    lines.extend(f"- {name}: {count}" for name, count in sorted(edge_counts.items()))
    if validation:
        lines.extend(["", "## 校验", "", f"- 状态：{validation.get('status')}", f"- 错误：{len(validation.get('errors', []))}", f"- 警告：{len(validation.get('warnings', []))}"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--title", required=True)
    parser.add_argument("--source-url", default=None)
    parser.add_argument("--publisher", default=None)
    parser.add_argument("--published-at", default=None)
    parser.add_argument("--issuer", default=None)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--model", default=None)
    parser.add_argument("--verification-model", default=None)
    parser.add_argument("--candidate-file", type=Path)
    parser.add_argument("--max-chunk-chars", type=int, default=8500)
    parser.add_argument("--max-block-chars", type=int, default=2800)
    parser.add_argument("--max-extraction-view-chars", type=int, default=600)
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()

    load_dotenv(args.env_file)
    base_url = os.environ.get("LIVINGFIN_LLM_BASE_URL", "").strip()
    api_key = os.environ.get("LIVINGFIN_LLM_API_KEY", "").strip()
    model = args.model or os.environ.get("LIVINGFIN_LLM_MODEL", "").strip() or "gemini-2.5-flash"
    verification_model = args.verification_model or model
    if not base_url or not api_key:
        raise SystemExit("LIVINGFIN_LLM_BASE_URL and LIVINGFIN_LLM_API_KEY are required")

    input_path = args.input.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    document_id = stable_id("DOC", sha256_file(input_path))
    document = {
        "id": document_id, "title": args.title,
        "source_type": "broker_research_pdf" if input_path.suffix.lower() == ".pdf" else "research_text",
        "local_path": str(input_path), "sha256": sha256_file(input_path),
        "source_url": args.source_url, "publisher": args.publisher,
        "published_at": args.published_at, "issuer": args.issuer,
    }
    if input_path.suffix.lower() == ".pdf":
        pages = extract_pdf_pages(input_path)
    else:
        pages = [input_path.read_text(encoding="utf-8")]
    source_objects = build_source_objects(document_id, pages, args.max_block_chars)
    extraction_views = build_extraction_views(source_objects, args.max_extraction_view_chars)
    chunks = pack_source_chunks(extraction_views, args.max_chunk_chars)
    source_graph = {
        "document": document, "source_objects": source_objects,
        "extraction_method": "pdftotext-layout+block-segmentation",
        "page_count": len(pages), "chunk_count": len(chunks),
        "extraction_view_count": len(extraction_views),
    }
    dump_json(output_dir / "source_graph.json", source_graph)

    extraction_client = LLMClient(base_url, api_key, model)
    reasoning_client = extraction_client if verification_model == model else LLMClient(base_url, api_key, verification_model)
    builder = GraphBuilder(document, source_objects)
    all_pending_relations: list[dict[str, Any]] = []
    all_source_reviews: dict[str, dict[str, str]] = {}
    chunk_results: list[dict[str, Any]] = []
    checkpoint_dir = output_dir / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    resumed_chunks = 0
    if args.candidate_file:
        candidate_payload = load_json(args.candidate_file)
        result = audit_candidates_to_result(candidate_payload)
        source_ids = [item["id"] for item in source_objects]
        chunk_id = "EXTERNAL_CANDIDATES"
        chunk_results.append({
            "chunk_id": chunk_id, "source_object_ids": source_ids,
            "candidate_file": str(args.candidate_file.resolve()), "result": result,
        })
        pending, reviews = register_chunk_candidates(builder, result, chunk_id, set(source_ids))
        all_pending_relations.extend(pending)
        all_source_reviews.update(reviews)
    else:
        for index, chunk in enumerate(chunks, start=1):
            chunk_id = f"CHUNK_{index:03d}"
            source_ids = [item["id"] for item in chunk]
            rendered_chunk = render_source_chunk(chunk)
            prompt = extraction_prompt(rendered_chunk, source_ids)
            prompt_digest = sha256_text(EXTRACTION_SYSTEM + "\n" + prompt)
            checkpoint_path = checkpoint_dir / f"{chunk_id}.json"
            checkpoint = None if args.no_resume or not checkpoint_path.is_file() else load_json(checkpoint_path)
            if (
                checkpoint
                and checkpoint.get("model") == model
                and checkpoint.get("source_object_ids") == source_ids
                and checkpoint.get("prompt_digest") == prompt_digest
                and checkpoint.get("finish_reason") == "stop"
            ):
                result = checkpoint["result"]
                resumed_chunks += 1
            else:
                result = extraction_client.complete_json(
                    f"semantic_extraction_{chunk_id}", EXTRACTION_SYSTEM,
                    prompt, max_tokens=16000,
                )
                dump_json(checkpoint_path, {
                    "chunk_id": chunk_id, "model": model,
                    "source_object_ids": source_ids, "prompt_digest": prompt_digest,
                    "finish_reason": extraction_client.calls[-1].get("finish_reason"),
                    "result": result,
                })
                if extraction_client.calls[-1].get("finish_reason") != "stop":
                    raise RuntimeError(
                        f"{chunk_id} was truncated; reduce --max-chunk-chars rather than accepting repaired partial JSON"
                    )
            if not isinstance(result, dict):
                raise RuntimeError(f"{chunk_id} returned a non-object JSON value")
            chunk_results.append({"chunk_id": chunk_id, "source_object_ids": source_ids, "result": result})
            pending, reviews = register_chunk_candidates(builder, result, chunk_id, set(source_ids))
            all_pending_relations.extend(pending)
            all_source_reviews.update(reviews)

    deterministic_table_points = extract_periodic_table_data(builder)
    deterministic_capacity_points = extract_capacity_table_data(builder)
    compact_nodes = compact_semantic_nodes(builder)
    cross_relations = propose_cross_relations(
        reasoning_client, compact_nodes, checkpoint_dir,
    )
    all_pending_relations.extend(cross_relations)

    explicit_relations = [item for item in all_pending_relations if item["assertion_level"] == "EXPLICIT"]
    inferred_relations = [item for item in all_pending_relations if item["assertion_level"] == "INFERRED"]
    verified_relations, verifier_rejections = verify_inferred_relations(
        reasoning_client, builder, inferred_relations, checkpoint_dir=checkpoint_dir,
    )
    for relation in verifier_rejections:
        builder.reject("relation", "independent verifier rejected inferred relation", relation)
    materialize_relations(builder, explicit_relations + verified_relations)

    coverage = finalize_source_coverage(source_objects, builder, all_source_reviews)
    graph = {
        "schema_version": SCHEMA_VERSION,
        "graph_id": stable_id("TCEG", document_id, model, verification_model),
        "state_hash": "0" * 64,
        "document": document,
        "source_objects": source_objects,
        "nodes": builder.nodes,
        "edges": builder.edges,
        "extraction_run": {
            "run_id": stable_id("RUN", document_id, datetime.now(timezone.utc).isoformat()),
            "started_from": "historical_research_report",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "model": model,
            "verification_model": verification_model,
            "extractor": "extract-research-report-tceg-0.1",
            "api_calls": [
                *[{**call, "stage": "candidate_extraction"} for call in extraction_client.calls],
                *([] if reasoning_client is extraction_client else [{**call, "stage": "relation_reasoning"} for call in reasoning_client.calls]),
            ],
            "chunk_count": 1 if args.candidate_file else len(chunks),
            "resumed_candidate_chunks": resumed_chunks,
            "candidate_input": str(args.candidate_file.resolve()) if args.candidate_file else "llm_api",
            "deterministic_table_points_created": deterministic_table_points,
            "deterministic_capacity_points_created": deterministic_capacity_points,
            "semantic_contract": "LLM candidates + deterministic evidence gate + independent inferred-relation verifier",
        },
        "coverage_manifest": coverage,
        "rejected_candidates": builder.rejected,
    }
    refresh_state_hash(graph)
    dump_json(output_dir / "candidates.json", {
        "chunks": chunk_results,
        "cross_relation_proposals": cross_relations,
        "verified_relations": verified_relations,
        "verifier_rejections": verifier_rejections,
    })
    dump_json(output_dir / "tceg.json", graph)
    dump_json(output_dir / "extraction_trace.json", {
        "document_id": document_id, "model": model,
        "verification_model": verification_model,
        "api_calls": [
            *[{**call, "stage": "candidate_extraction"} for call in extraction_client.calls],
            *([] if reasoning_client is extraction_client else [{**call, "stage": "relation_reasoning"} for call in reasoning_client.calls]),
        ],
        "source_object_count": len(source_objects),
        "chunk_count": 1 if args.candidate_file else len(chunks),
        "candidate_input": str(args.candidate_file.resolve()) if args.candidate_file else "llm_api",
        "resumed_candidate_chunks": resumed_chunks,
        "deterministic_table_points_created": deterministic_table_points,
        "deterministic_capacity_points_created": deterministic_capacity_points,
        "candidate_rejections": len(builder.rejected),
    })
    write_summary(output_dir / "EXTRACTION_SUMMARY.md", graph)
    print(json.dumps({
        "graph": str(output_dir / "tceg.json"),
        "source_objects": len(source_objects), "nodes": len(builder.nodes),
        "edges": len(builder.edges), "rejected_candidates": len(builder.rejected),
        "api_calls": len(extraction_client.calls) + (0 if reasoning_client is extraction_client else len(reasoning_client.calls)),
        "state_hash": graph["state_hash"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
