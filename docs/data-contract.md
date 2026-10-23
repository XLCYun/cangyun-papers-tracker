# 日报 JSON 接口 v1

这是采集器、OSS 发布器和网页共同遵循的接口。日期均为 `YYYY-MM-DD`，日报日期使用 `Asia/Shanghai`；时间戳为带时区的 ISO 8601 字符串。JSON 使用 UTF-8，文件末尾换行。

## 每日文件

Git 路径为 `data/arxiv-daily/YYYY-MM-DD.json`。对象的最小形状如下；空日仍包含相同字段，`papers` 为 `[]`，统计为零。

```json
{
  "schemaVersion": 1,
  "date": "2026-10-22",
  "timezone": "Asia/Shanghai",
  "fetchedAt": "2026-10-22T13:30:00+08:00",
  "source": {
    "url": "https://rss.arxiv.org/rss/cs",
    "updatedAt": "2026-10-22T00:00:00-04:00"
  },
  "stats": { "fetched": 1, "matched": 1, "translated": 1, "fallback": 0 },
  "papers": [
    {
      "id": "2610.00001v1",
      "title": "Example Agent paper",
      "abstract": "Original abstract.",
      "authors": ["Example Author"],
      "affiliations": [],
      "categories": ["cs.AI"],
      "primaryCategory": "cs.AI",
      "publishedAt": "2026-10-22T00:00:00-04:00",
      "updatedAt": null,
      "announceType": "new",
      "absUrl": "https://arxiv.org/abs/2610.00001v1",
      "pdfUrl": "https://arxiv.org/pdf/2610.00001v1",
      "htmlUrl": "https://arxiv.org/html/2610.00001v1",
      "translation": {
        "status": "translated",
        "title": "示例 Agent 论文",
        "abstract": "中文摘要。",
        "brief": "一句话总结。"
      }
    }
  ]
}
```

- `id` 为来源给出的 arXiv ID；有版本后缀就保留，不做跨日排除。
- 当前日报只保留 `announceType=new` 的条目，翻译前排除其余公告类型。结构校验仍接受四种合法类型，以便读取旧归档后重新筛选。
- 未提供的机构使用 `[]`，未提供的更新时间使用 `null`，不推测补造。`publishedAt` 按来源含义保存，不用于猜日报日期。
- 翻译状态只有 `translated` 和 `fallback`。回退时 `translation.title` 与 `translation.abstract` 使用英文，`brief` 为 `""`。上游错误的完整响应和凭证不写入公开 JSON。
- `stats.fetched` 为完整来源批次的去重条目数；`stats.matched === papers.length` 为筛选后展示数量，`translated + fallback === matched`。
- 同日重跑可以读取已有每日文件复用成功译文；缺失的历史日期不得用当前 feed 改写成历史数据。
- 重跑归档保留原始 `source` 和 `fetchedAt`，索引的 `updatedAt` 记录本次归档更新时间。采集器在重写前和发布器在上传前使用同一校验器检查必填元数据、翻译字段与统计；无效归档不会被改写或发布。

## 日报主题标签

标签方案见 [每日 arXiv 主题标签方案](plans/arxiv-daily-tags.md)。九个标签的唯一标识与展示顺序维护在 `shared/daily-tags.json`，Python 和网页共用。`GUI Agent` 在网页显示为 `GUI/Web Agent`；JSON 标识、评分、规则版本与缓存保持原样，改名不触发模型请求。`schemaVersion` 保持为 1，以下字段是向后兼容的扩展：旧日报可同时缺少 `tags` 和 `tagging`，新采集及补标签后两者必须同时存在。

每篇论文新增：

```json
{
  "tags": ["LLM", "Agent", "CodingAgent", "软件工程"],
  "tagging": {
    "status": "tagged",
    "model": "jev-1.13.0",
    "rulesVersion": "daily-tags-v2",
    "threshold": 0.7,
    "inputSha256": "英文标题、摘要和分类的规范化 JSON 字节的 SHA-256",
    "scores": {
      "AI4S": 0.01,
      "CodingAgent": 0.96,
      "GUI Agent": 0.12,
      "AgentOps": 0.1,
      "AgentHarness": 0.2,
      "企业Agent": 0.15
    }
  }
}
```

- `tags` 仅允许九个固定名称，无重复，按共享清单顺序排列。一篇论文可有多个标签。
- LLM、Agent 分别按现有英文标题和摘要的 `\bllm`、`\bagent` 规则判断，忽略大小写；软件工程按 `categories` 包含 `cs.SE` 判断。三个规则标签不由模型改写，也不根据细标签自动补打。
- 兼容已发布的 `daily-tags-v1` 归档，其成功记录仍可保留不含 `GUI Agent` 的五项评分。新默认规则 `daily-tags-v2` 必须具备六项评分；缺少 GUI 评分不能标为新版成功。历史归档仅在显式补跑时升级，旧 JSON 及其哈希不被读取过程修改。
- Jev 分别判断其余六个标签。`scores` 在成功时必须恰好包含这六个名称，每项为有限的 0–1 数值；分数达到 `threshold` 才加入对应标签。
- `tagging.status` 只有 `tagged` 和 `fallback`。失败时保留规则标签，`scores` 为 `{}`，不会写入模型错误正文或凭证。六个细标签都不命中、但得到完整有效响应，也属于成功。
- `model`、`rulesVersion`、`threshold`、`inputSha256` 用于判断是否可以复用；同一输入及配置的成功结果不重复调用，失败项可重试。显式更改模型、规则版本、阈值或原文输入会使缓存失效。
- 打标状态与 `translation.status` 独立；不改变原有 `stats` 口径。标签数据随每日文件字节参与索引哈希。
- 网页只在旧日报同时缺少 `tags` 和 `tagging` 时，据英文标题、摘要和分类推导三个规则标签，不猜测六个模型标签。带标签的新日报以采集器发布的三个规则标签为准，避免 Python 与浏览器的 Unicode 版本差异导致有效日报无法读取；网页仍校验固定标签、顺序、无重复、打标字段，以及六个模型标签与分数和阈值的一致性。畸形数据继续走原有读取错误处理。
- `tagging` 必须恰好含有示例中的六个字段，不接受额外字段。`model` 和 `rulesVersion` 按 Python `str.strip()` 的空白语义判断非空，包含 Unicode 空白及 `U+001C`–`U+001F` 分隔控制字符；`U+FEFF` 不作为空白删除。采集及发布校验使用同一个纯函数派生规则与模型标签，成功缓存、即时结果和最终校验保持一致。
- Jev 使用独立环境配置 `JEV_API_KEY`、`JEV_BASE_URL`、`JEV_MODEL`、`JEV_THRESHOLD`、`JEV_WORKERS`。默认基地址为 `https://www.dmxapi.cn/typesafe/v1`，请求 `/systemone`；默认模型 `jev-1.13.0`、阈值 `0.7`、并发 `3`。GitHub Actions 优先使用专用 `JEV_API_KEY` Secret，未设置时将现有 DMXAPI `OPENAI_API_KEY` Secret 显式注入；采集器不隐式挪用翻译凭证。未配置 Jev 密钥时仍可生成带规则标签的有效日报。
- `JEV_RULES_VERSION` 默认 `daily-tags-v2`；规则变更时显式升级版本以触发重打标。暂时性请求错误由 `JEV_RETRY_ATTEMPTS`（默认 `3`）和 `JEV_RETRY_DELAY_SECONDS`（默认 `2`，指数退避）限制。认证、权限或接口不存在错误，以及暂时性服务错误、网络错误或超时耗尽重试后，会停止尚未发起的打标请求；等待已经进行的请求结束后保存成功结果与其余规则回退，不逐篇消耗整日任务时限。

## 日期索引

Git 路径为 `data/arxiv-daily/index.json`，OSS 索引为 `research/arxiv-daily/index.json`。

```json
{
  "schemaVersion": 1,
  "updatedAt": "2026-10-22T13:35:00+08:00",
  "days": [
    {
      "date": "2026-10-22",
      "count": 1,
      "sha256": "每日文件字节的完整 SHA-256",
      "file": "2026-10-22/每日文件字节的完整SHA-256.json"
    }
  ]
}
```

`days` 按日期倒序，无重复日期。空索引使用 `updatedAt: null`、`days: []`。

发布器将每日文件上传到 `research/arxiv-daily/<date>/<sha256>.json` 并验证，再上传索引。前端默认数据根地址为 `https://updates.cyunlab.com/research/arxiv-daily/`，索引中的 `file` 为相对此根地址的路径。禁止外域、父目录和不匹配日期/哈希的路径。

## 命令边界

- `uv run python -m collector --date YYYY-MM-DD --output-dir data/arxiv-daily`：采集并翻译，写每日文件及索引。默认使用北京时间今天。历史补跑只能使用已经归档的该日来源内容，不抓取或导入旧日报。
- `uv run python -m collector.publish --date YYYY-MM-DD --data-dir data/arxiv-daily`：发布并验证当日不可变对象，最后发布索引；失败保留线上旧索引。
- 加 `--check` 可在没有 OSS 配置的环境中只校验本地 JSON 和索引。发布前会验证全部索引引用，补齐此前已在 Git 备份、但尚未成功上传的日报；索引回退与恢复行为见 [发布说明](publication.md)。
- 采集器与发布器的可配置 HTTP 服务、模型和 OSS 凭证均使用环境变量，网站只接收公开的数据根地址与备案配置。
