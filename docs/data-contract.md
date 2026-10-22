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
      "id": "2610.00001v2",
      "title": "Example Agent paper",
      "abstract": "Original abstract.",
      "authors": ["Example Author"],
      "affiliations": [],
      "categories": ["cs.AI"],
      "primaryCategory": "cs.AI",
      "publishedAt": "2026-10-22T00:00:00-04:00",
      "updatedAt": null,
      "announceType": "replace",
      "absUrl": "https://arxiv.org/abs/2610.00001v2",
      "pdfUrl": "https://arxiv.org/pdf/2610.00001v2",
      "htmlUrl": "https://arxiv.org/html/2610.00001v2",
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
- 未提供的机构使用 `[]`，未提供的更新时间使用 `null`，不推测补造。`publishedAt` 按来源含义保存，不用于猜日报日期。
- 翻译状态只有 `translated` 和 `fallback`。回退时 `translation.title` 与 `translation.abstract` 使用英文，`brief` 为 `""`。上游错误的完整响应和凭证不写入公开 JSON。
- `stats.matched === papers.length`，`translated + fallback === matched`。
- 同日重跑可以读取已有每日文件复用成功译文；缺失的历史日期不得用当前 feed 改写成历史数据。

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
- 采集器与发布器的可配置 HTTP 服务、模型和 OSS 凭证均使用环境变量，网站只接收公开的数据根地址与备案配置。
