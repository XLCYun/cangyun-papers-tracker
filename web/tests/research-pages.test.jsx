import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import App from "../src/App.jsx";
import benchmarkPapers from "../src/data/enterprise-papers.json";

const hash = "a".repeat(64);
const root = "https://updates.cyunlab.com/research/arxiv-daily/";
const paper = {
  id: "2610.00001v2", title: "A practical agent benchmark", abstract: "Original English abstract.",
  authors: ["Example Author"], affiliations: [], categories: ["cs.AI"], primaryCategory: "cs.AI",
  publishedAt: "2026-10-21T20:00:00-04:00", updatedAt: null, announceType: "replace",
  absUrl: "https://arxiv.org/abs/2610.00001v2", pdfUrl: "https://arxiv.org/pdf/2610.00001v2",
  htmlUrl: "https://arxiv.org/html/2610.00001v2",
  translation: { status: "translated", title: "实用智能体评测", abstract: "完整中文摘要。", brief: "在企业任务中检验智能体。" },
};
function day(date, papers = [paper]) {
  const translated = papers.filter((item) => item.translation.status === "translated").length;
  return { schemaVersion: 1, date, timezone: "Asia/Shanghai", fetchedAt: `${date}T13:30:00+08:00`,
    source: { url: "https://rss.arxiv.org/rss/cs", updatedAt: `${date}T00:00:00-04:00` },
    stats: { fetched: papers.length, matched: papers.length, translated, fallback: papers.length - translated }, papers };
}
function listingDay(date, papers = [{ ...paper, announceType: "new", publishedAt: null, htmlUrl: null }]) {
  return { ...day(date, papers),
    source: { kind: "cs-announcement-list", url: "https://arxiv.org/list/cs/new", updatedAt: null,
      announcementDate: date, counts: { total: 3, new: 2, cross: 1, replace: 0 } },
    stats: { ...day(date, papers).stats, fetched: 3, duplicates: 0 } };
}
function weekendDay(date) {
  return { ...day(date, []),
    source: { kind: "announcement-schedule", url: "https://info.arxiv.org/help/availability.html#announcement-schedule",
      updatedAt: null, reason: "weekend" },
    stats: { fetched: 0, matched: 0, translated: 0, fallback: 0, duplicates: 0 } };
}
function serve(days) {
  const entries = Object.entries(days).sort(([a], [b]) => b.localeCompare(a));
  vi.stubGlobal("fetch", vi.fn(async (url) => {
    if (String(url) === `${root}index.json`) return new Response(JSON.stringify({ schemaVersion: 1, updatedAt: null,
      days: entries.map(([date, value]) => ({ date, count: value.papers.length, sha256: hash, file: `${date}/${hash}.json` })) }));
    const selected = entries.find(([date]) => String(url) === `${root}${date}/${hash}.json`);
    return selected ? new Response(JSON.stringify(selected[1])) : new Response("Missing", { status: 404 });
  }));
}
function openDaily() {
  window.history.replaceState(null, "", "/arxiv-daily");
  return render(<App />);
}

test("daily defaults to today's Beijing date and shows that day's JSON papers", async () => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-21T17:30:00Z"));
  serve({ "2026-10-22": day("2026-10-22") });
  openDaily();
  expect(await screen.findByText("实用智能体评测")).toBeVisible();
  expect(screen.getByLabelText("日报日期")).toHaveValue("2026-10-22");
  expect(screen.getByText("A practical agent benchmark")).toBeVisible();
  expect(screen.getByText("在企业任务中检验智能体。")).toBeVisible();
});

test("a listing from an older announcement date is a read error instead of today's papers", async () => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-28T05:30:00Z"));
  const stale = listingDay("2026-10-28");
  stale.source.announcementDate = "2026-10-27";
  serve({ "2026-10-28": stale });
  openDaily();
  expect(await screen.findByRole("alert")).toHaveTextContent("暂时无法读取日报");
  expect(screen.queryAllByRole("article")).toHaveLength(0);
});

test.each([
  ["missing section", { total: 3, new: 2, cross: 1 }, { fetched: 3, duplicates: 0 }],
  ["inconsistent sections", { total: 4, new: 2, cross: 1, replace: 0 }, { fetched: 4, duplicates: 0 }],
  ["unexpected section", { total: 3, new: 2, cross: 1, replace: 0, other: 0 }, { fetched: 3, duplicates: 0 }],
  ["negative section", { total: 3, new: 3, cross: 1, replace: -1 }, { fetched: 3, duplicates: 0 }],
  ["fractional section", { total: 3, new: 2.5, cross: 0.5, replace: 0 }, { fetched: 3, duplicates: 0 }],
  ["fetched count mismatch", { total: 3, new: 2, cross: 1, replace: 0 }, { fetched: 2, duplicates: 0 }],
  ["negative duplicates", { total: 3, new: 2, cross: 1, replace: 0 }, { fetched: 3, duplicates: -1 }],
  ["missing duplicates", { total: 3, new: 2, cross: 1, replace: 0 }, { fetched: 3, duplicates: undefined }],
  ["more candidates than new announcements", { total: 3, new: 2, cross: 1, replace: 0 }, { fetched: 3, duplicates: 2 }],
])("invalid CS batch counts show a read error: %s", async (_name, counts, stats) => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-28T05:30:00Z"));
  const invalid = listingDay("2026-10-28");
  invalid.source.counts = counts;
  Object.assign(invalid.stats, stats);
  serve({ "2026-10-28": invalid });
  openDaily();
  expect(await screen.findByRole("alert")).toHaveTextContent("暂时无法读取日报");
  expect(screen.queryAllByRole("article")).toHaveLength(0);
});

test("a weekday cannot be presented as a scheduled weekend zero-paper day", async () => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-28T05:30:00Z"));
  serve({ "2026-10-28": weekendDay("2026-10-28") });
  openDaily();
  expect(await screen.findByRole("alert")).toHaveTextContent("暂时无法读取日报");
  expect(screen.queryByRole("heading", { name: "今天暂无论文" })).not.toBeInTheDocument();
});

test.each(["2026-10-24", "2026-10-25"])("normal weekend provenance shows a successful empty day: %s", async (date) => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(`${date}T05:30:00Z`));
  serve({ [date]: weekendDay(date), "2026-10-23": day("2026-10-23") });
  openDaily();
  expect(await screen.findByRole("heading", { name: "今天暂无论文" })).toBeVisible();
  expect(screen.getByLabelText("显示 0 篇论文")).toBeVisible();
  expect(screen.getByText(/按北京时间，arXiv 通常在周六、周日不发布新论文/)).toBeVisible();
  expect(screen.getByRole("button", { name: "查看最近一期" })).toBeVisible();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test.each([
  ["unexpected reason", (daily) => { daily.source.reason = "holiday"; }],
  ["invented source timestamp", (daily) => { daily.source.updatedAt = "2026-10-24T00:00:00+08:00"; }],
  ["fetched announcements", (daily) => { daily.stats.fetched = 1; }],
  ["removed duplicates", (daily) => { daily.stats.duplicates = 1; }],
  ["missing duplicate count", (daily) => { delete daily.stats.duplicates; }],
  ["nonempty papers", (daily) => { daily.papers = [paper]; Object.assign(daily.stats, { fetched: 1, matched: 1, translated: 1 }); }],
])("invalid weekend provenance is an error, not a successful empty day: %s", async (_name, alter) => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-24T05:30:00Z"));
  const invalid = weekendDay("2026-10-24");
  alter(invalid);
  serve({ "2026-10-24": invalid });
  openDaily();
  expect(await screen.findByRole("alert")).toHaveTextContent("暂时无法读取日报");
  expect(screen.queryByRole("heading", { name: "今天暂无论文" })).not.toBeInTheDocument();
});

test.each([
  ["unknown source kind", (daily) => { daily.source.kind = "unknown"; }],
  ["null source kind", (daily) => { daily.source.kind = null; }],
  ["non-HTTP source", (daily) => { daily.source.url = "file:///list/cs/new"; }],
  ["source with credentials", (daily) => { daily.source.url = "https://user:secret@arxiv.org/list/cs/new"; }],
  ["invented source update time", (daily) => { daily.source.updatedAt = "2026-10-28T00:00:00+08:00"; }],
  ["invented submission time", (daily) => { daily.papers[0].publishedAt = "2026-10-28T00:00:00+08:00"; }],
  ["missing update-time field", (daily) => { delete daily.papers[0].updatedAt; }],
  ["replacement item", (daily) => { daily.papers[0].announceType = "replace"; }],
  ["empty source batch", (daily) => {
    daily.papers = [];
    daily.source.counts = { total: 0, new: 0, cross: 0, replace: 0 };
    daily.stats = { fetched: 0, matched: 0, translated: 0, fallback: 0, duplicates: 0 };
  }],
])("malformed listing provenance cannot be displayed as a valid daily: %s", async (_name, alter) => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-28T05:30:00Z"));
  const invalid = listingDay("2026-10-28");
  alter(invalid);
  serve({ "2026-10-28": invalid });
  openDaily();
  expect(await screen.findByRole("alert")).toHaveTextContent("暂时无法读取日报");
  expect(screen.queryAllByRole("article")).toHaveLength(0);
});

test("CS listing papers with unknown timestamps and no HTML link retain normal reading controls", async () => {
  const user = userEvent.setup();
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-28T05:30:00Z"));
  serve({ "2026-10-28": listingDay("2026-10-28") });
  openDaily();
  await user.click(await screen.findByRole("button", { name: "展开 实用智能体评测 的论文详情" }));
  const details = screen.getByRole("region", { name: "实用智能体评测" });
  expect(within(details).getByText("完整中文摘要。")).toBeVisible();
  expect(within(details).getByRole("link", { name: "arXiv" })).toHaveAttribute("href", paper.absUrl);
  expect(within(details).getByRole("link", { name: "PDF" })).toHaveAttribute("href", paper.pdfUrl);
  expect(within(details).queryByRole("link", { name: "HTML" })).not.toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test.each([
  ["absUrl", "https://arxiv.org/abs/2610.99999"],
  ["pdfUrl", "https://arxiv.org/pdf/2610.99999"],
  ["pdfUrl", null],
  ["htmlUrl", "https://arxiv.org/html/2610.99999v1"],
  ["htmlUrl", undefined],
  ["pdfUrl", "https://arxiv.org:444/pdf/2610.00001v2"],
])("a new listing cannot send readers to another paper or a missing required link: %s %s", async (field, value) => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-28T05:30:00Z"));
  const invalid = listingDay("2026-10-28");
  invalid.papers[0][field] = value;
  serve({ "2026-10-28": invalid });
  openDaily();
  expect(await screen.findByRole("alert")).toHaveTextContent("暂时无法读取日报");
  expect(screen.queryAllByRole("article")).toHaveLength(0);
});

test("a complete announcement batch with no topic matches remains a successful zero-paper day", async () => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-28T05:30:00Z"));
  serve({ "2026-10-28": listingDay("2026-10-28", []) });
  openDaily();
  expect(await screen.findByRole("heading", { name: "今天暂无论文" })).toBeVisible();
  expect(screen.getByLabelText("显示 0 篇论文")).toBeVisible();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("opening a daily paper shows complete bilingual abstracts and original links", async () => {
  const user = userEvent.setup();
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-21T17:30:00Z"));
  serve({ "2026-10-22": day("2026-10-22") });
  openDaily();
  const toggle = await screen.findByRole("button", { name: "展开 实用智能体评测 的论文详情" });
  await user.click(toggle);
  const details = screen.getByRole("region", { name: "实用智能体评测" });
  expect(within(details).getByText("完整中文摘要。")).toBeVisible();
  expect(within(details).getByText("Original English abstract.")).toBeVisible();
  for (const [name, href] of [["arXiv", paper.absUrl], ["HTML", paper.htmlUrl], ["PDF", paper.pdfUrl]]) {
    const link = within(details).getByRole("link", { name });
    expect(link).toHaveAttribute("href", href);
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  }
});

test("daily search matches Chinese summaries, English titles, authors and classifications", async () => {
  const user = userEvent.setup();
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-21T17:30:00Z"));
  serve({ "2026-10-22": day("2026-10-22", [paper, { ...paper, id: "2610.00002", title: "Vision model", authors: ["Other Researcher"], categories: ["cs.CV"],
    translation: { status: "fallback", title: "Vision model", abstract: "Original English abstract.", brief: "" } }]) });
  openDaily();
  await screen.findByText("实用智能体评测");
  const search = screen.getByRole("searchbox", { name: "搜索日报论文" });
  for (const query of ["企业", "PRACTICAL", "Example Author", "cs.AI"]) {
    await user.clear(search);
    await user.type(search, query);
    expect(screen.getByText("实用智能体评测")).toBeVisible();
    expect(screen.queryByText("Vision model")).not.toBeInTheDocument();
  }
  await user.clear(search);
  await user.type(search, "nothing-matches");
  expect(screen.queryAllByRole("article")).toHaveLength(0);
  expect(screen.getByRole("heading", { name: "没有找到相关论文" })).toBeVisible();
  expect(screen.queryByText(/周六、周日/)).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "清除筛选" }));
  expect(search).toHaveValue("");
  expect(screen.getAllByRole("article")).toHaveLength(2);
});

test("a failed JSON request offers retry and never appears as a successful zero-paper day", async () => {
  const user = userEvent.setup();
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-21T17:30:00Z"));
  vi.stubGlobal("fetch", vi.fn(async () => new Response("Unavailable", { status: 503 })));
  openDaily();
  expect(await screen.findByRole("alert")).toHaveTextContent("暂时无法读取日报");
  expect(screen.queryByText(/周六、周日/)).not.toBeInTheDocument();
  serve({ "2026-10-22": day("2026-10-22") });
  await user.click(screen.getByRole("button", { name: "重试" }));
  expect(await screen.findByText("实用智能体评测")).toBeVisible();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test.each([
  "https://attacker.invalid/daily.json", "../private.json", `2026-10-21/${hash}.json`,
  `2026-10-22/${"b".repeat(64)}.json`, `2026-10-22/${hash}.json?redirect=1`,
])("daily refuses an index object path outside its date and content hash: %s", async (file) => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-21T17:30:00Z"));
  vi.stubGlobal("fetch", vi.fn(async (url) => new Response(JSON.stringify(String(url).endsWith("index.json")
    ? { schemaVersion: 1, updatedAt: null, days: [{ date: "2026-10-22", count: 1, sha256: hash, file }] }
    : day("2026-10-22")))));
  openDaily();
  expect(await screen.findByRole("alert")).toHaveTextContent("暂时无法读取日报");
  expect(screen.queryAllByRole("article")).toHaveLength(0);
});

test("missing today stays selected and offers the latest archived papers", async () => {
  const user = userEvent.setup();
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-21T17:30:00Z"));
  serve({ "2026-10-21": day("2026-10-21", []), "2026-10-20": day("2026-10-20") });
  openDaily();
  expect(await screen.findByRole("heading", { name: "今天的日报尚未更新" })).toBeVisible();
  expect(screen.getByLabelText("日报日期")).toHaveValue("2026-10-22");
  expect(screen.getByLabelText("该日期暂无日报")).toBeVisible();
  expect(screen.queryAllByRole("article")).toHaveLength(0);
  await user.click(screen.getByRole("button", { name: "查看最近一期" }));
  expect(await screen.findByText("实用智能体评测")).toBeVisible();
  expect(screen.getByLabelText("日报日期")).toHaveValue("2026-10-20");
  await user.selectOptions(screen.getByLabelText("日报日期"), "2026-10-21");
  expect(await screen.findByRole("heading", { name: "当天暂无论文" })).toBeVisible();
  expect(screen.getByLabelText("显示 0 篇论文")).toBeVisible();
  expect(screen.getByLabelText("日报日期")).toHaveValue("2026-10-21");
  await user.selectOptions(screen.getByLabelText("日报日期"), "2026-10-22");
  expect(await screen.findByRole("heading", { name: "今天的日报尚未更新" })).toBeVisible();
  expect(screen.getByLabelText("日报日期")).toHaveValue("2026-10-22");
  expect(screen.queryAllByRole("article")).toHaveLength(0);
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("an archived zero-paper today shows an empty state and weekend note instead of older papers", async () => {
  const user = userEvent.setup();
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-24T05:30:00Z"));
  serve({ "2026-10-24": day("2026-10-24", []), "2026-10-23": day("2026-10-23") });
  openDaily();
  expect(await screen.findByRole("heading", { name: "今天暂无论文" })).toBeVisible();
  expect(screen.getByLabelText("日报日期")).toHaveValue("2026-10-24");
  expect(screen.getByLabelText("显示 0 篇论文")).toBeVisible();
  expect(screen.getByText("按北京时间，arXiv 通常在周六、周日不发布新论文，周一恢复更新。")).toBeVisible();
  expect(screen.queryByText("实用智能体评测")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "查看最近一期" }));
  expect(await screen.findByText("实用智能体评测")).toBeVisible();
  expect(screen.getByLabelText("日报日期")).toHaveValue("2026-10-23");
  expect(screen.queryByText(/周六、周日/)).not.toBeInTheDocument();
});

test("an empty archive has no previous-issue action when no papers have been published", async () => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-22T05:30:00Z"));
  serve({ "2026-10-22": day("2026-10-22", []) });
  openDaily();
  expect(await screen.findByRole("heading", { name: "今天暂无论文" })).toBeVisible();
  expect(screen.getByLabelText("日报日期")).toHaveValue("2026-10-22");
  expect(screen.queryByRole("button", { name: "查看最近一期" })).not.toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("translation fallback displays the original title and abstract with no translation failure notice", async () => {
  const user = userEvent.setup();
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-21T17:30:00Z"));
  serve({ "2026-10-22": day("2026-10-22", [{ ...paper,
    translation: { status: "fallback", title: paper.title, abstract: paper.abstract, brief: "" } }]) });
  openDaily();
  await user.click(await screen.findByRole("button", { name: `展开 ${paper.title} 的论文详情` }));
  expect(screen.getByText(paper.abstract)).toBeVisible();
  expect(screen.queryByText("中文摘要")).not.toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.queryByText(/翻译失败|额度|fallback/i)).not.toBeInTheDocument();
});

test("the research home provides exactly the daily and benchmark entry points", () => {
  render(<App />);
  const entries = screen.getByRole("navigation", { name: "研究专题" });
  expect(within(entries).getAllByRole("link")).toHaveLength(2);
  expect(within(entries).getByRole("link", { name: /每日 arXiv/ })).toHaveAttribute("href", "/arxiv-daily");
  expect(within(entries).getByRole("link", { name: /企业 Agent Benchmark/ })).toHaveAttribute("href", "/enterprise-agent-benchmark");
});

test("benchmark route lists the complete catalog, nine categories and mutually exclusive details", async () => {
  const user = userEvent.setup();
  window.history.replaceState(null, "", "/enterprise-agent-benchmark");
  render(<App />);
  await screen.findByRole("heading", { name: "企业 Agent Benchmark", level: 1 });
  expect(screen.getAllByRole("article")).toHaveLength(benchmarkPapers.length);
  const filters = screen.getByRole("group", { name: "按标签筛选" });
  expect(within(filters).getAllByRole("button")).toHaveLength(10);
  await user.click(screen.getByRole("button", { name: "展开 WorkArena++ 的论文详情" }));
  expect(screen.getByRole("region", { name: "WorkArena++" })).toBeVisible();
  await user.click(screen.getByRole("button", { name: "展开 τ-bench 的论文详情" }));
  expect(screen.queryByRole("region", { name: "WorkArena++" })).not.toBeInTheDocument();
  const details = screen.getByRole("region", { name: "τ-bench" });
  expect(within(details).getByRole("link", { name: "在新窗口预览 τ-bench 中文正文 PDF" })).toHaveAttribute("href",
    "https://updates.cyunlab.com/research/enterprise-agent/tau-bench-2024/8694cc49b7193b363c03428ca79d4baf5b98a9ede1a3e8cb2b083dbb7fbbcc2b/zh.pdf");
  expect(screen.getAllByRole("button", { name: /^收起 / })).toHaveLength(1);
  await user.click(within(filters).getByRole("button", { name: "办公协作" }));
  expect(screen.queryByRole("article", { name: "τ-bench" })).not.toBeInTheDocument();
  expect(within(filters).getByRole("button", { name: "办公协作" })).toHaveAttribute("aria-pressed", "true");
});

test("benchmark source-only papers and reports keep their original publication boundaries", async () => {
  const user = userEvent.setup();
  window.history.replaceState(null, "", "/enterprise-agent-benchmark");
  render(<App />);
  await user.click(await screen.findByRole("button", { name: "展开 EntWorld 的论文详情" }));
  const entworld = screen.getByRole("region", { name: "EntWorld" });
  expect(within(entworld).getByRole("link", { name: "在新窗口预览 EntWorld 英文原文 PDF" })).toHaveAttribute("href", "https://arxiv.org/pdf/2601.17722v1");
  expect(within(entworld).queryByRole("link", { name: /中文正文 PDF/ })).not.toBeInTheDocument();
  expect(within(entworld).queryByRole("link", { name: "中文 Markdown" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "展开 ATLAS-Finance 的报告详情" }));
  const report = screen.getByRole("region", { name: "ATLAS-Finance" });
  expect(within(report).getByRole("link", { name: "官方报告" })).toBeVisible();
  expect(within(report).queryByRole("link", { name: /PDF/ })).not.toBeInTheDocument();
});

test.each([
  { ...day("2026-10-22"), schemaVersion: 2 },
  day("2026-10-21"),
  { ...day("2026-10-22"), stats: { fetched: 1, matched: 0, translated: 0, fallback: 0 } },
  day("2026-10-22", [{ ...paper, pdfUrl: "javascript:alert(1)" }]),
])("malformed daily JSON is a retriable error instead of a partial publication", async (invalid) => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-21T17:30:00Z"));
  serve({ "2026-10-22": invalid });
  openDaily();
  expect(await screen.findByRole("alert")).toHaveTextContent("暂时无法读取日报");
  expect(screen.queryAllByRole("article")).toHaveLength(0);
});
