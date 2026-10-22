# 研究站前端

在仓库根目录运行：

```sh
npm ci
npm run dev
npm test
npm run build
```

Vite 从 `web/` 读取前端源码，将可直接由 Nginx 托管的静态文件输出到仓库根目录 `dist/`。部署时需让三个页面路径均能返回 `index.html`。

生产站默认直接读取 `https://updates.cyunlab.com/research/arxiv-daily/` 下的 JSON。开发服务器通过同源 `/daily-data/` 转发该公开前缀，不要求为 OSS 添加 localhost CORS 来源。`VITE_DAILY_DATA_BASE_URL` 可覆盖公开 JSON 根地址；不要在任何 `VITE_` 变量中写凭证。

备案信息支持 `VITE_ICP_FILING_NUMBER`、`VITE_POLICE_FILING_NUMBER`、`VITE_POLICE_FILING_CODE`；默认保留现有 CY Lab 备案。

日报主题名称和顺序使用 `shared/daily-tags.json`。页面提供“全部 + 八个标签”的单选筛选；每个标签的篇数统计所选日期的完整日报，顶部数量反映标签与搜索的交集。切换日期保留标签和关键词。卡片用金色主题标签与较淡的 arXiv 分类区分两种含义，窄屏标签栏可以横向滚动。

旧 JSON 缺少标签字段时，页面仅按英文标题、摘要和分类推导 LLM、Agent、软件工程。带标签的 JSON 必须符合 [数据接口](../docs/data-contract.md)，包括固定名称、顺序、打标状态、分数和标签一致性；损坏数据走现有读取错误及重试。Jev 失败但结构有效的规则标签照常显示，不增加提示。

`src/data/enterprise-papers.json` 为完整的人工精选研究目录。原文、译文和 Markdown 继续链接到已发布的 OSS 文件；source-only 条目不增加译文链接。字体许可保存在 `public/research/OFL-Noto-Serif-SC.txt`，页面视觉和资产来源见 [设计说明](../docs/design/enterprise-agent-benchmark-archive/README.md)。

## 验证边界

网页测试通过实际页面、用户操作与固定 JSON 响应验证行为；仅替代外部 HTTP 和时钟，不依赖内部组件结构。覆盖北京时间默认日期、历史日期选择、今日缺失及有效空日、搜索、双语内容与英文回退、完整性错误和重试、对象路径约束，以及 Benchmark 的互斥展开和公开文件边界。原有八项 Benchmark 选择与元数据检查一并保留。

主题标签测试覆盖单选及多标签展示、独立于搜索的每日篇数、日期与搜索的交集、跨日期保留筛选条件、旧数据规则推导、有效回退状态和损坏打标数据，包含与采集器一致的 Unicode 左词边界及前缀匹配。

新增行为按失败测试、最小实现逐个推进：默认日报最先因缺少页面失败；详情、搜索、重试、索引路径限制、日报完整性、首页入口和 Benchmark 路由分别先失败，再通过。构建与响应式浏览器检查独立进行，不校对翻译内容。
