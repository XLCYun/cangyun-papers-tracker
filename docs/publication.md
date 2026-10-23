# 日报发布与恢复

每日流程由 ECS 的 systemd timer 在北京时间 13:30 开始触发；GitHub Actions 不再配置 cron，只接受 `workflow_dispatch`。ECS 会检查当日归档和在途任务，每 15 分钟补查，最晚至 20:45，每日最多发起 3 次采集。具体安装、Token 权限和重试规则见 [ECS 触发器](ecs-trigger.md)。

也可在 Actions 的 **Daily arXiv** 页面手动运行，日期留空表示北京时间今天，填写日期则只补跑已有归档日。流程只允许从 `main` 运行，并串行执行。`verify_only` 默认关闭；开启后仅运行权限探针，不采集、不调用模型、不提交或发布数据。

## 发布命令

```sh
uv sync --locked --group dev
uv run --locked python -m collector.publish --date 2026-10-22 --data-dir data/arxiv-daily --check
uv run --locked python -m collector.publish --date 2026-10-22 --data-dir data/arxiv-daily
```

`--check` 只校验本地 JSON、日期索引、内容哈希、文件路径和统计，不读取 OSS 凭证、不访问云端。正式发布使用以下环境配置，不自动读取 `.env`：

| 变量 | 配置位置 | 用途 |
| --- | --- | --- |
| `OSS_ACCESS_KEY_ID`、`OSS_ACCESS_KEY_SECRET` | GitHub Secrets | 专用 JSON uploader；仅需目标前缀的 `PutObject`、`GetObject` |
| `OSS_SECURITY_TOKEN` | 本地可选环境变量 | 使用临时 STS 凭证时传入 |
| `OSS_BUCKET`、`OSS_ENDPOINT` | Repository variables | Bucket 与 HTTPS 区域端点 |
| `OSS_PUBLIC_BASE_URL` | Repository variables | 匿名读取的公开 HTTPS 域名，不含数据前缀 |
| `OSS_PREFIX` | Repository variables | 必须为 `research/arxiv-daily` |
| `OPENAI_API_KEY` | GitHub Secrets | 只注入采集步骤 |
| `OPENAI_BASE_URL`、`OPENAI_MODEL`、`OPENAI_THINKING` | Repository variables | 翻译接口；`OPENAI_THINKING=disabled` 会禁用提供商推理参数 |
| `JEV_API_KEY` | 可选 GitHub Secret | Jev 专用密钥；配置后优先使用，否则采集步骤显式使用现有 `OPENAI_API_KEY` Secret |
| `JEV_BASE_URL`、`JEV_MODEL`、`JEV_THRESHOLD`、`JEV_WORKERS` | Repository variables，可选 | 默认分别为 `https://www.dmxapi.cn/typesafe/v1`、`jev-1.13.0`、`0.7`、`3`；Jev 请求 `/systemone`，独立于翻译接口 |
| `JEV_RULES_VERSION`、`JEV_RETRY_ATTEMPTS`、`JEV_RETRY_DELAY_SECONDS` | Repository variables，可选 | 默认分别为 `daily-tags-v3`、`3`、`2`；重试间隔单位为秒 |

两个模型密钥只注入采集步骤，不进入发布 job、网页构建或 Artifact。翻译可用不代表 token 已获得 Jev 权限；遇到 Jev 403 时检查该 token 的模型及专用接口权限，必要时设置独立的 `JEV_API_KEY` Secret。不要把密钥写入仓库变量、日报或日志。

测试可用回环 HTTP 服务替代 OSS，生产端点必须使用 HTTPS。发布器不会列举 Bucket、删除对象、改变 Bucket ACL/CORS 或访问 Benchmark 文件；公开权限通过每次 JSON `PutObject` 的 `x-oss-object-acl: public-read` 设置。

## 顺序与缓存

1. 只读采集 job 完成筛选、翻译和独立打标，生成每日 JSON 和索引，通过本地校验后保存只含 `data/arxiv-daily/*.json` 的 14 天 Artifact。不会归档环境文件、PDF、原始上游错误响应或日志。
2. 发布 job 才有仓库写权限。先将正式每日 JSON 和索引提交、推送到 `main`，然后自行发布 OSS，不依赖机器人提交触发另一个 `push` 流程。
3. 逐一核验索引中的日报引用，将本地正式 JSON 上传到 `<date>/<sha256>.json`。同名对象禁止覆盖；已存在时验证其字节，再通过匿名域名核验长度及 SHA-256。所有对象均在同一前缀内。
4. 每日对象使用 `public, max-age=31536000, immutable`。验证全部引用后，才覆盖 `index.json`，使用 `public, max-age=60, must-revalidate`，并匿名核验索引字节。读取带随机校验查询参数和 `no-cache`，避免旧缓存造成误判。

若新索引上传或匿名校验失败，发布器尝试恢复旧索引并验证；首次发布没有旧索引时恢复有效的空索引。若网络故障连回退也无法验证，会明确返回失败，不能声称线上已恢复。

## 失败恢复

- 来源或本地校验失败时不进入发布 job，也不会把抓取失败记为零篇。
- 翻译失败仍归档英文，Actions 日志和 Summary 如实显示 `translated` / `fallback` 数；HTTP 状态只输出状态码，不输出上游错误正文、请求头或密钥。英文回退不让发布失败。同日重跑复用已有成功译文，仅重试回退项。
- Jev 失败仍归档规则标签，Summary 单独显示 `tagged`、规则标签回退和旧归档缺少打标结果的数量。打标失败不影响译文，也不阻止发布；页面不额外提示。401/402/403/404，或暂时性服务错误、网络错误及超时耗尽有限重试后，会停止尚未发起的请求；已经进行的请求结束后归档成功项和规则回退项，避免持续故障时为每篇论文重复等待，直至任务超时。
- 在 Actions 手动填入已有日期即可补标签和失败译文，无须重新抓取来源或下载 PDF。相同输入、模型、规则版本与阈值下的成功标签会复用；五个模型标签都未命中也算成功。改模型、规则版本或阈值会重新打标，不要为普通失败重跑改这些值。旧归档缺少标签时会补齐，未配置 Jev 也会保留有效的规则标签与回退状态。
- OSS 失败时，已推送的 Git JSON 是长期恢复源，采集 Artifact 是短期副本。下一次发布会同时补齐索引引用的缺失日报对象，不会把缺失对象写进可见索引。
- Git 推送遇到并发改动时使用普通 rebase；冲突会终止流程并保留 Artifact，不强制推送或改写远端历史。修复后重新运行即可。

测试通过 `uv run --locked python -m pytest` 运行，外部服务均由本地 HTTP 固定响应替代，不实际调用翻译、Jev 接口或操作云资源。CI 同时验证 Python、网页构建与测试，以及 GitHub Actions 语法；Actions 使用官方完整提交 SHA，actionlint 使用固定版本和下载校验和。
