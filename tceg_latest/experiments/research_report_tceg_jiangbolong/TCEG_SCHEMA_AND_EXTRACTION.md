# TCEG 图 Schema、抽取算法与前端解释

本文说明当前江波龙券商研报实验中，TCEG 图究竟保存了什么、如何从 PDF 构建、哪些步骤是真实算法、哪些步骤包含固定规则，以及前端不同簇和 PDF 下方 `EXTRACTED` 状态的准确含义。

对应实现与数据：

- 图状态：[`tceg.json`](tceg.json)
- 正式 Schema：[`research_report_tceg.schema.json`](../../schemas/research_report_tceg.schema.json)
- 抽取主流程：[`extract_research_report_tceg.py`](../../tools/extract_research_report_tceg.py)
- 公共来源处理：[`research_report_tceg_core.py`](../../tools/research_report_tceg_core.py)
- 独立验证器：[`validate_research_report_tceg.py`](../../tools/validate_research_report_tceg.py)
- 前端数据构建：[`build_tceg_visualization_data.py`](../../tools/build_tceg_visualization_data.py)
- 前端图布局与交互：[`viewer.js`](visualization/viewer.js)

## 1. 先给结论：这是什么，不是什么

当前实现是一个“模型提出候选、确定性程序决定能否进入规范图、独立验证调用复核推断关系”的混合建图系统。

它不是纯 Python 规则抽取，因为 Claim、Event、非规则 DataPoint 和大量论证关系需要语言模型识别；它也不是让大模型直接生成最终 JSON，因为候选必须经过来源 ID、原文 quote、数字字形、单位尺度、引用完整性、关系复核和 DAG 等确定性检查后才能写入图。

它同样不是完全通用、已经解决所有研报版式的生产系统。当前代码中仍包含格式敏感的规则和人工构件：

- 固定财务指标词表和“五期表头”解析逻辑；
- 针对当前报告中 iPhone 容量表的正则表达式；
- 人工定义的 63 项核心评测清单；
- 按节点类型固定中心位置的前端布局；
- 本次运行直接导入了已经保存的 Luna 候选文件，而不是在主脚本中重新调用 Luna 完成候选抽取；
- PDF 图片型图表目前没有 OCR/多模态数值恢复。

因此，准确描述应当是：**已有一条真实、可执行、可验证的混合建图管线；当前样本中的部分召回能力仍由固定规则和保存的模型候选支撑，尚不是任意研报无修改运行即可保证无损建图的通用算法。**

## 2. TCEG 的总体结构

TCEG 将一个研究状态分成四层：

```text
Document
  └── SourceObject[]                    原始证据层
          ↑
          └──────── EVIDENCED_BY ────── Claim / DataPoint / Event
                                               │
Entity / Metric / Period  ← ABOUT / MEASURES / VALID_DURING
                                               │
                                               └── PREMISE_OF → ReasoningStep
                                                                        │
                                                               CONCLUDES ↓
                                                                      Claim
```

此外，根对象还保存抽取运行记录、覆盖状态、拒绝候选和规范图内容哈希。交付文件不是只有 `nodes + edges`；来源对象和运行审计也属于完整交付包，但只有规范图内容参与 `state_hash`。

## 3. 根对象字段

正式版本为 `research-report-tceg-0.1`。根对象禁止未声明字段。

| 字段 | 作用 |
|---|---|
| `schema_version` | 指定读取和校验该状态所使用的 Schema 版本。 |
| `graph_id` | 当前配置下的图实例身份；由文档、抽取模型和验证模型共同生成，更换模型会改变该 ID。 |
| `state_hash` | 规范图内容哈希。对 `schema_version + graph_id + document + source_objects + nodes + edges` 的规范化内容计算 SHA-256；运行日志、覆盖摘要和拒绝记录不参与哈希。 |
| `document` | 原始研报文件及其来源元数据。 |
| `source_objects` | 从 PDF 文本层登记的不可漂移证据对象。 |
| `nodes` | 实体、指标、期间、数字、事实、事件和推理步骤。 |
| `edges` | 节点之间以及节点到来源对象之间的有向关系。 |
| `extraction_run` | 本次抽取使用的模型、API 调用、检查点和规则解析数量。 |
| `coverage_manifest` | 来源对象处理状态和语义节点证据覆盖情况。 |
| `rejected_candidates` | 未进入规范图的候选及拒绝原因。 |

### 3.1 `document`

| 字段 | 作用 |
|---|---|
| `id` | 由原始文件哈希生成的稳定文档 ID。 |
| `title` | 研报标题。 |
| `source_type` | 来源类型；Schema 允许 `broker_research_pdf`、`research_markdown`、`research_text`。 |
| `local_path` | 本地原始文件路径。 |
| `sha256` | 原始文件内容哈希；验证器会重新计算并比较。 |
| `source_url` | 原始公开来源地址。 |
| `publisher` | 研报发布机构。 |
| `published_at` | 发布日期。 |
| `issuer` | 研报覆盖的主要公司。 |

### 3.2 `extraction_run`

| 字段 | 作用 |
|---|---|
| `run_id` | 单次运行 ID。 |
| `started_from` | 输入状态类型；当前为历史研报。 |
| `finished_at` | 完成时间。 |
| `model` | 候选抽取模型名称。 |
| `verification_model` | 跨段关系提议和独立验证使用的模型。 |
| `extractor` | 抽取程序版本。 |
| `api_calls` | 本次实际发生的 API 调用审计记录。 |
| `chunk_count` | 候选输入块数量；使用外部候选文件时记为 1。 |
| `resumed_candidate_chunks` | 从检查点恢复、未重新调用模型的候选块数量。 |
| `candidate_input` | `llm_api` 或候选文件路径。当前指向 `luna_extraction_audit.json`。 |
| `deterministic_table_points_created` | 确定性财务表解析新建的 DataPoint 数量。 |
| `deterministic_capacity_points_created` | 确定性容量表解析新建的 DataPoint 数量。 |
| `semantic_contract` | 对本次混合抽取约束的摘要。 |

每条 `api_calls` 记录包含：

| 字段 | 作用 |
|---|---|
| `id` | 调用序号。 |
| `purpose` | 调用用途和批次，例如跨段关系提议或关系验证。 |
| `model` | 实际调用的模型。 |
| `attempt` | 重试序号。 |
| `duration_seconds` | 调用耗时。 |
| `prompt_sha256` / `response_sha256` | 提示词和响应的哈希；不在图中保存密钥。 |
| `finish_reason` | 模型完成原因；若被截断，管线拒绝接受不完整结果。 |
| `json_repair_applied` | 是否做过 JSON 修复。 |
| `usage.prompt_tokens` / `completion_tokens` / `total_tokens` | Token 使用量。 |
| `status` | 调用状态。 |
| `stage` | 候选抽取或关系推理阶段。 |

### 3.3 `coverage_manifest`

| 字段 | 作用 |
|---|---|
| `total_source_objects` | 来源对象总数。 |
| `terminal_source_objects` | 已被赋予某种分类状态的对象数。代码沿用 terminal 命名，但 `NEEDS_REVIEW` 也被计入，因此不能理解为“已经无需后续处理”。 |
| `source_object_status_counts` | 各处理状态的数量。 |
| `source_processing_coverage` | `terminal / total`，更准确地说是来源对象“状态分类覆盖率”；不是处理完成率，也不是事实召回率。 |
| `semantic_nodes` | Claim、DataPoint、Event 的数量。 |
| `semantic_nodes_with_evidence` | 具有 evidence 的语义节点数。 |
| `semantic_evidence_coverage` | 上述两者之比。它只衡量已经进入图的节点是否有证据。 |
| `opaque_source_object_ids` | `processing_status=OPAQUE` 的来源对象 ID；其来源可能是模型 review 为 opaque，也可能是未被节点引用的 `figure_caption`，不能仅凭该字段断言文本层完全不可读。 |
| `needs_review_source_object_ids` | 没有形成已接受语义节点且无法确定为无语义对象的来源对象 ID。 |
| `definition` | 覆盖率口径说明。 |

### 3.4 `rejected_candidates`

| 字段 | 作用 |
|---|---|
| `id` | 拒绝记录 ID。 |
| `candidate_type` | `claim`、`data_point`、`event`、`relation` 等候选类型。 |
| `chunk_id` | 候选来自哪个抽取块。 |
| `reason` | 确定性拒绝原因，例如证据不存在、数字缺少期间、置信度类型非法或关系形成环。 |
| `candidate` | 被拒绝的原始候选，供调试和误差分析。 |

## 4. 原始证据层：`source_objects`

PDF 首先被拆成来源对象。来源对象不是大模型生成的摘要，而是对 PDF 文本层的登记。

| 字段 | 作用 |
|---|---|
| `id` | 在同一原文件、同一文本提取器和切分参数下稳定的来源对象 ID，例如 `SO_P001_B004` 表示第 1 页第 4 块。工具版本或切分参数变化可能改变块号。 |
| `document_id` | 所属文档。 |
| `object_type` | `paragraph`、`table_like`、`figure_caption`、`legal` 或 `other`。当前分类由文本结构启发式规则给出。 |
| `sequence` | 在整份报告中的顺序。 |
| `raw_text` | `pdftotext -layout` 得到的原始块文本。 |
| `normalized_text` | 修复常见中文字符间空格、统一空白后的匹配文本。原始文本仍然保留。 |
| `sha256` | `raw_text` 的哈希。 |
| `locator.page` | PDF 页码。 |
| `locator.block` | 页内块号。 |
| `locator.char_start` / `char_end` | 在该页文本中的字符范围；定位失败时允许为 `null`。 |
| `processing_status` | `EXTRACTED`、`NO_CLAIM`、`OPAQUE`、`NEEDS_REVIEW` 或 `ERROR`。 |
| `candidate_count` | 最终被接受节点中，有多少条 evidence 引用了该来源对象。它不是模型原始候选总数。 |
| `irrelevant_reason` | 未形成语义节点时的原因。 |
| `metadata` | 来源处理扩展信息；当前保存 `extraction_method=pdftotext-layout`。 |

长来源对象可以被进一步拆成较小的 `extraction view` 交给模型，但这些 view 不会替换原始 source object。最终 evidence 仍然引用原始稳定 ID。

## 5. 节点 Schema

所有节点至少包含：

| 字段 | 作用 |
|---|---|
| `id` | 根据规范语义内容生成的稳定 ID。 |
| `node_type` | 节点类型。 |
| `label` | 人可读标签。 |
| `status` | `active`、`needs_review` 或 `rejected`。当前规范图中主要使用 `active`。 |

### 5.1 节点类型与专属字段

| 节点类型 | 字段 | 作用 |
|---|---|---|
| `Entity` | `entity_type` | 公司、产品、行业、地区、机构或其他实体。 |
| `Metric` | `canonical_name` | 指标规范名称，用于让多个 DataPoint 复用同一指标。 |
| `Period` | `normalized_label` | 规范期间，例如 `2025E`、`2025Q4`。 |
| `Claim` | `claim_role` | observation、forecast、interpretation、valuation、recommendation、risk、guidance。 |
| `Claim` | `modality` | actual、forecast、opinion、recommendation、risk、conditional。 |
| `Claim` | `polarity` / `importance` | 命题方向及 core、supporting、context 重要性。 |
| `Claim` | `subject_ref` / `predicate` / `object_text` | 主体、规范谓词和命题宾语。 |
| `Claim` | `metric_ref` / `period_ref` | 可选指标和期间上下文。 |
| `Claim` | `assertion_level` / `evidence` | 原文显式表达还是推断，以及原文证据。当前 Claim 本身均按显式研报表达入图。 |
| `DataPoint` | `subject_ref` / `metric_ref` / `period_ref` | 数字的主体、指标和期间；验证器要求三者完整。 |
| `DataPoint` | `qualifier` | actual、forecast、market_data、assumption 等数字语境。 |
| `DataPoint` | `value` | 原始字形、规范数值、单位、币种和尺度。 |
| `DataPoint` | `extraction_method` | 对规则解析生成的数字，记录具体确定性解析器。 |
| `DataPoint` | `assertion_level` / `evidence` | 数字是否为原文显式表达以及其证据。 |
| `Event` | `category` | supply、demand、price、strategy、technology、competition、macro 或 other。 |
| `Event` | `subject_ref` / `period_ref` | 事件主体和发生期间。 |
| `Event` | `assertion_level` / `evidence` | 表达层级和证据。 |
| `ReasoningStep` | `reasoning_method` | supports、causes、depends_on 等推理方式。 |
| `ReasoningStep` | `premise_node_ids` | 该推理步骤的前提节点。 |
| `ReasoningStep` | `conclusion_claim_ids` | 该步骤导向的结论 Claim。 |
| `ReasoningStep` | `rationale` | 可审计的关系理由。 |
| `ReasoningStep` | `assertion_level` / `verification` | 显式或推断，以及独立关系验证记录。 |
| `Assumption` | 公共字段 | Schema 预留的假设节点类型；当前江波龙图没有生成该类型。 |

正式 JSON Schema 对 `node` 使用 `additionalProperties: true`。这允许不同节点类型携带专属字段，但也意味着“节点不允许任何未知字段”目前不是严格 Schema 保证，而主要由构建器和验证器约束。

### 5.2 `evidence`

Claim、DataPoint、Event 通过 evidence 回到来源对象。

| 字段 | 作用 |
|---|---|
| `source_object_id` | 被引用的来源对象。 |
| `quote` | 规范化后必须是该来源对象 `normalized_text` 的连续片段；当前 `exact` 并不表示直接对 `raw_text` 逐字匹配。 |
| `quote_sha256` | 规范化 quote 的哈希。 |
| `match_mode` | `exact` 或 `whitespace_normalized`。 |

同一引用还会实体化为 `EVIDENCED_BY` 边。验证器要求节点 evidence 集合与这些边完全一致。

### 5.3 `value`

| 字段 | 作用 |
|---|---|
| `kind` | `scalar`、`range` 或 `text`。 |
| `raw` | 原文中的数字字形，例如 `239.95`、`20%-30%`。 |
| `normalized_decimal` | 标量的十进制字符串；不提前乘尺度。 |
| `range_low` / `range_high` | 区间上下界。 |
| `unit` | 基础单位，例如 CNY、USD、CNY/share、percent、GB、multiple。 |
| `currency` | CNY、USD 或 `null`。 |
| `scale` | 从原数字到基础单位的倍率，例如“亿元”为 `100000000`，“百分比”为 `0.01`。 |
| `dimensions` | 附加维度，例如容量升级的 `before`、`after`、`reported`。 |

例如 `239.95 亿元` 被保存为 `normalized_decimal=239.95`、`unit=CNY`、`scale=100000000`，计算值为 `23,995,000,000 CNY`。

### 5.4 `verification`

推断关系及对应 ReasoningStep 可包含：

| 字段 | 作用 |
|---|---|
| `verdict` | `accept` 或 `reject`。 |
| `confidence` | 独立验证模型直接给出的 0–1 JSON 数字。 |
| `reason` | 接受或拒绝理由。 |
| `model` | 验证模型名称。 |

## 6. 边 Schema

所有边至少包含：

| 字段 | 作用 |
|---|---|
| `id` | 由关系类型、起点和终点生成的稳定 ID。 |
| `edge_type` | 关系谓词。 |
| `source_id` / `target_id` | 有向边起点和终点。 |
| `assertion_level` | `EXPLICIT` 或 `INFERRED`。 |
| `confidence` | 0–1 数字。结构边通常为 1；模型关系使用模型给出的置信度。 |
| `status` | `active`、`needs_review` 或 `rejected`。 |

关系边还可能包含：

| 字段 | 作用 |
|---|---|
| `rationale` | 关系为什么成立。 |
| `evidence` | 显式关系的原文证据。 |
| `extraction_origin` | `within_chunk` 或 `cross_chunk`。 |
| `verification` | 推断关系的独立复核结果。 |
| `evidence_quote_sha256` | `EVIDENCED_BY` 边对应的 quote 哈希。 |

### 6.1 边类型语义

| 边类型 | 方向与含义 |
|---|---|
| `EVIDENCED_BY` | 语义节点 → SourceObject；该节点由哪个来源块中的 quote 支撑。 |
| `ABOUT` | Claim、DataPoint 或 Event → Entity；该语义对象关于谁。 |
| `MEASURES` | DataPoint 或 Claim → Metric；涉及哪个指标。 |
| `VALID_DURING` | 语义对象 → Period；在哪个期间成立。 |
| `HAS_DATA` | Claim → DataPoint；命题包含或引用哪个结构化数字。 |
| `SUPPORTS` | 前提 → 结论；前者为后者提供实质支持。 |
| `CONTRADICTS` | 命题 → 命题；语义上冲突。 |
| `CAUSES` | 原因 → 结果；要求明确因果方向。 |
| `AFFECTS` | 影响因素 → 被影响对象；弱于充分因果。 |
| `DEPENDS_ON` | 必要前提 → 依赖该前提的结论；即 target 依赖 source。当前验证提示也要求 source 是 target 的必要假设或前提。 |
| `PREMISE_OF` | 前提节点 → ReasoningStep。 |
| `CONCLUDES` | ReasoningStep → 结论 Claim。 |
| `ASSUMES` | 结论或推理 → Assumption。当前样本未使用。 |
| `SAME_AS` | 对象 → 等价对象，用于身份归并。当前样本未使用。 |

Schema 允许 14 种边。当前图实际出现 10 种：`ABOUT`、`CAUSES`、`CONCLUDES`、`DEPENDS_ON`、`EVIDENCED_BY`、`HAS_DATA`、`MEASURES`、`PREMISE_OF`、`SUPPORTS`、`VALID_DURING`。

与节点相同，正式 Schema 对 `edge` 使用 `additionalProperties: true`；可选关系字段主要由构建器和验证器约束。

## 7. 从 PDF 到 TCEG 的完整抽取过程

### 步骤 1：登记文档

程序计算原始 PDF SHA-256，以此生成文档 ID，并保存标题、发布方、日期、公司、原始路径和来源 URL。

### 步骤 2：构建 Source Graph

PDF 通过 `pdftotext -layout -enc UTF-8` 提取文本。程序按页和空行划分块，并对超过字符上限的块继续按行拆分。每个块得到稳定 ID、页码、块号、字符范围、原文、规范化文本和哈希。

`object_type` 是规则分类：

- 包含声明/评级说明等关键词 → `legal`；
- 以图或图表编号开头 → `figure_caption`；
- 多行且数字密集 → `table_like`；
- 其余 → `paragraph`。

### 步骤 3：生成模型抽取视图

过长来源块会被拆成较短 extraction view，多个 view 仍共享原始 source object ID。随后按最大字符数打包成模型 chunk。

### 步骤 4：产生语义候选

程序支持两种路径：

1. `llm_api`：逐 chunk 调用 OpenAI-compatible API；
2. `--candidate-file`：导入外部生成并保存的候选文件，再执行同一套确定性审计。

本次江波龙正式图走第 2 条路径，候选输入为 `luna_extraction_audit.json`。其中有 244 个候选：89 Claim、110 DataPoint、16 Event、29 Relation。也就是说，本次主脚本的候选阶段没有重新调用 Luna；Luna 结果是一个保存的输入产物。代码具备直接 API 抽取能力，但这个具体状态不是从零实时重跑 Luna 得到的。

### 步骤 5：确定性候选审计

模型候选不能直接写图。程序逐项执行：

1. evidence 的 `source_object_id` 必须存在并属于当前 chunk；
2. quote 会先做相同的文本规范化，然后与来源对象的 `normalized_text` 比较；`exact` 表示规范化 quote 是 `normalized_text` 的连续子串，`whitespace_normalized` 表示双方去除所有空白后连续匹配；这里不是直接对 `raw_text` 比较；
3. evidence quote 计算哈希；
4. DataPoint 的 `value` 必须满足标量、区间或文本格式；
5. `raw` 中所有数字字形必须出现在 evidence 中；
6. 单位和尺度按原文字样规范化；
7. DataPoint 必须拥有 Metric 和 Period；实际、预测和假设数字缺少主体时才回退到报告 issuer；
8. 实体、指标和期间按规范标签去重；
9. 置信度只接受真正的 JSON number，不把 high/medium/low 映射成数值；
10. 不合法候选写入 `rejected_candidates`，不会静默进入图。

### 步骤 6：确定性表格展开

为了避免模型漏掉规则表格的大量单元格，代码运行两类规则解析器：

- 周期财务表解析器：识别至少五个 `20xx/20xxA/20xxE` 表头，使用固定财务指标词表逐行抽取；本次新建 380 个 DataPoint；
- iPhone 容量表解析器：使用产品、日期、内存和存储容量正则，并拆分“从 A 向 B 升级”的 before/after 端点；本次新建 34 个 DataPoint。

规则解析生成的 DataPoint 不经过第 5 步的 `canonical_evidence()` 候选接口，而是直接从已经登记的 `normalized_text` 行或连续片段构造 `match_mode=exact` 的 evidence，并从正则命中的原数字构造值、主体、指标和期间。随后统一验证器仍会重新检查 quote、数字字形、三类上下文、证据边一致性和数值格式。

这一步是真实执行的确定性算法，但也是当前最明显的格式敏感部分。它不是伪造数据，却不能自然覆盖任意券商的任意表格。

### 步骤 7：补全跨段关系

程序把已经通过证据门的 Claim 和 Event 压缩后交给关系模型，为核心结论和风险寻找跨段前提。模型只能引用已有 node ID，不能创造新事实。

### 步骤 8：独立验证调用复核推断关系

所有 `INFERRED` 关系由单独的验证调用和专用验证提示再次判断。只有 `verdict=accept` 且验证置信度不低于 0.65 才能进入图。本次有 106 个推断关系进入验证，69 个接受，37 个拒绝。

这里的“独立”首先指验证调用不直接复用提议结果的判断，而是重新接收关系两端命题、证据和候选理由。模型身份并不始终独立：当前配置中，Luna 提出的片段内关系由 Gemini 复核，属于跨模型；Gemini 提出的跨段关系仍由 Gemini 在另一批次、另一提示中复核，属于同模型的独立验证 pass，而不是第二个不同模型。

### 步骤 9：实体化 ReasoningStep 并防环

每条进入图、且目标为 Claim 的论证关系都会生成一个 ReasoningStep：

```text
前提 --PREMISE_OF--> ReasoningStep --CONCLUDES--> Claim
```

在写入关系前，程序检查新边是否使论证关系形成有向环；会形成环的候选被拒绝。

### 步骤 10：计算来源覆盖状态

程序根据最终已接受节点实际引用了哪些 source object，计算每个来源对象的处理状态。详细规则见第 10 节。

### 步骤 11：计算状态哈希并输出产物

程序对规范状态计算 `state_hash`，同时输出：

- `source_graph.json`：原始来源对象；
- `candidates.json`：候选、关系提议、接受和拒绝结果；
- `tceg.json`：规范图状态；
- `extraction_trace.json`：调用和运行轨迹；
- `rejected_candidates`：图内拒绝记录。

### 步骤 12：独立验证与人工核心清单评测

验证器不信任抽取模型，重新检查 Schema、文件哈希、唯一 ID、引用目标、quote、数字语境、数字字形、证据边一致性、推断关系验证结果和论证 DAG。

此外，`gold_core.json` 是人工定义的 19 个核心语义项、34 个核心数字项和 10 个核心关系项。`63/63` 表示这些指定项目都能在图中找到，不代表全报告精确率或穷尽召回率为 100%。

## 8. 哪些是系统算法，哪些是固定机制

| 组件 | 性质 | 是否真实执行 | 泛化情况 |
|---|---|---:|---|
| PDF 哈希、页级文本提取、SourceObject 建立 | 确定性算法 | 是 | 对有文本层的 PDF 较通用。 |
| 空白规范化、页块切分、稳定 ID | 确定性算法/启发式 | 是 | 基本通用，但版面复杂时块边界可能不理想。 |
| Claim/Event/DataPoint 候选生成能力 | 大模型语义抽取 | 代码已实现；本次图构建阶段只消费已保存的 Luna 候选，没有在该次运行重新执行 Luna 生成 | 依赖提示词、模型能力和输入块。 |
| evidence quote 门 | 确定性验证 | 是 | 通用，是当前可靠性核心。 |
| 数字字形、十进制、单位、尺度检查 | 确定性算法 | 是 | 基本通用，但单位表仍需扩展。 |
| 五期财务表解析 | 固定词表 + 正则启发式 | 是 | 能覆盖相似财务附表，不保证跨版式。 |
| iPhone 容量表解析 | 报告特定正则 | 是 | 明显样本特定，应替换为通用表格结构解析。 |
| 跨段关系提议 | 大模型 | 是 | 可迁移，但质量依赖模型。 |
| 推断关系验证 pass | 第二阶段模型判定 | 是 | 防止共现关系直接入图，但不是形式证明；当前片段内关系是 Luna→Gemini，跨段关系是 Gemini→Gemini 的不同调用与提示。 |
| 环检测与 ReasoningStep 构造 | 确定性图算法 | 是 | 通用。 |
| `state_hash` 和结构验证 | 确定性算法 | 是 | 通用。 |
| `gold_core.json` | 人工评测清单 | 是 | 只适用于当前报告，不属于抽取算法。 |
| 前端节点簇位置 | 固定可视布局 | 是 | 只负责解释，不影响图内容。 |

所以，“有没有 mock”要分开回答：

- 没有在前端手写 854 个节点和 2509 条边来伪造结果；前端数据由 `tceg.json` 生成。
- 没有让模型绕过证据门直接决定最终图。
- 但当前运行使用了静态的 Luna 候选文件，且包含报告特定规则和人工评测清单。因此不能把当前演示描述成“对任意研报零适配的全自动算法”。

## 9. 前端不同簇分别表示什么

前端所谓“簇”不是 Louvain、谱聚类或 embedding 自动发现的社区。`viewer.js` 先按 `node_type` 分组，再把每一类放到固定中心，组内使用黄金角螺旋和稳定 ID 哈希进行排布。因此，簇表示本体类型，不表示模型自动发现的主题。

| 簇 | 位置 | 默认颜色/形状 | 含义 |
|---|---|---|---|
| `Entity` | 左上 | 青绿色圆形 | 公司、产品、行业、机构等对象。 |
| `Event` | 左中 | 橙色菱形 | 涨价、发布、需求变化、技术进展等有时间性的事件。 |
| `DataPoint` | 左下 | 蓝色圆形 | 带主体、指标、期间、单位和尺度的结构化数字。 |
| `Metric` | 下中偏左 | 灰色圆形 | 营业收入、毛利率、容量等指标定义。 |
| `Period` | 右下 | 棕灰色圆角矩形 | `2025E`、`2025Q4` 等期间。 |
| `ReasoningStep` | 中部 | 紫色梯形 | 前提到结论之间的论证步骤。 |
| `Claim` | 右侧 | 红色矩形 | 事实陈述、预测、解释、风险、估值和投资建议。 |

组内排序先看 `importance`：core 在前、supporting 其次、其他最后；同级节点按稳定哈希排序。节点大小由当前显示模式、节点度数和重要性共同决定，因此“大节点”通常连接更多或属于核心命题，不等于置信度更高。

### 9.1 三种显示范围

| 模式 | 选择规则 | 用途 |
|---|---|---|
| 核心论证 | 以 `importance=core` 的 Claim 为种子，沿当前 viewer 定义的 SUPPORTS、CAUSES、DEPENDS_ON、HAS_DATA、PREMISE_OF、CONCLUDES 取两跳邻域。邻域选择把边当作无向连接，只用于决定显示范围，不改变边的语义方向。 | 阅读主要投资逻辑。 |
| 关键数据 | 以人工核心清单命中的 DataPoint 为种子，沿 HAS_DATA、SUPPORTS、MEASURES、VALID_DURING、ABOUT 取一跳无向邻域。 | 检查核心数字及上下文。 |
| 完整图 | 加载全部 `nodes`，并绘制起点和终点都属于 `nodes` 的边。SourceObject 不作为画布节点，因此 `EVIDENCED_BY` 不在画布上绘制。 | 全量语义图审计；来源证据仍在左侧 PDF 和右侧详情中查看。 |

### 9.2 线和标记

- 实线：`EXPLICIT` 关系；
- 虚线：`INFERRED` 关系；
- 绿色系：SUPPORTS / HAS_DATA；
- 橙色系：CAUSES；
- 紫色系：DEPENDS_ON、PREMISE_OF、CONCLUDES；
- 灰色：ABOUT、MEASURES、VALID_DURING 等画布结构边；`EVIDENCED_BY` 保存在规范图中，但前端不把 SourceObject 画成节点，因此该边只通过详情与 PDF 联动体现；
- `CORE`：该节点命中了人工核心清单，不是模型置信度标签；
- 警告描边：该节点出现在验证器 warning 中。

### 9.3 三个前端方向的区别

“研究工作台”“论证星图”“证据账本”读取的是同一份前端 payload，并使用同一套 `viewer.js`。它们只改变配色、栏宽、排版和审计语气，不会改变节点、关系或簇定义。

## 10. PDF 下方的 `EXTRACTED` 是怎么来的

这是来源对象级状态，不是整页状态，也不是“这一页所有信息已经完整抽取”的声明。

来源对象初始状态都是 `NEEDS_REVIEW`。候选抽取协议还允许模型对每个来源对象输出 `source_reviews`，其结构是 `source_object_id + classification + reason`，其中 classification 为 `material`、`administrative`、`legal` 或 `opaque`。图构建完成后，程序遍历所有最终节点的 evidence，并统计每个 source object 被引用了多少次：

```python
for node in final_nodes:
    for evidence in node.evidence:
        referenced[evidence.source_object_id] += 1

if referenced[source_id] > 0:
    status = "EXTRACTED"
elif model_review in {"administrative", "legal"}:
    status = "NO_CLAIM"
elif model_review == "opaque" or object_type == "figure_caption":
    status = "OPAQUE"
else:
    status = "NEEDS_REVIEW"
```

因此：

- `EXTRACTED`：至少一个最终接受节点的 evidence 指向该来源块；
- `NO_CLAIM`：模型把没有产生节点的来源块判定为行政或法律内容；
- `OPAQUE`：没有被已接受节点引用，同时模型 review 为 opaque，或者启发式类型是 `figure_caption`。这是当前处理约定，不是对“该图一定完全不可读取”的形式证明；
- `NEEDS_REVIEW`：该块没有形成已接受节点，又不能安全判定为无语义或不可读；
- `ERROR`：Schema 预留的错误状态；当前抽取器没有逐对象写入 ERROR 的分支，关键抽取失败通常会中止整次运行，验证器若看到 ERROR 也会报错。

`candidate_count` 也是在这一步写入，等于最终节点 evidence 对该来源对象的引用计数，而不是模型最初生成了多少候选。

前端翻到某一页时，一页通常对应多个 source object。`viewer.js` 的默认选择逻辑为：

1. 如果该页存在 `OPAQUE` 对象，显示来源顺序中的第一个 OPAQUE；
2. 否则显示 `candidate_count` 最大的来源对象；并列时保持原来源顺序，选择第一个；
3. PDF 下方显示的是这个“当前选中来源对象”的状态；
4. 点击图节点后，前端切换到该节点第一条 evidence 对应的来源对象，此时状态也随之变化。

所以，页面下方出现 `EXTRACTED` 的准确含义是：**当前显示的 source block 已经为至少一个进入规范图的节点提供了证据。** 它不表示整页已被无损理解，也不表示该块中每个事实和数字都已抽取。

当前 56 个来源对象的状态为：22 个 `EXTRACTED`、30 个 `NEEDS_REVIEW`、4 个 `OPAQUE`。这 4 个对象均为未被节点引用的 `figure_caption`。本次外部候选文件没有提供 `source_reviews`，因此当前图没有 `NO_CLAIM` 对象。

## 11. 当前验证结果如何理解

当前状态：854 个节点、2509 条边、587 个语义节点；所有 587 个已入图语义节点都有 evidence。验证结果为 PASS、0 errors、6 warnings。

PASS 能说明：

- Schema 根字段和版本正确；
- 原始 PDF 存在且文件哈希一致；
- ID 唯一；
- evidence 引用存在且 quote 可回到来源对象；
- DataPoint 的主体、指标、期间和数字格式满足当前约束；
- 节点 evidence 与 EVIDENCED_BY 边一致；
- 激活的推断关系具有接受的独立验证结果；
- 论证关系没有有向环；
- 覆盖统计与图内容一致。

PASS 不能自动说明：

- 所有应该抽取的事实都已进入图；
- 每个已抽取命题的语义一定正确；
- 所有关系都符合金融专家判断；
- 对不同券商、行业和版式同样有效。

6 个 warnings 的具体含义是 6 个核心分析 Claim 没有入向论证关系。它们不破坏结构有效性，但说明论证路径仍不完整。

## 12. 如果要把它发展成通用算法，下一步应替换什么

优先级最高的不是继续增加报告特定正则，而是：

1. 用版面检测、表格结构恢复和 OCR/多模态识别替换仅依赖 PDF 文本层的输入；
2. 将固定五期财务表规则升级为“表头—行头—单元格—脚注”通用表格对象；
3. 将 iPhone 专用容量正则改为基于列语义和单位的通用产品规格解析；
4. 让候选抽取在标准命令中直接、可重复地调用模型，而不是依赖预先保存的候选文件；
5. 建立跨券商、跨行业、跨版式的盲测集，分别评估对象召回、数值准确率、证据对齐率和关系正确率；
6. 将节点和边的专属字段进一步写入严格 JSON Schema，减少 `additionalProperties: true` 带来的宽松空间；
7. 前端增加“来源块列表”和页级覆盖摘要，避免用户把单个 source object 的 `EXTRACTED` 误认为整页完成。

## 13. 一句话总结

当前 TCEG 是一套真实运行的混合语义编译系统：模型负责提出金融语义，确定性程序负责证据、数字、身份和结构约束，单独的验证 pass 负责复核推断关系；但当前样本仍混有固定格式规则、静态候选输入和人工评测清单，前端簇也是按节点类型固定布局，而不是自动发现的知识社区。
