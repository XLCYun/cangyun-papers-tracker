# Cangyun Papers Tracker

CY Lab 的研究站点，汇集每日 arXiv LLM 与 Agent 论文，以及企业 Agent Benchmark 时间线。

线上站点为 <https://research.cyunlab.com>，提供[每日 arXiv](https://research.cyunlab.com/arxiv-daily) 和[企业 Agent Benchmark](https://research.cyunlab.com/enterprise-agent-benchmark)。需求见 [实现规格](docs/spec.md)，采集与页面共用的接口见 [数据约定](docs/data-contract.md)。

每日采集由 GitHub Actions 在北京时间 13:30 运行，完整 JSON 先提交到 Git，再上传 OSS。配置与失败恢复见 [日报发布说明](docs/publication.md)，网页发布见 [部署说明](docs/deployment.md)。每日 JSON 保存在 `data/arxiv-daily/`，人工精选目录维护在 `web/src/data/enterprise-papers.json`。

代码使用 MIT 许可证；论文文件及字体保留各自许可。日报仅归档 JSON，不保存 PDF。
