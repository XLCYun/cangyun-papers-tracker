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

`src/data/enterprise-papers.json` 为完整的人工精选研究目录。原文、译文和 Markdown 继续链接到已发布的 OSS 文件；source-only 条目不增加译文链接。字体许可保存在 `public/research/OFL-Noto-Serif-SC.txt`，页面视觉和资产来源见 [设计说明](../docs/design/enterprise-agent-benchmark-archive/README.md)。

## 验证边界

网页测试通过实际页面、用户操作与固定 JSON 响应验证行为；仅替代外部 HTTP 和时钟，不依赖内部组件结构。覆盖北京时间默认日期、历史日期选择、今日缺失及有效空日、搜索、双语内容与英文回退、完整性错误和重试、对象路径约束，以及 Benchmark 的互斥展开和公开文件边界。原有八项 Benchmark 选择与元数据检查一并保留。

新增行为按失败测试、最小实现逐个推进：默认日报最先因缺少页面失败；详情、搜索、重试、索引路径限制、日报完整性、首页入口和 Benchmark 路由分别先失败，再通过。构建与响应式浏览器检查独立进行，不校对翻译内容。
