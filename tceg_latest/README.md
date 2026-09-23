# TCEG 当前保留版本

本目录集中保存 LivingFin 在方案重构前最后一次完成的建图实现，即江波龙券商研报 TCEG 实验及其代码、Schema、原始样本、可视化和测试产物。

它是一份冻结的阶段快照，用于后续讨论和对照，不代表下一阶段的 Graph-Native Continual Financial Report Generation 最终方案。

## 目录

- `tools/`：当前保留的研报抽取、验证、评测、可视化与浏览器测试代码。
- `schemas/`：当前保留的 `research-report-tceg-0.1` JSON Schema。
- `sources/`：江波龙原始券商研报 PDF。
- `experiments/research_report_tceg_jiangbolong/`：最后一次抽取的图、候选、评测、展示页面和方法 Deck。
- `deliverables/TCEG_Workbench_Portable/`：可直接通过 `file://` 打开的便携图谱工作台。
- `deliverables/TCEG_Workbench_Portable.zip`：便携交付压缩包。
- `.env` / `.env.example`：本地模型调用配置与示例；`.env` 不应提交或公开。

## 当前状态

- 这是历史研报反向建图的最后实现版本。
- 已知其论证关系、依赖关系和 `ReasoningStep` 表达不足以直接支撑未来的图原生持续研报生成。
- 本次整理不修改 `tceg.json`，不重算状态哈希，也不把旧图自动迁移到尚未确定的新 Schema。
- 后续应先确定图原生生成、Inference、版本、场景和增量渲染契约，再开始新一轮实现。

## 主要入口

- 阶段说明：`experiments/research_report_tceg_jiangbolong/FINAL_DELIVERY.md`
- 图数据：`experiments/research_report_tceg_jiangbolong/tceg.json`
- 可视化：`experiments/research_report_tceg_jiangbolong/visualization/index.html`
- 方法展示：`experiments/research_report_tceg_jiangbolong/visualization/method-deck/index.html`
- 便携工作台：`deliverables/TCEG_Workbench_Portable/index.html`

