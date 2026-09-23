(async () => {
  "use strict";

  const config = window.TCEG_CONFIG || {};
  let data = window.TCEG_DATA;
  let liveData = false;
  if (location.protocol !== "file:" && config.liveEndpoint) {
    try {
      const response = await fetch(config.liveEndpoint, { cache: "no-store" });
      if (response.ok) {
        data = await response.json();
        liveData = true;
      }
    } catch (_) {
      liveData = false;
    }
  }
  if (!data) throw new Error("TCEG visualization data is missing");

  const svgNS = "http://www.w3.org/2000/svg";
  const argumentTypes = new Set(["SUPPORTS", "CAUSES", "DEPENDS_ON", "HAS_DATA", "PREMISE_OF", "CONCLUDES"]);
  const nodeById = new Map(data.nodes.map((node) => [node.id, node]));
  const sourceById = new Map(data.source_objects.map((source) => [source.id, source]));
  const edgeById = new Map(data.edges.map((edge) => [edge.id, edge]));
  const incident = new Map();
  const sourceToNodes = new Map();
  const warningIds = new Set(data.warning_node_ids || []);
  const benchmarkIds = new Set(data.benchmark_object_ids || []);

  data.nodes.forEach((node) => incident.set(node.id, []));
  data.edges.forEach((edge) => {
    if (incident.has(edge.source_id)) incident.get(edge.source_id).push(edge);
    if (incident.has(edge.target_id)) incident.get(edge.target_id).push(edge);
  });
  data.nodes.forEach((node) => {
    (node.evidence || []).forEach((evidence) => {
      if (!sourceToNodes.has(evidence.source_object_id)) sourceToNodes.set(evidence.source_object_id, []);
      sourceToNodes.get(evidence.source_object_id).push(node.id);
    });
  });

  const $ = (selector) => document.querySelector(selector);
  const graphSvg = $("#graphSvg");
  const graphLayer = $("#graphLayer");
  const graphEmpty = $("#graphEmpty");
  const inspector = $("#inspector");
  const searchInput = $("#searchInput");
  const searchResults = $("#searchResults");
  const reportImage = $("#reportImage");
  const sourceText = $("#sourceText");
  const sourceMeta = $("#sourceMeta");
  const sourceLinked = $("#sourceLinked");
  const pageIndicator = $("#pageIndicator");

  let currentMode = "thesis";
  let currentPage = 1;
  let currentSourceId = null;
  let selectedNodeId = null;
  let renderedNodeIds = new Set();
  let renderedEdgeIds = new Set();
  let baseView = { x: 0, y: 0, w: 1600, h: 1000 };
  let viewBox = { x: 0, y: 0, w: 1600, h: 1000 };
  let dragStart = null;

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function truncate(text, max = 88) {
    const compact = String(text || "").replace(/\s+/g, " ").trim();
    return compact.length > max ? `${compact.slice(0, max - 1)}…` : compact;
  }

  function svgElement(name, attrs = {}) {
    const element = document.createElementNS(svgNS, name);
    Object.entries(attrs).forEach(([key, value]) => element.setAttribute(key, String(value)));
    return element;
  }

  function setViewBox(next) {
    viewBox = next;
    graphSvg.setAttribute("viewBox", `${next.x} ${next.y} ${next.w} ${next.h}`);
  }

  function hashNumber(value) {
    let hash = 2166136261;
    for (let i = 0; i < value.length; i += 1) {
      hash ^= value.charCodeAt(i);
      hash = Math.imul(hash, 16777619);
    }
    return hash >>> 0;
  }

  function unique(values) {
    return [...new Set(values)];
  }

  function neighborhood(seedIds, depth, allowedTypes = argumentTypes) {
    const found = new Set(seedIds.filter((id) => nodeById.has(id)));
    let frontier = new Set(found);
    for (let level = 0; level < depth; level += 1) {
      const next = new Set();
      frontier.forEach((id) => {
        (incident.get(id) || []).forEach((edge) => {
          if (!allowedTypes.has(edge.edge_type)) return;
          const other = edge.source_id === id ? edge.target_id : edge.source_id;
          if (nodeById.has(other) && !found.has(other)) next.add(other);
        });
      });
      next.forEach((id) => found.add(id));
      frontier = next;
    }
    return found;
  }

  function modeNodeIds(mode) {
    if (mode === "full") return new Set(data.nodes.map((node) => node.id));

    if (mode === "data") {
      const seeds = data.nodes
        .filter((node) => node.node_type === "DataPoint" && benchmarkIds.has(node.id))
        .map((node) => node.id);
      const relevantEdges = new Set(["HAS_DATA", "SUPPORTS", "MEASURES", "VALID_DURING", "ABOUT"]);
      return neighborhood(seeds, 1, relevantEdges);
    }

    const seeds = data.nodes
      .filter((node) => node.node_type === "Claim" && node.importance === "core")
      .map((node) => node.id);
    return neighborhood(seeds, 2, argumentTypes);
  }

  function modeEdges(nodeIds, mode) {
    return data.edges.filter((edge) => {
      if (!nodeIds.has(edge.source_id) || !nodeIds.has(edge.target_id)) return false;
      if (mode === "thesis") return argumentTypes.has(edge.edge_type);
      if (mode === "data") return ["HAS_DATA", "SUPPORTS", "MEASURES", "VALID_DURING", "ABOUT"].includes(edge.edge_type);
      return true;
    });
  }

  function nodeRadius(node, mode) {
    const degree = (incident.get(node.id) || []).length;
    const base = mode === "full" ? 5 : 7;
    const importance = node.importance === "core" ? 4 : node.importance === "supporting" ? 1.5 : 0;
    return Math.min(mode === "full" ? 10 : 16, base + Math.sqrt(degree) * .7 + importance);
  }

  function layoutNodes(nodes, mode, worldHeight = 1000) {
    const centers = {
      Entity: [165, 205],
      Event: [210, 500],
      DataPoint: [390, 785],
      Metric: [720, 880],
      Period: [1040, 875],
      ReasoningStep: [735, 420],
      Claim: [1280, 430],
    };
    const grouped = new Map();
    nodes.forEach((node) => {
      if (!grouped.has(node.node_type)) grouped.set(node.node_type, []);
      grouped.get(node.node_type).push(node);
    });
    const positions = new Map();
    grouped.forEach((group, type) => {
      group.sort((a, b) => {
        const ai = a.importance === "core" ? 0 : a.importance === "supporting" ? 1 : 2;
        const bi = b.importance === "core" ? 0 : b.importance === "supporting" ? 1 : 2;
        return ai - bi || hashNumber(a.id) - hashNumber(b.id);
      });
      const [cx, cy] = centers[type] || [800, 500];
      const density = mode === "full" ? 14 : 21;
      const maxRadius = type === "DataPoint" && mode === "full" ? 270 : type === "Claim" ? 225 : 150;
      group.forEach((node, index) => {
        const angle = index * 2.399963229728653 + (hashNumber(type) % 100) / 100;
        const radius = Math.min(maxRadius, Math.sqrt(index + .6) * density);
        const jitterX = ((hashNumber(node.id) % 17) - 8) * .8;
        const jitterY = (((hashNumber(node.id) >> 5) % 17) - 8) * .8;
        positions.set(node.id, {
          x: Math.max(30, Math.min(1570, cx + Math.cos(angle) * radius + jitterX)),
          y: Math.max(30, Math.min(970, cy + Math.sin(angle) * radius + jitterY)),
        });
      });
    });
    const verticalScale = worldHeight / 1000;
    positions.forEach((position) => { position.y *= verticalScale; });
    return positions;
  }

  function nodeShape(node, x, y, radius) {
    if (node.node_type === "Claim") {
      return svgElement("rect", { class: "shape", x: x - radius, y: y - radius * .72, width: radius * 2, height: radius * 1.44, rx: 2 });
    }
    if (node.node_type === "Event") {
      return svgElement("polygon", { class: "shape", points: `${x},${y-radius} ${x+radius},${y} ${x},${y+radius} ${x-radius},${y}` });
    }
    if (node.node_type === "ReasoningStep") {
      return svgElement("polygon", { class: "shape", points: `${x-radius},${y-radius*.75} ${x+radius},${y-radius*.75} ${x+radius*.72},${y+radius*.75} ${x-radius*.72},${y+radius*.75}` });
    }
    if (node.node_type === "Period") {
      return svgElement("rect", { class: "shape", x: x - radius, y: y - radius, width: radius * 2, height: radius * 2, rx: radius });
    }
    return svgElement("circle", { class: "shape", cx: x, cy: y, r: radius });
  }

  function labelIdsFor(nodes, mode) {
    const ranked = (filter, limit) => nodes
      .filter(filter)
      .sort((a, b) => (incident.get(b.id)?.length || 0) - (incident.get(a.id)?.length || 0))
      .slice(0, limit)
      .map((node) => node.id);
    if (mode === "thesis") {
      return new Set([
        ...ranked((node) => node.node_type === "Claim" && node.importance === "core", 12),
        ...ranked((node) => node.node_type === "Event", 5),
        ...ranked((node) => node.node_type === "DataPoint" && benchmarkIds.has(node.id), 3),
      ]);
    }
    if (mode === "data") {
      return new Set([
        ...ranked((node) => node.node_type === "DataPoint", 16),
        ...ranked((node) => node.node_type === "Claim", 5),
      ]);
    }
    return new Set([
      ...ranked((node) => node.node_type === "Claim" && node.importance === "core", 8),
      ...ranked((node) => benchmarkIds.has(node.id) && node.node_type !== "Claim", 6),
    ]);
  }

  function renderGraph({ preserveView = false } = {}) {
    const nodeIds = modeNodeIds(currentMode);
    const nodes = data.nodes.filter((node) => nodeIds.has(node.id));
    const edges = modeEdges(nodeIds, currentMode);
    const graphRect = graphSvg.getBoundingClientRect();
    const aspectRatio = graphRect.width > 0 && graphRect.height > 0 ? graphRect.width / graphRect.height : 1.6;
    const worldHeight = 1600 / Math.max(.72, Math.min(1.8, aspectRatio));
    const positions = layoutNodes(nodes, currentMode, worldHeight);
    const labelIds = labelIdsFor(nodes, currentMode);
    baseView = { x: 0, y: 0, w: 1600, h: worldHeight };
    renderedNodeIds = nodeIds;
    renderedEdgeIds = new Set(edges.map((edge) => edge.id));
    graphLayer.replaceChildren();

    const edgeFragment = document.createDocumentFragment();
    edges.forEach((edge) => {
      const source = positions.get(edge.source_id);
      const target = positions.get(edge.target_id);
      if (!source || !target) return;
      const line = svgElement("line", {
        x1: source.x,
        y1: source.y,
        x2: target.x,
        y2: target.y,
        class: `graph-edge edge-${edge.edge_type} ${argumentTypes.has(edge.edge_type) ? "argument" : "structural"} ${edge.assertion_level === "INFERRED" ? "inferred" : ""}`,
        "data-edge-id": edge.id,
      });
      edgeFragment.appendChild(line);
    });
    graphLayer.appendChild(edgeFragment);

    const nodeFragment = document.createDocumentFragment();
    nodes.forEach((node) => {
      const position = positions.get(node.id);
      const radius = nodeRadius(node, currentMode);
      const group = svgElement("g", {
        class: `node type-${node.node_type} ${warningIds.has(node.id) ? "warning" : ""}`,
        "data-node-id": node.id,
        role: "button",
        tabindex: "0",
        "aria-label": `${node.node_type}: ${node.label}`,
      });
      group.appendChild(nodeShape(node, position.x, position.y, radius));
      const title = svgElement("title");
      title.textContent = `${node.node_type} · ${node.label}`;
      group.appendChild(title);

      if (labelIds.has(node.id)) {
        const label = svgElement("text", { x: position.x + radius + 5, y: position.y + 4 });
        label.textContent = truncate(node.label, currentMode === "full" ? 26 : 34);
        group.appendChild(label);
      }
      if (benchmarkIds.has(node.id)) {
        const badge = svgElement("text", { class: "node-badge", x: position.x - radius - 2, y: position.y - radius - 5 });
        badge.textContent = "CORE";
        group.appendChild(badge);
      }
      group.addEventListener("click", (event) => {
        event.stopPropagation();
        selectNode(node.id);
      });
      group.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") selectNode(node.id);
      });
      nodeFragment.appendChild(group);
    });
    graphLayer.appendChild(nodeFragment);
    graphEmpty.hidden = nodes.length > 0;
    $("#graphCount").textContent = `${nodes.length} nodes · ${edges.length} edges`;
    if (!preserveView) resetView();
    updateGraphHighlight();
  }

  function updateGraphHighlight() {
    const connectedNodes = new Set();
    const connectedEdges = new Set();
    if (selectedNodeId) {
      connectedNodes.add(selectedNodeId);
      (incident.get(selectedNodeId) || []).forEach((edge) => {
        if (!renderedEdgeIds.has(edge.id)) return;
        connectedEdges.add(edge.id);
        connectedNodes.add(edge.source_id);
        connectedNodes.add(edge.target_id);
      });
    }
    graphLayer.querySelectorAll(".node").forEach((element) => {
      const id = element.dataset.nodeId;
      element.classList.toggle("selected", id === selectedNodeId);
      element.classList.toggle("connected", Boolean(selectedNodeId) && connectedNodes.has(id) && id !== selectedNodeId);
      element.classList.toggle("dimmed", Boolean(selectedNodeId) && !connectedNodes.has(id));
    });
    graphLayer.querySelectorAll(".graph-edge").forEach((element) => {
      const id = element.dataset.edgeId;
      element.classList.toggle("connected", connectedEdges.has(id));
      element.classList.toggle("dimmed", Boolean(selectedNodeId) && !connectedEdges.has(id));
    });
  }

  function formatValue(value) {
    if (value === null || value === undefined) return "—";
    if (typeof value === "object") return JSON.stringify(value, null, 2);
    if (Array.isArray(value)) return value.join(", ");
    return String(value);
  }

  function renderOverview() {
    const metrics = data.validation.metrics || {};
    const summary = data.evaluation.summary || {};
    inspector.innerHTML = `
      <div class="inspector-kicker">Canonical graph state</div>
      <h2 class="inspector-title">研报文字是载体，图才是可持续维护的语义状态。</h2>
      <p class="overview-copy">选择图中任意节点，右侧查看结构化字段和论证关系；含原文证据的节点会同步跳到左侧报告页。</p>
      <section class="inspect-section">
        <h3>验证摘要</h3>
        <div class="overview-metric"><strong>${escapeHtml(data.validation.status || "—")}</strong><span>${data.validation.error_count} errors · ${data.validation.warning_count} warnings</span></div>
        <div class="overview-metric"><strong>${Math.round((metrics.semantic_evidence_coverage || 0) * 100)}%</strong><span>语义节点证据覆盖率</span></div>
        <div class="overview-metric"><strong>${summary.semantic?.passed || 0}/${summary.semantic?.total || 0}</strong><span>人工核心语义清单</span></div>
        <div class="overview-metric"><strong>${summary.data?.passed || 0}/${summary.data?.total || 0}</strong><span>人工核心数字清单</span></div>
        <div class="overview-metric"><strong>${summary.relations?.passed || 0}/${summary.relations?.total || 0}</strong><span>人工核心关系清单</span></div>
      </section>
      <section class="inspect-section">
        <h3>状态与模型</h3>
        <dl class="field-grid">
          <dt>抽取</dt><dd>${escapeHtml(data.run.model)}</dd>
          <dt>关系验证</dt><dd>${escapeHtml(data.run.verification_model)}</dd>
          <dt>状态哈希</dt><dd>${escapeHtml(data.graph.state_hash)}</dd>
          <dt>来源对象</dt><dd>${data.counts.sources}</dd>
          <dt>OPAQUE</dt><dd>${data.coverage.opaque_source_object_ids?.length || 0}</dd>
        </dl>
      </section>
      <section class="inspect-section">
        <h3>解释边界</h3>
        <div class="truth-note">63/63 仅表示本报告人工核心清单全部命中，不等于全报告的穷尽召回率或精确率为 100%。当前仍有 ${data.validation.warning_count} 个验证警告和 ${data.coverage.opaque_source_object_ids?.length || 0} 个图像型不可解析来源对象。</div>
      </section>`;
  }

  function relatedNodeId(edge, nodeId) {
    return edge.source_id === nodeId ? edge.target_id : edge.source_id;
  }

  function nodeEvidence(node) {
    const direct = node.evidence || [];
    const relationEvidence = (incident.get(node.id) || []).flatMap((edge) => edge.evidence || []);
    const seen = new Set();
    return [...direct, ...relationEvidence].filter((item) => {
      const key = `${item.source_object_id}:${item.quote || ""}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }

  function renderInspector(node) {
    const excluded = new Set(["id", "node_type", "label", "evidence", "status", "benchmark_matches"]);
    const fields = Object.entries(node).filter(([key]) => !excluded.has(key));
    const evidence = nodeEvidence(node);
    const relations = (incident.get(node.id) || []).filter((edge) => nodeById.has(relatedNodeId(edge, node.id)));
    const badges = [
      `<span class="badge">${escapeHtml(node.node_type)}</span>`,
      node.importance ? `<span class="badge ${node.importance === "core" ? "core" : ""}">${escapeHtml(node.importance)}</span>` : "",
      benchmarkIds.has(node.id) ? `<span class="badge pass">core benchmark</span>` : "",
      warningIds.has(node.id) ? `<span class="badge warning">validation warning</span>` : "",
    ].join("");
    inspector.innerHTML = `
      <div class="inspector-kicker">Selected graph object</div>
      <h2 class="inspector-title">${escapeHtml(node.label)}</h2>
      <div class="id-line">${escapeHtml(node.id)}</div>
      <div class="badge-row">${badges}</div>
      ${node.benchmark_matches?.length ? `<section class="inspect-section"><h3>人工核心清单命中</h3>${node.benchmark_matches.map((item) => `<div class="overview-copy"><b>${escapeHtml(item.id)}</b> · ${escapeHtml(item.description)}</div>`).join("")}</section>` : ""}
      <section class="inspect-section">
        <h3>结构化字段</h3>
        <dl class="field-grid">${fields.map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(formatValue(value))}</dd>`).join("")}</dl>
      </section>
      <section class="inspect-section">
        <h3>原文证据 · ${evidence.length}</h3>
        ${evidence.length ? evidence.map((item) => {
          const source = sourceById.get(item.source_object_id);
          return `<article class="evidence-card" data-source-id="${escapeHtml(item.source_object_id)}" tabindex="0">
            <div class="source-id">${escapeHtml(item.source_object_id)} · P${source?.page || "?"} / B${source?.block || "?"}</div>
            <div class="quote">${escapeHtml(item.quote || source?.text || "")}</div>
          </article>`;
        }).join("") : `<p class="overview-copy">该类型节点没有直接证据；可沿关系查看其相邻事实或结论。</p>`}
      </section>
      <section class="inspect-section">
        <h3>相邻关系 · ${relations.length}</h3>
        <div class="relation-list">${relations.slice(0, 80).map((edge) => {
          const otherId = relatedNodeId(edge, node.id);
          const other = nodeById.get(otherId);
          const direction = edge.source_id === node.id ? "→" : "←";
          return `<button class="relation-button" data-node-id="${escapeHtml(otherId)}"><span>${direction} ${escapeHtml(edge.edge_type)}</span><strong>${escapeHtml(other?.label || otherId)}</strong></button>`;
        }).join("")}</div>
      </section>`;

    inspector.querySelectorAll(".evidence-card").forEach((element) => {
      const activate = () => showSource(element.dataset.sourceId);
      element.addEventListener("click", activate);
      element.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") activate();
      });
    });
    inspector.querySelectorAll(".relation-button").forEach((button) => {
      button.addEventListener("click", () => selectNode(button.dataset.nodeId));
    });
  }

  function selectNode(nodeId, { keepMode = false } = {}) {
    const node = nodeById.get(nodeId);
    if (!node) return;
    if (!renderedNodeIds.has(nodeId) && !keepMode) {
      currentMode = "full";
      updateModeButtons();
      renderGraph();
    }
    selectedNodeId = nodeId;
    renderInspector(node);
    updateGraphHighlight();
    const evidence = nodeEvidence(node);
    if (evidence.length) showSource(evidence[0].source_object_id);
  }

  function showSource(sourceId) {
    const source = sourceById.get(sourceId);
    if (!source) return;
    currentSourceId = sourceId;
    currentPage = Math.max(1, Math.min(7, Number(source.page) || 1));
    reportImage.src = `assets/report-page-${currentPage}.png`;
    reportImage.alt = `原始研报第 ${currentPage} 页`;
    pageIndicator.textContent = `${currentPage} / 7`;
    sourceMeta.innerHTML = `<span>${escapeHtml(source.id)} · Block ${escapeHtml(source.block)}</span><span>${escapeHtml(source.processing_status)}</span>`;
    sourceText.textContent = source.text || "该来源对象没有可用文本。";
    const linkedIds = unique(sourceToNodes.get(sourceId) || []);
    sourceLinked.innerHTML = linkedIds.slice(0, 30).map((id) => {
      const linked = nodeById.get(id);
      return `<button class="source-node-link" data-node-id="${escapeHtml(id)}">${escapeHtml(linked?.node_type || "Node")} · ${escapeHtml(truncate(linked?.label || id, 34))}</button>`;
    }).join("");
    sourceLinked.querySelectorAll("button").forEach((button) => {
      button.addEventListener("click", () => selectNode(button.dataset.nodeId));
    });
  }

  function showPage(page) {
    currentPage = Math.max(1, Math.min(7, page));
    reportImage.src = `assets/report-page-${currentPage}.png`;
    reportImage.alt = `原始研报第 ${currentPage} 页`;
    pageIndicator.textContent = `${currentPage} / 7`;
    const sources = data.source_objects.filter((source) => Number(source.page) === currentPage);
    const preferred = sources.find((source) => source.processing_status === "OPAQUE")
      || [...sources].sort((a, b) => Number(b.candidate_count || 0) - Number(a.candidate_count || 0))[0];
    if (preferred) {
      currentSourceId = preferred.id;
      sourceMeta.innerHTML = `<span>PAGE ${currentPage} · ${sources.length} source blocks</span><span>${escapeHtml(preferred.processing_status)}</span>`;
      sourceText.textContent = preferred.text || "该页来源对象没有可用文本。";
      const linkedIds = unique(sourceToNodes.get(preferred.id) || []);
      sourceLinked.innerHTML = linkedIds.slice(0, 30).map((id) => `<button class="source-node-link" data-node-id="${escapeHtml(id)}">${escapeHtml(nodeById.get(id)?.node_type || "Node")} · ${escapeHtml(truncate(nodeById.get(id)?.label || id, 34))}</button>`).join("");
      sourceLinked.querySelectorAll("button").forEach((button) => button.addEventListener("click", () => selectNode(button.dataset.nodeId)));
    }
  }

  function updateModeButtons() {
    document.querySelectorAll(".mode-button").forEach((button) => button.classList.toggle("active", button.dataset.mode === currentMode));
  }

  function resetView() {
    setViewBox({ ...baseView });
  }

  function zoom(factor, clientX, clientY) {
    const rect = graphSvg.getBoundingClientRect();
    const px = clientX === undefined ? .5 : (clientX - rect.left) / rect.width;
    const py = clientY === undefined ? .5 : (clientY - rect.top) / rect.height;
    const nextW = Math.max(260, Math.min(3200, viewBox.w * factor));
    const nextH = nextW * (viewBox.h / viewBox.w);
    const worldX = viewBox.x + px * viewBox.w;
    const worldY = viewBox.y + py * viewBox.h;
    setViewBox({ x: worldX - px * nextW, y: worldY - py * nextH, w: nextW, h: nextH });
  }

  function search(query) {
    const normalized = query.trim().toLowerCase();
    if (!normalized) {
      searchResults.hidden = true;
      searchResults.replaceChildren();
      return;
    }
    const nodeMatches = data.nodes
      .map((node) => ({ type: "node", item: node, score: `${node.label} ${node.id} ${node.object_text || ""}`.toLowerCase().includes(normalized) ? 1 : 0 }))
      .filter((entry) => entry.score)
      .slice(0, 8);
    const sourceMatches = data.source_objects
      .filter((source) => `${source.id} ${source.text}`.toLowerCase().includes(normalized))
      .slice(0, 4)
      .map((source) => ({ type: "source", item: source }));
    const matches = [...nodeMatches, ...sourceMatches];
    searchResults.innerHTML = matches.length ? matches.map((entry) => {
      if (entry.type === "node") return `<button class="search-result" data-node-id="${escapeHtml(entry.item.id)}"><strong>${escapeHtml(truncate(entry.item.label, 62))}</strong><span>${escapeHtml(entry.item.node_type)} · ${escapeHtml(entry.item.id)}</span></button>`;
      return `<button class="search-result" data-source-id="${escapeHtml(entry.item.id)}"><strong>${escapeHtml(truncate(entry.item.text, 62))}</strong><span>SOURCE · P${entry.item.page} / B${entry.item.block}</span></button>`;
    }).join("") : `<div class="search-result"><strong>没有匹配项</strong><span>可搜索标签、ID 或原文片段</span></div>`;
    searchResults.hidden = false;
    searchResults.querySelectorAll("[data-node-id]").forEach((button) => button.addEventListener("click", () => {
      selectNode(button.dataset.nodeId);
      searchResults.hidden = true;
    }));
    searchResults.querySelectorAll("[data-source-id]").forEach((button) => button.addEventListener("click", () => {
      showSource(button.dataset.sourceId);
      searchResults.hidden = true;
    }));
  }

  function populateChrome() {
    $("#reportTitle").textContent = data.document.title;
    $("#reportSubtitle").textContent = `${data.document.publisher} · ${data.document.published_at} · ${data.document.issuer} · state ${data.graph.state_hash.slice(0, 12)}… · ${liveData ? "LIVE API" : "OFFLINE SNAPSHOT"}`;
    $("#nodeStat").textContent = data.counts.nodes.toLocaleString("zh-CN");
    $("#edgeStat").textContent = data.counts.edges.toLocaleString("zh-CN");
    $("#validationStat").textContent = `${data.validation.error_count} / ${data.validation.warning_count}`;
    const evaluationTotal = Object.values(data.evaluation.summary).reduce((sum, item) => sum + Number(item.passed || 0), 0);
    const evaluationMax = Object.values(data.evaluation.summary).reduce((sum, item) => sum + Number(item.total || 0), 0);
    $("#benchmarkStat").textContent = `${evaluationTotal}/${evaluationMax}`;
    $("#pdfLink").href = liveData ? "/api/report.pdf" : "../../../sources/broker_reports/jiangbolong_2025/aijian_jiangbolong_2025-12-31.pdf";
    document.title = `${config.name || "TCEG Evidence Graph"} · 江波龙研报`;
  }

  document.querySelectorAll(".mode-button").forEach((button) => {
    button.addEventListener("click", () => {
      currentMode = button.dataset.mode;
      selectedNodeId = null;
      updateModeButtons();
      renderGraph();
      renderOverview();
    });
  });
  $("#prevPage").addEventListener("click", () => showPage(currentPage - 1));
  $("#nextPage").addEventListener("click", () => showPage(currentPage + 1));
  $("#zoomIn").addEventListener("click", () => zoom(.78));
  $("#zoomOut").addEventListener("click", () => zoom(1.28));
  $("#resetView").addEventListener("click", resetView);
  searchInput.addEventListener("input", () => search(searchInput.value));
  searchInput.addEventListener("keydown", (event) => {
    if (event.key === "Escape") searchResults.hidden = true;
    if (event.key === "Enter") searchResults.querySelector("button")?.click();
  });
  document.addEventListener("click", (event) => {
    if (!event.target.closest(".search-wrap")) searchResults.hidden = true;
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "/" && document.activeElement !== searchInput) {
      event.preventDefault();
      searchInput.focus();
    }
    if (event.key === "Escape" && document.activeElement !== searchInput) {
      selectedNodeId = null;
      updateGraphHighlight();
      renderOverview();
    }
  });
  graphSvg.addEventListener("wheel", (event) => {
    event.preventDefault();
    zoom(event.deltaY > 0 ? 1.12 : .89, event.clientX, event.clientY);
  }, { passive: false });
  graphSvg.addEventListener("pointerdown", (event) => {
    if (event.target.closest(".node")) return;
    graphSvg.setPointerCapture(event.pointerId);
    graphSvg.classList.add("dragging");
    dragStart = { clientX: event.clientX, clientY: event.clientY, view: { ...viewBox } };
  });
  graphSvg.addEventListener("pointermove", (event) => {
    if (!dragStart) return;
    const rect = graphSvg.getBoundingClientRect();
    const dx = (event.clientX - dragStart.clientX) * dragStart.view.w / rect.width;
    const dy = (event.clientY - dragStart.clientY) * dragStart.view.h / rect.height;
    setViewBox({ ...dragStart.view, x: dragStart.view.x - dx, y: dragStart.view.y - dy });
  });
  graphSvg.addEventListener("pointerup", () => {
    dragStart = null;
    graphSvg.classList.remove("dragging");
  });
  graphSvg.addEventListener("click", (event) => {
    if (event.target === graphSvg || event.target === graphLayer) {
      selectedNodeId = null;
      updateGraphHighlight();
      renderOverview();
    }
  });

  populateChrome();
  updateModeButtons();
  showPage(1);
  renderOverview();
  renderGraph();
  window.TCEG_VIEWER = {
    selectNode,
    showSource,
    showPage,
    setMode(mode) {
      currentMode = mode;
      updateModeButtons();
      renderGraph();
    },
    getState() {
      return { currentMode, currentPage, currentSourceId, selectedNodeId, renderedNodes: renderedNodeIds.size, renderedEdges: renderedEdgeIds.size };
    },
  };
})();
