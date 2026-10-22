# 每日公告采集器

在仓库根目录运行：

```sh
uv sync --locked --group dev
uv run --locked python -m collector --output-dir data/arxiv-daily
uv run --locked python -m collector --date 2026-10-22 --output-dir data/arxiv-daily
uv run --locked python -m pytest tests/test_collector.py
```

默认日报日期为北京时间今天。`--date` 用于补跑已有归档日的失败译文；未保存来源的历史日期会失败，不使用今天的公告补造历史。缺少翻译配置或调用失败时，仍会生成保留完整英文标题和摘要的有效日报。

## 环境配置

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `OPENAI_API_KEY` | 空 | 兼容 Chat Completions 接口的密钥；空值时使用英文 |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | 翻译接口基地址 |
| `OPENAI_MODEL` | `gpt-4o-mini` | 翻译模型，部署时显式设置实际模型 |
| `OPENAI_THINKING` | 空 | 设为 `disabled` 时发送提供商的禁用推理参数，其余情况不发送 |
| `TRANSLATION_BATCH_SIZE` | `10` | 每个模型请求包含的论文数 |
| `TRANSLATION_WORKERS` | `3` | 并发模型请求数 |
| `ARXIV_FEED_URL` | `https://rss.arxiv.org/rss/cs` | 官方整个 CS 公告源；本地测试可替换 HTTP 地址 |
| `ARXIV_RETRY_ATTEMPTS` | `3` | 来源网络或解析失败后的最大尝试次数 |
| `ARXIV_RETRY_DELAY_SECONDS` | `2` | 来源重试初始间隔，后续指数增加 |

凭证由运行环境或 GitHub Secrets 注入。采集器不自动读取、复制或归档 `.env`。日志只输出错误类别和 HTTP 状态，不输出提供商错误正文、请求头或密钥。

## 数据行为

- 仅从官方 RSS 公告取批次，保留来源批次时间和生成时间，不把提交日期当公告日。
- 沿用旧项目的 40 类配置，其中 31 类启用；匹配原文标题和摘要中的 `\bllm|\bagent`，忽略大小写，并保留 `robot` 排除规则。
- 只保留 `announceType=new`，在翻译前排除 `cross`、`replace` 和 `replace-cross`；同日归档重跑也会重新筛选并复用成功译文。按公告类型筛选，不按版本后缀判断；只合并本批次重复的完整版本 ID，不跨日期排除，不把 v1 和 v2 合并。
- `stats.fetched` 保留完整来源批次的去重条目数，`stats.matched` 为通过公告类型、分类和专题筛选后实际展示的论文数。
- RSS 未保证首分类就是主分类，`primaryCategory` 留空。未提供的机构为 `[]`、更新时间为 `null`，不下载 PDF 补元数据。
- 整个 CS feed 达到 2,000 条时，改为依次读取启用分类并合并；任何单分类仍达到限制，或分类批次发生变化，就失败并保留已有归档。
- 只有有效且批次日期正确的空来源才写零篇。HTTP 错误、无效 XML、挑战网页、畸形条目或旧批次均不写空日报。
- 归档中的完整英文元数据可用于重跑。成功译文不重复请求，未成功项继续尝试；失败始终保留 `fallback` 状态。不会校对翻译内容。
- 每日 JSON 与日期索引分别原子写入；索引包含每日文件字节的 SHA-256。OSS 上传由独立发布命令负责。

完整公共接口见 [日报 JSON 约定](data-contract.md)。测试使用本地 HTTP 服务承载公开 RSS 和合成模型响应，不会实际调用翻译服务。
