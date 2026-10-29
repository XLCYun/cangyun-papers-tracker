# AutoVend 来源与正文范围

2026-10-29 新增 `autovend-2026`。采用 [arXiv:2610.36980v1](https://arxiv.org/abs/2610.36980v1)，首发时间为 2026-10-27；固定版本的[英文 PDF](https://arxiv.org/pdf/2610.36980v1)共 16 页。

作者与机构按论文首页记录：Qiming Shi、Yikun Li、Beidi Luan、Rui Sun、Yan Ma、Jing Li、Daxin Jiang、Zuo Bai；机构包括 StepFun、Zhejiang University、Xi’an Jiaotong-Liverpool University、FinStep。未找到论文提供的 AutoVend 代码地址，`codeUrl` 保持 `null`。

论文用一个 Agent 在 180 个模拟日内经营 20 台售货机，覆盖五类场所及共享仓库。按实际经营任务归入「经营模拟」「供应链」。页面简述与摘要为原创整理，依据论文摘要、任务定义和结论；保留五个受测模型中四个低于规则基线，以及单一环境、每个模型三次运行的适用范围。

中文范围为 PDF 第 1–10 页。第 10 页采用普通双栏阅读顺序，右栏结论之后开始 References；保留完整左栏和右栏结论，裁去右栏参考文献，排除后续参考文献与附录。复用原官网仓库 `paper-tools` 的 `prepare --end-page 10 --stop-before References --columns 2`、`translate` 和 `finalize` 流程。

所选版本使用 [arXiv 非独占分发许可](https://arxiv.org/licenses/nonexclusive-distrib/1.0/)，沿用现有 `source-only` 规则：页面显示简介、摘要和官方英文 PDF，不发布全文或译文至 OSS，`assets` 保持空对象。本地 PDF、Markdown、处理回执和 `.env` 不进入 Git。翻译命令正常完成即视为成功，不逐页检查、校对或另行处理图表。
