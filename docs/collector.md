# 每日公告采集器

在仓库根目录运行：

```sh
uv sync --locked --group dev
uv run --locked python -m collector --output-dir data/arxiv-daily
uv run --locked python -m collector --date 2026-10-22 --output-dir data/arxiv-daily
uv run --locked python -m pytest tests/test_collector.py
```

默认日报日期为北京时间今天。`--date` 用于补跑已有归档日的失败译文和标签；未保存来源的历史日期会失败，不使用今天的公告补造历史。缺少翻译配置或调用失败时，仍会生成保留完整英文标题和摘要的有效日报。Jev 打标独立运行，未配置或调用失败时保留规则标签，照常发布。

## 环境配置

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `OPENAI_API_KEY` | 空 | 兼容 Chat Completions 接口的密钥；空值时使用英文 |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | 翻译接口基地址 |
| `OPENAI_MODEL` | `gpt-4o-mini` | 翻译模型，部署时显式设置实际模型 |
| `OPENAI_THINKING` | 空 | 设为 `disabled` 时发送提供商的禁用推理参数，其余情况不发送 |
| `TRANSLATION_BATCH_SIZE` | `10` | 每个模型请求包含的论文数 |
| `TRANSLATION_WORKERS` | `3` | 并发模型请求数 |
| `JEV_API_KEY` | 空 | Jev 专用接口密钥；空值时仅生成规则标签，不隐式使用翻译密钥 |
| `JEV_BASE_URL` | `https://www.dmxapi.cn/typesafe/v1` | Jev 接口基地址，请求 `/systemone`，与翻译的 Chat Completions 接口分别配置 |
| `JEV_MODEL` | `jev-1.13.0` | 固定 Jev 模型版本 |
| `JEV_THRESHOLD` | `0.7` | 六个模型标签的概率阈值 |
| `JEV_WORKERS` | `3` | 并发 Jev 请求数，每篇论文一个请求 |
| `JEV_RULES_VERSION` | `daily-tags-v3` | 标签规则版本，用于判断已有成功结果是否可复用；v3 明确 GUI/Web Agent 包含 DOM、文本化页面交互及相关训练和评测 |
| `JEV_RETRY_ATTEMPTS` | `3` | Jev 暂时性错误的最大尝试次数 |
| `JEV_RETRY_DELAY_SECONDS` | `2` | Jev 重试初始间隔，后续指数增加 |
| `ARXIV_FEED_URL` | `https://rss.arxiv.org/rss/cs` | 官方整个 CS 公告源；本地测试可替换 HTTP 地址 |
| `ARXIV_RETRY_ATTEMPTS` | `3` | 来源网络或解析失败后的最大尝试次数 |
| `ARXIV_RETRY_DELAY_SECONDS` | `2` | 来源重试初始间隔，后续指数增加 |

凭证由运行环境或 GitHub Secrets 注入。采集器不自动读取、复制或归档 `.env`。日志只输出错误类别和 HTTP 状态，不输出提供商错误正文、请求头或密钥。

线上翻译通过 DMXAPI 调用 `glm-5.3-flash`。GitHub Actions 优先将独立的 `JEV_API_KEY` Secret 注入打标步骤；未设置时，显式复用 `OPENAI_API_KEY` Secret。同一 DMXAPI 账户的 token 仍须允许 Jev 模型及专用接口；若翻译可用但 Jev 返回权限错误，可提供单独的 `JEV_API_KEY` Secret，无须更换翻译配置。本地运行须自行设置 `JEV_API_KEY`。

## 数据行为

- 仅从官方 RSS 公告取批次，保留来源批次时间和生成时间，不把提交日期当公告日。
- 沿用旧项目的 40 类配置，其中 31 类启用；匹配原文标题和摘要中的 `\bllm|\bagent`，忽略大小写，并保留 `robot` 排除规则。
- 只保留 `announceType=new`，在翻译前排除 `cross`、`replace` 和 `replace-cross`；同日归档重跑也会重新筛选并复用成功译文。按公告类型筛选，不按版本后缀判断；只合并本批次重复的完整版本 ID，不跨日期排除，不把 v1 和 v2 合并。
- `stats.fetched` 保留完整来源批次的去重条目数，`stats.matched` 为通过公告类型、分类和专题筛选后实际展示的论文数。
- RSS 未保证首分类就是主分类，`primaryCategory` 留空。未提供的机构为 `[]`、更新时间为 `null`，不下载 PDF 补元数据。
- 整个 CS feed 达到 2,000 条时，改为依次读取启用分类并合并；任何单分类仍达到限制，或分类批次发生变化，就失败并保留已有归档。
- 只有有效且批次日期正确的空来源才写零篇。HTTP 错误、无效 XML、挑战网页、畸形条目或旧批次均不写空日报。
- 归档中的完整英文元数据可用于重跑。成功译文不重复请求，未成功项继续尝试；失败始终保留 `fallback` 状态。不会校对翻译内容。
- 标签不扩大入选范围。LLM、Agent 分别按原文 `\bllm`、`\bagent` 匹配，软件工程依据 `cs.SE`；其余六个标签由 Jev 根据英文标题、摘要和分类判断，不读取 PDF。固定名称、边界与展示顺序见 [标签方案](plans/arxiv-daily-tags.md) 和 `shared/daily-tags.json`。
- 翻译和打标分别缓存。相同英文输入、模型、规则版本及阈值下，成功标签（包括六个细标签均未命中）可复用，普通重跑仅补失败或旧归档缺失的标签。更改上述配置或原文输入会重新打标，不影响已有成功译文。
- Jev 暂时性错误有限重试。401/402/403/404，或暂时性服务错误、网络错误及超时耗尽重试后，会停止尚未发起的打标请求；已在进行的请求结束后保存结果，不继续逐篇等待失效服务。成功项继续保留，未成功项保留规则标签与 `tagging.status=fallback`，后续重跑可补齐。Actions Summary 分别显示翻译、Jev 成功及规则回退数量；旧归档缺少打标结果时单独计数，不冒充成功。
- 每日 JSON 与日期索引分别原子写入；索引包含每日文件字节的 SHA-256。OSS 上传由独立发布命令负责。

完整公共接口见 [日报 JSON 约定](data-contract.md)。测试使用本地 HTTP 服务承载公开 RSS 和合成模型响应，不会实际调用翻译或 Jev 服务。
