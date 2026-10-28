# 每日 arXiv 主题标签方案

2026-10-22 确认方案，2026-10-23 已实现并完成归档补标签；正式发布验收由 [#11](https://github.com/XLCYun/cangyun-papers-tracker/issues/11) 跟踪。用户已确认 Q1、Q2 和 Q4–Q8，并补充 CodingAgent、AI4S、AgentOps 的收录边界。2026-10-23 追加 GUI Agent 标签。2026-10-24 改为默认停留在今天，零篇或缺少日报时展示空状态及周末说明，通过按钮查看最近有论文的一期。

2026-10-23 补充澄清：CodingAgent 以编程 Agent 为主，相关的大模型编程研究适当放宽，不以特定 Agent 架构或论文是否自称 Agent 为硬门槛。

2026-10-23 展示名称调整：GUI Agent 改为 GUI/Web Agent，体现其覆盖网页智能体及相关训练、数据和评测。筛选栏、卡片与搜索使用新名称；JSON 保留 `GUI Agent` 标识，沿用现有评分、阈值与打标缓存。

2026-10-23 提示词同步：Jev 的 GUI/Web Agent 定义明确包含 DOM、文本化页面交互和相关训练、数据集及评测，规则版本升级为 `daily-tags-v3`。后续采集及显式补跑使用新定义，已归档结果继续按原版本读取。标签问题沿用公共的来源不可信、按主要研究对象判断两条指令，定义正文为：

> Is GUI/Web Agent research a main focus? Include agents operating web, desktop or mobile interfaces via screenshots, DOM, UI elements or text-based page representations, plus related training, datasets and evaluations. Exclude API-only agents, unrelated coding research and interface generation without agent interaction.

## 已确认

- 保持现有入选范围，只处理 `new`，仍须满足当前启用分区、英文标题或摘要的 LLM/Agent 匹配规则及 robot 排除规则；增加标签不扩大抓取范围。
- 当前固定九个标签：LLM、Agent、AI4S、CodingAgent、GUI/Web Agent、AgentOps、AgentHarness、软件工程、企业Agent。
- 一篇论文可以有多个标签，不要求互斥。
- LLM、Agent 沿用关键词规则，软件工程依据 `cs.SE`；其余六个标签由 TypeSafe Jev 判断，通过现有 DMXAPI 接入，翻译继续使用 `glm-5.3-flash`。
- 打标只读取英文标题、摘要和来源分类，不读取 PDF，不依赖中文翻译是否成功。
- 标签按论文的主要贡献或明确研究对象判定，泛泛提及某个应用不足以打标签。
- 页面沿用黑金视觉，提供“全部 + 九个标签”的单选筛选及各标签篇数，与日期和搜索共同生效。
- Jev 失败时保留规则标签并照常发布，页面不增加失败提示；重跑只补失败打标，不自动切换 GLM。
- 上线时给当前已归档的 208 篇补标签，复用已有译文；之后纳入每日自动采集、Git 备份和 OSS 发布。

## 核验的现状

- 采集器使用忽略大小写的 `\bllm|\bagent` 匹配英文标题与摘要，仅有左侧词边界；robot 排除使用子串匹配。新增采集与归档重跑都先筛选再翻译。
- `cs.SE` 已启用，仍需命中上述专题规则。当天归档有 208 篇，其中 34 篇的来源分类包含 `cs.SE`。
- 当前翻译通过 DMXAPI 的 OpenAI 兼容接口，GitHub 非敏感配置中的模型为 `glm-5.3-flash`。日报 JSON 尚无自定义主题标签。
- 账户只读模型列表返回 Jev 的 `jev-1.13.0`、`jev-1.14.0`、`jev-latest`；本次未调用模型推理。
- DMXAPI 的 Jev 文档提供专用 `https://www.dmxapi.cn/typesafe/v1/systemone` 接口。它与当前翻译的 `/v1/chat/completions` 不同，不能只替换模型名。实际推理可用性待实施时验证。

## 标签定义

| 标签 | 判定方式 | 范围 |
| --- | --- | --- |
| LLM | 现有关键词规则 | 英文标题或摘要命中 `\bllm`，忽略大小写 |
| Agent | 现有关键词规则 | 英文标题或摘要命中 `\bagent`，忽略大小写 |
| 软件工程 | 来源分类规则 | arXiv 分类包含 `cs.SE` |
| AI4S | Jev | 利用 AI 开展科学研究、辅助科研过程或推动科学发现，不限于某个学科或必须使用 Agent；包括科学建模、计算仿真、科学数据分析、实验设计和自动实验等 |
| CodingAgent | Jev | 以编程 Agent 为主，覆盖与其直接相关的大模型代码生成和软件开发研究；包括代码生成、补全、修复、调试、测试生成、重构、审查，以及相关模型、数据和评测，不要求特定 Agent 架构或论文必须自称 Agent |
| GUI/Web Agent | Jev | 网页、桌面和手机界面的操作智能体及其训练、数据和评测，涵盖基于截图、DOM、UI 元素或文本化页面的网页交互；仅 API 调用、无界面操作的普通编程研究和单纯界面生成不算 |
| AgentOps | Jev | Agent 系统的部署、可观测性、监控、日志与链路追踪、故障诊断、根因定位、运行评测、可靠性、性能、成本及生产运维 |
| AgentHarness | Jev | 支撑 Agent 执行的上下文组织、记忆、工具接入、执行循环、调度与运行控制 |
| 企业Agent | Jev | Agent 执行办公、客服销售、财务、ERP/CRM、供应链、企业经营与经营模拟等具体业务任务及相关评测 |

CodingAgent 的主体仍是编程 Agent；相关大模型编程研究适当放宽，避免因命名或架构限制漏收，不将一般“涉及代码”作为充分条件。AI4S 的“范围广”指科学应用主题，不扩大日报的来源与入选规则。

AgentOps 与 AgentHarness 可以同时出现；普通 Benchmark 不自动算 AgentOps。企业所属机构、企业赞助或通用企业应用展望不足以标为企业Agent。

三个规则标签独立生成，不因细标签判定而自动补打基础标签。例如，符合 CodingAgent 但原文未命中 `\bagent` 的论文，可以没有 Agent 标签。

## 页面交互

- 保留日期、搜索和互斥展开论文详情的行为；标签栏默认选择“全部”，宽度不足时自动换行。进入页面默认显示今天；今天缺失或零篇时显示空状态，不自动切换日期，可通过“查看最近一期”按钮打开最近一个不晚于今天且非零的归档日。
- 一次只选一个标签，点击另一个标签即切换；“全部”取消主题限制。论文自身仍可同时显示多个标签。
- 标签筛选与日期、关键词搜索取交集；切换日期时继续使用当前标签和关键词。
- 标签篇数按所选日期的完整日报统计；结果数量反映当前搜索与标签筛选后的论文数。零篇显示空状态及北京时间周六、周日通常不发布新论文的说明；筛选无结果提示清除筛选，与零篇日报分开。
- 卡片显示自定义主题标签，并保留原有 arXiv 分类，二者含义分别表达。

## 打标与归档

- 使用 Jev 的 Noul 问题对六个细标签分别做是非判断；同篇论文共享英文标题、摘要和来源分类，一次请求返回六个独立判断。
- 实施初始值采用有明确文档的固定模型 `jev-1.13.0`，避免别名升级自动改变结果；模型版本可配置。首次实施先验证 DMXAPI 专用接口的实际可用性。
- 细标签初始概率阈值取 `0.7`，作为偏保守策略的可配置参数；按主要研究对象编写判定问题与正反例，不通过泛泛出现的单词决定细标签。
- 公开 JSON 保存主题标签和独立的打标状态，并记录模型、标签规则版本等复用依据。翻译状态与打标状态分别维护。
- 同一原文、模型和标签规则版本的成功打标结果复用；修改规则或模型需明确触发重新打标，普通重跑不重复请求成功项。已完成但六个细标签均未命中也属于成功。
- 暂时性失败有限重试；仍失败则保留三个规则标签、记录可重试状态并发布。缺失或畸形模型结果不能伪装为成功；不人工逐篇校对模型判断或翻译。
- 标签数据随每日 JSON 先备份到 Git，再按现有不可变对象和索引流程发布 OSS。当前归档补标签不重新抓取、不重译成功内容。

## 决策树结论

1. 入选范围：保持现状，已确认。
2. 标签体系：固定九个标签、允许多标签，标签范围与规则/模型分工已确认。
3. 模型打标：Jev 经 DMXAPI 接入，输入原始英文元数据；翻译继续用 GLM，已确认。
4. 页面筛选：单选标签、显示篇数、结合日期与搜索，已确认。
5. 失败与恢复：先发布规则标签、后台记录失败、重跑补失败项，无页面提示、不自动换模型，已确认。
6. 既有归档：补齐当前 208 篇，复用译文，不新增历史抓取，已确认。

产品决策无未决项；接口实际可用性及具体错误处理通过实施验证。

## 实施验证

- 2026-10-23 已通过 DMXAPI 的固定 `jev-1.13.0` 实际调用验证，为 2026-10-22 的 208 篇归档论文完成打标，成功 208 篇、回退 0 篇。
- 原始论文元数据、来源时间、统计与全部既有译文保持不变；移除两类 API 密钥后重跑，成功打标和日报字节完全复用。
- 代码按 [#8](https://github.com/XLCYun/cangyun-papers-tracker/issues/8)、[#9](https://github.com/XLCYun/cangyun-papers-tracker/issues/9)、[#10](https://github.com/XLCYun/cangyun-papers-tracker/issues/10) 实现，双轴审查发现的问题由 [#12](https://github.com/XLCYun/cangyun-papers-tracker/issues/12) 修复。
- 119 项 Python 测试、54 项网页测试及生产构建通过；本地浏览器已验证日期、单选筛选、搜索交集、卡片互斥展开和窄屏布局。公网 JSON、构建文件及浏览器发布验收记录在 #11。

## 资料

- 标签实现：`collector/tagging.py`、`.github/workflows/daily.yml`、`web/src/ArxivDaily.jsx`。本文记录标签首次实现时的采集范围；后续总区分页与全部 CS 分类范围见 [CS 公告采集方案](cs-announcement-pagination.md)。
- [arXiv 分类](https://arxiv.org/category_taxonomy)与 [RSS 规范](https://info.arxiv.org/help/rss_specifications.html)。
- [DMXAPI Jev 接入](https://doc.dmxapi.cn/jev-1.13.0-typesafe-structured-judgment.html)。
- [TypeSafe Noul 问题](https://docs.typesafe.ai/primitives/noul)与[模型说明](https://docs.typesafe.ai/models)。
