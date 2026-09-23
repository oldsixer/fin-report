# TCEG 方法 Deck 产品事实

- 演示对象：爱建证券《国产存储模组龙头迎来涨价周期——江波龙(301308.SZ)首次覆盖报告》。
- 报告日期：2025-12-31；PDF 共 7 页。
- 当前图状态哈希：`a54e162b41464745d5901a9321ae8011b54b97879de2321762f450b69dec0077`。
- 来源对象：56；状态分布为 EXTRACTED 22、NEEDS_REVIEW 30、OPAQUE 4。
- Luna 候选：244，包括 89 Claim、110 DataPoint、16 Event、29 Relation。
- 确定性解析创建：周期财务表 380 个 DataPoint；iPhone 容量表 34 个 DataPoint。
- 推断关系独立验证队列：106；接受 69，拒绝 37。
- 最终图：854 节点、2509 条边；语义节点 587，证据覆盖率 100%。
- 节点类型：Entity 55、Metric 106、Period 35、DataPoint 498、Event 13、Claim 76、ReasoningStep 71。
- 边类型：ABOUT 582、MEASURES 536、VALID_DURING 551、EVIDENCED_BY 611、HAS_DATA 16、CAUSES 6、PREMISE_OF 71、CONCLUDES 71、SUPPORTS 56、DEPENDS_ON 9。
- 抽取候选模型：gpt-5.6-luna；关系验证模型：gemini-3.1-pro-high。
- 验证：PASS，0 errors，6 warnings。
- 人工核心清单：语义 19/19、数字 34/34、关系 10/10。
- 解释边界：核心清单全中不等于全报告精确率或召回率 100%；4 个图像对象仍为 OPAQUE；6 个核心分析主张没有入向论证关系；单报告不能证明泛化。

以上数据均来自本地 `tceg.json`、`validation.json`、`core_evaluation.json`、`candidates.json` 和 `luna_extraction_audit.json`，不使用演示占位数字。
