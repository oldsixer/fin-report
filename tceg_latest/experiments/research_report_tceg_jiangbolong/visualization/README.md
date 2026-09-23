# TCEG 研报证据图谱前端

这是爱建证券江波龙首次覆盖报告的交互式 TCEG 查看器。图是主语义状态，原始 PDF 是证据载体。前端支持核心论证、关键数据和完整图三种范围，节点搜索，关系邻域高亮，以及节点到报告页和原文片段的联动。

## 动态网站模式（推荐）

在项目根目录执行：

```bash
python3 tools/serve_tceg_visualization.py --host 127.0.0.1 --port 8765
```

打开 <http://127.0.0.1:8765/>。页面每次刷新都会通过 `/api/data` 重新读取以下当前文件，而不是依赖构建时快照：

- `experiments/research_report_tceg_jiangbolong/tceg.json`
- `experiments/research_report_tceg_jiangbolong/validation.json`
- `experiments/research_report_tceg_jiangbolong/core_evaluation.json`

健康检查地址为 <http://127.0.0.1:8765/api/health>，原始报告由 `/api/report.pdf` 提供。页面标题下出现 `LIVE API` 表示动态模式已启用。

## 离线 HTML 模式

直接双击 `index.html` 或任一 `direction-*.html` 也能使用。离线模式读取同目录下的 `tceg_visualization_data.js`，标题下显示 `OFFLINE SNAPSHOT`。当图文件更新后，用下面的命令刷新离线包：

```bash
python3 tools/build_tceg_visualization_data.py
```

## 三个界面方向

- `direction-1-workbench.html`：研究工作台，推荐默认版本；米白编辑设计，平衡报告、图和证据。
- `direction-2-atlas.html`：论证星图；深色、图优先，适合演示关系网络。
- `direction-3-ledger.html`：证据账本；瑞士网格与审计导向，适合逐项验收。

三个页面使用相同数据和交互。浏览器验收覆盖 1440×900 与 1920×1080，测试核心论证/关键数据/完整图切换、854 节点完整加载、搜索选中、证据显示、报告翻页和控制台错误。

## 当前解释边界

结构验证为 PASS（0 errors，6 warnings）；人工核心清单为 63/63，但只表示本报告预先定义的 19 个语义项、34 个数字项和 10 个关系项全部命中，不代表全报告穷尽精确率或召回率均为 100%。4 个图像型来源对象仍为 OPAQUE。
