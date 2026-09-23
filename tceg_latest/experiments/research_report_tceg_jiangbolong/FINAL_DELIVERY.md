# 江波龙研报 TCEG 阶段交付

## 最终状态

- 原始研报：爱建证券《国产存储模组龙头迎来涨价周期——江波龙(301308.SZ)首次覆盖报告》，2025-12-31，共 7 页。
- 图状态：854 个节点、2509 条边、56 个原始来源对象。
- 状态哈希：`a54e162b41464745d5901a9321ae8011b54b97879de2321762f450b69dec0077`。
- 抽取：`gpt-5.6-luna`；关系验证：`gemini-3.1-pro-high`。
- 结构验证：PASS，0 errors，6 warnings。
- 语义节点证据覆盖率：100%。
- 人工核心清单：语义 19/19、数字 34/34、关系 10/10。
- 单元测试：有效图、伪造证据、未验证推断、数字上下文缺失、严格数值置信度、空白归一化证据、容量表解析全部通过。

## 前端交付

推荐入口：`visualization/index.html`，默认进入“研究工作台”。另有“论证星图”和“证据账本”两个完整交互方向。

动态运行：

```bash
python3 tools/serve_tceg_visualization.py --host 127.0.0.1 --port 8765
```

打开 `http://127.0.0.1:8765/`。动态模式通过 `/api/data` 在每次刷新时重新读取当前 TCEG、校验和评测文件；直接打开 HTML 时使用离线数据包。

浏览器验收覆盖三个方向、两个桌面尺寸，共 6 组：页面加载、动态 API、核心论证模式、关键数据模式、完整 854 节点模式、搜索选中、节点证据显示、报告翻页和控制台错误检查均为 PASS。结果保存在 `visualization/acceptance_test.json`，截图保存在 `visualization/screenshots/`。

## 方法演示交付

`visualization/method-deck/` 提供 B 模板的 12 页 HTML 演示，用真实江波龙样本说明完整图 Schema、source graph、混合抽取、本体与数字规范化、证据门、关系复核、论证 DAG 和最终验证结果。入口为 `visualization/method-deck/index.html`；运行可视化服务后可打开 `http://127.0.0.1:8765/method-deck/`。PDF 位于 `visualization/method-deck/output/TCEG抽取过程与方法_B模板_12页.pdf`，浏览器验收位于 `visualization/method-deck/acceptance_test.json`。

## 可审计边界

“63/63”仅表示为这份报告手工定义的核心清单全部命中，不是对全报告穷尽精确率或召回率的声明。当前 4 个图像型 source object 为 OPAQUE，因为 PDF 文本层不包含图表中的完整数值；另有 6 个核心分析主张没有入向论证关系，因此验证器保留 warnings。一份券商研报样本不能证明跨公司、跨券商或跨版式泛化，下一阶段需要建立多报告盲测集并分别度量对象召回、数值准确率、证据对齐率和关系正确率。

## 主要文件

- `tceg.json`：当前规范图状态。
- `validation.json`：结构、证据和论证约束验证。
- `core_evaluation.json` / `CORE_EVALUATION.md`：人工核心清单评测。
- `luna_extraction_audit.json` / `.md`：Luna 抽取候选及审计。
- `visualization/`：动态/离线前端、原始报告页图像、截图和设计说明。
- `tools/extract_research_report_tceg.py`：主抽取与建图流程。
- `tools/validate_research_report_tceg.py`：TCEG 验证器。
- `tools/evaluate_research_report_tceg.py`：核心清单评测器。
- `tools/build_tceg_visualization_data.py`：离线前端数据构建。
- `tools/serve_tceg_visualization.py`：动态数据前端服务器。
- `tools/test_tceg_visualization.cjs`：浏览器验收测试。
