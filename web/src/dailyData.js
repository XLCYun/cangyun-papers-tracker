import dailyTags from "../../shared/daily-tags.json";

const defaultRoot = import.meta.env.MODE === "development"
  ? "/daily-data/"
  : "https://updates.cyunlab.com/research/arxiv-daily/";

function ruleTags(paper) {
  const text = `${paper.title}\n${paper.abstract}`;
  // Python's source rules use Unicode word boundaries and deliberately allow suffixes.
  return [
    ...(/(?:^|[^\p{L}\p{N}_])llm/iu.test(text) ? ["LLM"] : []),
    ...(/(?:^|[^\p{L}\p{N}_])agent/iu.test(text) ? ["Agent"] : []),
    ...(paper.categories.includes("cs.SE") ? ["软件工程"] : []),
  ];
}

const modelTags = dailyTags.filter((tag) => !["LLM", "Agent", "软件工程"].includes(tag));
const taggingFields = ["status", "model", "rulesVersion", "threshold", "inputSha256", "scores"];
const probability = (value) => typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1;
// Python str.strip includes these four separators, but does not discard U+FEFF.
const nonempty = (value) => typeof value === "string" && /[^\p{White_Space}\u001c-\u001f]/u.test(value);

function readTags(paper) {
  if (!Object.hasOwn(paper, "tags") && !Object.hasOwn(paper, "tagging")) return ruleTags(paper);
  const tagging = paper.tagging;
  if (!Array.isArray(paper.tags) || !tagging || typeof tagging !== "object" || Array.isArray(tagging) ||
      Object.keys(tagging).length !== taggingFields.length || !taggingFields.every((field) => Object.hasOwn(tagging, field)) ||
      !["tagged", "fallback"].includes(tagging.status) || !nonempty(tagging.model) || !nonempty(tagging.rulesVersion) ||
      !probability(tagging.threshold) || typeof tagging.inputSha256 !== "string" || !/^[a-f0-9]{64}$/.test(tagging.inputSha256) ||
      !tagging.scores || typeof tagging.scores !== "object" || Array.isArray(tagging.scores)) throw new Error("论文主题标签无效");
  const scoreTags = Object.keys(tagging.scores);
  if (tagging.status === "tagged"
    ? scoreTags.length !== modelTags.length || !modelTags.every((tag) => Object.hasOwn(tagging.scores, tag) && probability(tagging.scores[tag]))
    : scoreTags.length !== 0) throw new Error("论文主题分数无效");
  const ordered = dailyTags.filter((tag) => paper.tags.includes(tag));
  if (paper.tags.length !== ordered.length || paper.tags.some((tag, index) => tag !== ordered[index])) throw new Error("论文主题标签无效");
  // The collector owns rule labels: Unicode word tables may differ between
  // Python and a reader's browser. Only legacy documents derive them here.
  const semantic = paper.tags.filter((tag) => modelTags.includes(tag));
  const expected = modelTags.filter((tag) => tagging.status === "tagged" && tagging.scores[tag] >= tagging.threshold);
  if (semantic.length !== expected.length || semantic.some((tag, index) => tag !== expected[index])) throw new Error("论文主题标签与判定不符");
  return paper.tags;
}

function dataRoot() {
  const configured = import.meta.env.VITE_DAILY_DATA_BASE_URL || defaultRoot;
  const root = new URL(configured.endsWith("/") ? configured : `${configured}/`, window.location.origin);
  if (root.username || root.password || root.search || root.hash ||
      (root.protocol !== "https:" && root.origin !== window.location.origin)) throw new Error("日报地址无效");
  return root;
}

function validDate(value) {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
}

async function readJson(file, signal) {
  const response = await fetch(new URL(file, dataRoot()).href, {
    signal, credentials: "omit", cache: file === "index.json" ? "no-cache" : "default",
  });
  if (!response.ok) throw new Error("日报请求失败");
  return response.json();
}

export async function loadDailyIndex(signal) {
  const index = await readJson("index.json", signal);
  if (index?.schemaVersion !== 1 || !Array.isArray(index.days)) throw new Error("日报索引无效");
  const dates = new Set();
  for (const entry of index.days) {
    if (!validDate(entry?.date) || dates.has(entry.date) || !Number.isInteger(entry.count) || entry.count < 0 ||
        !/^[a-f0-9]{64}$/.test(entry.sha256) || entry.file !== `${entry.date}/${entry.sha256}.json`) {
      throw new Error("日报索引对象路径无效");
    }
    dates.add(entry.date);
  }
  return index;
}

export async function loadDailyDocument(entry, signal) {
  const daily = await readJson(entry.file, signal);
  const stats = daily?.stats;
  if (daily?.schemaVersion !== 1 || daily.date !== entry.date || daily.timezone !== "Asia/Shanghai" ||
      !Array.isArray(daily.papers) || !stats || daily.papers.length !== entry.count ||
      ![stats.fetched, stats.matched, stats.translated, stats.fallback].every((count) => Number.isInteger(count) && count >= 0) ||
      stats.matched !== daily.papers.length || stats.fetched < stats.matched ||
      stats.translated + stats.fallback !== stats.matched) throw new Error("日报内容无效");
  const ids = new Set();
  for (const paper of daily.papers) {
    if (!paper || typeof paper.id !== "string" || !paper.id.trim() || ids.has(paper.id) ||
        ![paper.title, paper.abstract].every((value) => typeof value === "string" && value.trim()) ||
        ![paper.authors, paper.affiliations, paper.categories].every((values) => Array.isArray(values) && values.every((value) => typeof value === "string" && value.trim())) ||
        !["translated", "fallback"].includes(paper.translation?.status) ||
        ![paper.translation.title, paper.translation.abstract].every((value) => typeof value === "string" && value.trim()) ||
        typeof paper.translation.brief !== "string") throw new Error("论文内容无效");
    ids.add(paper.id);
    for (const [field, path] of [["absUrl", "abs"], ["pdfUrl", "pdf"], ["htmlUrl", "html"]]) {
      if (field !== "absUrl" && paper[field] == null) continue;
      const url = new URL(paper[field]);
      if (url.protocol !== "https:" || url.hostname !== "arxiv.org" || url.username || url.password ||
          !url.pathname.startsWith(`/${path}/`)) throw new Error("论文原文链接无效");
    }
  }
  if (daily.papers.filter((paper) => paper.translation.status === "translated").length !== stats.translated) throw new Error("日报统计无效");
  daily.papers = daily.papers.map((paper) => ({ ...paper, tags: readTags(paper) }));
  return daily;
}
