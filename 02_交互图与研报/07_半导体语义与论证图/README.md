# 半导体：从记录图到业务语义图与限定论证图

入口：[交互图、查询、审计和增强研报](06_交互图与研报/index.html)。全部本地离线可浏览。

“05 增强版研报”增加左右对照：默认展示 7 组经原文匹配检查的节选、高亮和差异解读，可切换两版完整原文。左侧为原 06 实验的原始数据版，右侧为本项目增强版；输入资料和写作要求不同，不是图效果的受控消融。原版的条件论证和更完整的估值／情景覆盖也明确保留。对照定义见 `report_comparison.py`，运行 `publish.py` 重建；不会重新调用模型或改写两版研报。

主入口的“06 行业截面 × 时间演化”现为页内标签，页面和数据一起嵌入 `index.html`，不再依赖跨目录 HTML 跳转。修改后需刷新或重新打开入口。原始资料链接仍需要保留目录结构。更新时态数据后，先运行 `python3 temporal.py`，再运行 `python3 publish.py`，同步更新独立页面与主入口内置视图。

新增：[行业截面 × 时间演化](08_时态图与行业演化/index.html)。复用已有 4 条指数日频序列、8 家公司累计财务历史与 133 条业务断言。选日期看截面，选公司/概念看轨迹；不是严格 point-in-time 回测，也不把历史披露自动延长为当前有效关系。建模说明见 `00_方案与说明/时态图方案.md`。重建运行 `python3 temporal.py`；浏览器与边界测试使用现有 finsight 环境运行 `verify_temporal.py`。

## 文件地图

- `00_方案与说明`：实施方案、关系schema、测试边界。
- `01_基线快照`：从06复制的财务派生值、上下文与来源清单；未重新拉取供应商财务。
- `02_文本原始资料`：网页/PDF原件、哈希、获取日期和失败记录。
- `03_文本证据`：全文、建图片段、片段范围；中微转曲PDF的视觉核对摘录。
- `04_抽取与校验`：每次CLI调用的输入、输出、trace；通过/拒收、逐条修订记录；增强研报生成原始输出。
- `05_图与查询`：两种图JSON、跨公司工艺/应用路径、查询结果、依赖测试。
- `06_交互图与研报`：HTML入口与增强版研报Markdown。
- `07_交付验证`：文件与图结构检查、报告数字校验、浏览器交互测试与截图。
- `08_时态图与行业演化`：离线联动页面、时态图 JSON、实现验证结果与截图；`temporal.py` / `temporal.template.html` 为可重现源码。

原05/06实验未覆盖。本轮没有重新比较raw/graph报告质量；新增了文本与分析者论证后，不可拿旧raw报告归因图收益。

## 两种逻辑

A先按领域schema抽取公司、产品、工艺、应用与限定事件，规范实体并拆分有明确原文的枚举。B将A的边提升为有来源、时间和条件的断言节点，再由研究问题组织多前提论证，显式挂接假设、验证与反证。二者共享同一事实集，不是两个独立训练模型。

跨公司共享工艺通过最多三跳的已披露路径获得，只表示能力或应用重叠；具名客户必须另有直接披露。单条证据撤回后沿前提依赖传播“须复核”，不自动断定世界改变或结论错误。当前未训练GNN或可学习curator。

## 重现

使用这台机器已有Python环境，无需提供API key。CLI使用现有登录；不接收同花顺凭据，关闭shell/web/agents。已有输出默认缓存，重放图不再调用模型。

```bash
cd /Users/nelson/Documents/FinAgent/07_半导体语义与论证图
/Users/nelson/Documents/FinAgent/literature_review/reproduction_envs/finsight/bin/python curate.py
/Users/nelson/Documents/FinAgent/literature_review/reproduction_envs/finsight/bin/python build.py
/Users/nelson/Documents/FinAgent/literature_review/reproduction_envs/finsight/bin/python publish.py
/Users/nelson/Documents/FinAgent/literature_review/reproduction_envs/finsight/bin/python verify.py
```

重新获取/抽取用`sources.py`和`extract.py`，但本轮已有成功/失败缓存，不会静默覆盖旧原件。换新来源或模型重新试验应另建运行版本并重新复核`curate.py`中的案例级修订，不能将本次Fxxx/Cxxx修订当成通用算法。

`report.py`保留了未经编辑的模型输出；已交付Markdown另经校验修正单日行情与区间回报的混淆，以及披露强度/设备研发阶段的表述。不要直接重跑report.py覆盖已复核稿；审阅依据见07_交付验证。

## 局限

源页面可访问、原文匹配不等于声明真实。公司自述未独立验证；财务仍是06接口快照而非交易所逐项对账；沪硅文字为新浪转载的2025年报摘要，原始PDF待交叉核验。中微PDF页1经视觉核对，长电PDF页10经渲染核对。历史技术披露不保证持续至2026。

133条原子边包括枚举拆分和分析者补充，不是133个独立新增知识点。没有独立标注准确率、报告盲评或收益回测。下一步应固定同一新增证据集，对原文检索/三元组/限定论证图做受控消融。
