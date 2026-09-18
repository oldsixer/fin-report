# 半导体板块图研报实验（独立重跑）

先打开 [知识图与两篇研报入口](06_研报与对照/index.html)。这里仅研究半导体板块。188只主板块成分有行情与估值覆盖，八家预设公司有中报财务覆盖，不能将后者外推全板块。

## 查阅入口

- 00_方案与说明：实施方案、实际采集范围。
- 01_接口契约：公开接口文档快照，复用上轮同日读取的文档，不含鉴权信息。
- 02_原始数据：本轮新采集的.body原始字节、含URL/时间/哈希的.json包装和manifest。
- 03_规范化证据：sources来源、records选定记录、derived指标及依赖、context范围约束。
- 04_知识图：graph完整图、validation图与两路一致性核验。
- 05_隔离输入与运行记录：raw_input/graph_input最终输入；report_raw_final/report_graph_final最终输出、提示词和trace。无_final为首轮试运行，initial输入单独保留。
- 06_研报与对照：两份HTML/MD报告、交互图、执行审计、数据/报告/UI核验。

## 从缓存快照重建

在本目录运行，前五步均可使用系统python3，无需第三方数据处理库：

```sh
python3 prepare.py
python3 build_graph.py
python3 model_runner.py raw
python3 model_runner.py graph
python3 publish.py
python3 validate_data.py
```

已有模型output.json会复用，不再次消耗模型调用。报告模型使用本机已登录Codex CLI，gpt-5.6-terra / low，不用用户模型API。需要新抽样时另建运行标签，不覆盖本轮trace。

可选运行test_viewer.py，需要Playwright及浏览器。当前已验证环境：/Users/nelson/Documents/FinAgent/literature_review/reproduction_envs/finsight/bin/python。

## 重新获取新时点数据

pipeline.py调用同花顺只读接口，已存在的缓存不重复请求。新的时间点应使用新的实验目录，不应把新快照当成本轮2026-09-15数据。配置只读自用户提供的 /Users/nelson/Documents/ZSZQ/hithink_api_config.py，密钥只发往固定HTTPS域名，不记录、不复制、不进入模型上下文。

图是属性、财报版本和计算来源的组织方式，不是因果模型。本次没有GNN训练、行业新闻抽取、全板块财务汇总或盲评结论。所有商业数据保留在本地，不公开部署。上轮05目录保持不变。
