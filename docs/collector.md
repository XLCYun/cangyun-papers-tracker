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
| `ARXIV_LIST_URL` | `https://arxiv.org/list/cs/new` | 官方 CS 总区公告页；本地测试可替换 HTTP 地址，分页参数由采集器构造 |
| `ARXIV_PAGE_DELAY_SECONDS` | `3` | 公告分页和首页复核请求之间的间隔；本地固定响应测试可设为 `0` |
| `ARXIV_RETRY_ATTEMPTS` | `3` | 来源请求、解析或批次一致性失败后，重试整个批次的最大次数 |
| `ARXIV_RETRY_DELAY_SECONDS` | `2` | 批次重试初始间隔，后续指数增加 |

凭证由运行环境或 GitHub Secrets 注入。采集器不自动读取、复制或归档 `.env`。日志只输出错误类别和 HTTP 状态，不输出提供商错误正文、请求头或密钥。

线上翻译通过 DMXAPI 调用 `glm-5.3-flash`。GitHub Actions 优先将独立的 `JEV_API_KEY` Secret 注入打标步骤；未设置时，显式复用 `OPENAI_API_KEY` Secret。同一 DMXAPI 账户的 token 仍须允许 Jev 模型及专用接口；若翻译可用但 Jev 返回权限错误，可提供单独的 `JEV_API_KEY` Secret，无须更换翻译配置。本地运行须自行设置 `JEV_API_KEY`。

## 数据行为

- 分页读取官方 `/list/cs/new` 的完整公告批次，不再读取 RSS 或子分类源。每页核对公告日期、分节计数、连续序号和唯一 ID，完成后重新读取首页确认批次未变化；缺页、重复条目、混合批次或数量不一致都失败，不发布部分结果。
- 覆盖总区中的全部 CS 分类，不再使用 31 类启用清单作为入选条件。匹配原文标题和摘要中的 `\bllm|\bagent`，忽略大小写，并保留 `robot` 文本排除规则；这不等同于排除整个 `cs.RO` 分类。
- 只保留 `announceType=new`，在翻译前排除 `cross` 和 `replace`；旧归档中的 `replace-cross` 同样排除。公告类型与版本后缀分别处理，不把“没有版本号”或“v1”当作 `new` 的替代条件。
- 翻译和打标前直接读取目标日期 D 之前 `[D-7, D-1]` 七个自然日的 JSON，按去除版本后缀的 arXiv ID 排除重复。只读存在的文件，不请求 OSS，也不向前凑足七份非空日报；窗口内已有归档损坏则失败。部分重复剔除后继续，非空候选全部重复则失败，不生成当天文件或索引。
- `stats.fetched` 为完整来源公告条数，包含各分节；`stats.matched` 为最终展示数量。新归档的 `stats.duplicates` 记录前七天已收录、在模型调用前被剔除的候选数量。Actions Summary 显示来源类型和该数量，旧归档缺少去重统计时按 0 展示。
- 分类和 `primaryCategory` 按页面保存，机构未知时为 `[]`。公告日期放入 `source.announcementDate`；页面未提供精确更新时间或论文提交时间，因此 `source.updatedAt`、论文 `publishedAt` 和 `updatedAt` 使用 `null`。保留页面提供的论文 ID 和 HTML 链接，未提供 HTML 链接时为 `null`；不擅自补 `v1`，不逐篇请求 API 或下载 PDF 补元数据。
- 北京时间周六、周日在来源和模型请求前按正常排期生成 `announcement-schedule` 零篇日报，Actions 成功，发布后 ECS 认定当天完成。完整当日公告仅因专题筛选无命中时也成功生成零篇。非周末的空响应、HTTP 错误、挑战网页、畸形条目或旧批次都失败，不能伪装成零篇；不额外维护节假日日历。
- 本轮只影响后续首次采集，不重建历史日报。重跑已有日期继续复用归档来源、原始抓取时间和去重统计，不读取今天的新批次，也不因自身已有相同论文而失败。
- 归档中的完整英文元数据可用于重跑。成功译文不重复请求，未成功项继续尝试；失败始终保留 `fallback` 状态。不会校对翻译内容。
- 标签不扩大入选范围。LLM、Agent 分别按原文 `\bllm`、`\bagent` 匹配，软件工程依据 `cs.SE`；其余六个标签由 Jev 根据英文标题、摘要和分类判断，不读取 PDF。固定名称、边界与展示顺序见 [标签方案](plans/arxiv-daily-tags.md) 和 `shared/daily-tags.json`。
- 翻译和打标分别缓存。相同英文输入、模型、规则版本及阈值下，成功标签（包括六个细标签均未命中）可复用，普通重跑仅补失败或旧归档缺失的标签。更改上述配置或原文输入会重新打标，不影响已有成功译文。
- Jev 暂时性错误有限重试。401/402/403/404，或暂时性服务错误、网络错误及超时耗尽重试后，会停止尚未发起的打标请求；已在进行的请求结束后保存结果，不继续逐篇等待失效服务。成功项继续保留，未成功项保留规则标签与 `tagging.status=fallback`，后续重跑可补齐。Actions Summary 分别显示翻译、Jev 成功及规则回退数量；旧归档缺少打标结果时单独计数，不冒充成功。
- 每日 JSON 与日期索引分别原子写入；索引包含每日文件字节的 SHA-256。OSS 上传由独立发布命令负责。

完整公共接口见 [日报 JSON 约定](data-contract.md)，本轮范围见 [CS 总区分页采集方案](plans/cs-announcement-pagination.md)。测试使用本地 HTTP 服务承载公告 HTML 和合成模型响应，不会实际调用翻译或 Jev 服务。旧 RSS 归档继续可读，不需要迁移；`ARXIV_FEED_URL` 不再提供采集模式。
