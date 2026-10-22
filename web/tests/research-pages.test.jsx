import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import App from "../src/App.jsx";

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
});

test("a failed JSON request offers retry and never appears as a successful zero-paper day", async () => {
  const user = userEvent.setup();
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-21T17:30:00Z"));
  vi.stubGlobal("fetch", vi.fn(async () => new Response("Unavailable", { status: 503 })));
  openDaily();
  expect(await screen.findByRole("alert")).toHaveTextContent("暂时无法读取日报");
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

test("date selection shows archived days while missing today and a valid zero day stay empty without notices", async () => {
  const user = userEvent.setup();
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-21T17:30:00Z"));
  serve({ "2026-10-21": day("2026-10-21"), "2026-10-20": day("2026-10-20", []) });
  openDaily();
  await screen.findByRole("option", { name: "2026-10-21" });
  await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
  expect(screen.getByLabelText("日报日期")).toHaveValue("2026-10-22");
  expect(screen.getByLabelText("显示 0 篇论文")).toBeVisible();
  expect(screen.queryAllByRole("article")).toHaveLength(0);
  await user.selectOptions(screen.getByLabelText("日报日期"), "2026-10-21");
  expect(await screen.findByText("实用智能体评测")).toBeVisible();
  await user.selectOptions(screen.getByLabelText("日报日期"), "2026-10-20");
  await waitFor(() => expect(screen.getByLabelText("显示 0 篇论文")).toBeVisible());
  expect(screen.queryAllByRole("article")).toHaveLength(0);
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.queryByText(/暂无|未发布|没有论文|最近一期|更新中/)).not.toBeInTheDocument();
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

test("benchmark route preserves 101 studies, nine categories and mutually exclusive details", async () => {
  const user = userEvent.setup();
  window.history.replaceState(null, "", "/enterprise-agent-benchmark");
  render(<App />);
  await screen.findByRole("heading", { name: "企业 Agent Benchmark", level: 1 });
  expect(screen.getAllByRole("article")).toHaveLength(101);
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
