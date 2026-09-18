# TCEG 研究工作台 · 离线展示包

这个文件夹可以整体复制到另一台电脑，不依赖项目源码、模型 API 或互联网连接。

## 最简单的打开方式

双击 `index.html`，使用 Chrome、Edge、Firefox 或 Safari 打开。

页面会直接读取文件夹内的离线图数据：

- `tceg_visualization_data.js`：854 个节点、2509 条边及审计信息；
- `assets/report-page-1.png` 至 `report-page-7.png`：原研报页面图像；
- `assets/source-report.pdf`：原始券商研报 PDF；
- `viewer.js`：图交互和证据联动；
- `styles.css`：页面样式。

## 如果浏览器限制本地文件

在本文件夹打开终端，执行：

```bash
python -m http.server 8765
```

然后访问：

```text
http://127.0.0.1:8765/
```

Windows 如果 `python` 命令不可用，可尝试：

```powershell
py -m http.server 8765
```

## 演示操作

- “核心论证”：查看核心 Claim 的两跳论证邻域；
- “关键数据”：查看人工核心清单命中的数字及其主体、指标和期间；
- “完整图”：查看全部语义节点和节点间关系；
- 点击节点：右侧显示结构化字段、关系和 evidence，并同步左侧研报页；
- 点击 evidence：切换到对应来源块；
- `/`：聚焦搜索；
- 鼠标滚轮：缩放；拖动画布：平移；
- “打开 PDF”：打开本文件夹内的 `assets/source-report.pdf`。

请保持整个文件夹结构不变，不要只复制 `index.html`。
