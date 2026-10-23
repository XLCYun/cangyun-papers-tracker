import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import App from "../src/App.jsx";

const hash = "a".repeat(64);
const root = "https://updates.cyunlab.com/research/arxiv-daily/";
const paper = {
  id: "2610.00001v1", title: "LLM agents that write code", abstract: "Generate and test software with language models.",
  authors: ["Example Author"], affiliations: [], categories: ["cs.SE", "cs.AI"], primaryCategory: "cs.SE",
  publishedAt: "2026-10-22T00:00:00-04:00", updatedAt: null, announceType: "new",
  absUrl: "https://arxiv.org/abs/2610.00001v1", pdfUrl: "https://arxiv.org/pdf/2610.00001v1", htmlUrl: null,
  translation: { status: "translated", title: "编程助手", abstract: "生成代码并完成测试。", brief: "研究编程助手。" },
  tags: ["LLM", "Agent", "CodingAgent", "软件工程"],
  tagging: { status: "tagged", model: "jev-1.13.0", rulesVersion: "daily-tags-v1", threshold: 0.7,
    inputSha256: hash, scores: { AI4S: 0.01, CodingAgent: 0.97, AgentOps: 0.1, AgentHarness: 0.2, 企业Agent: 0.1 } },
};
const science = {
  ...paper, id: "2610.00002v1", title: "LLMs for materials discovery", abstract: "Scientific discovery for new materials.",
  categories: ["cs.LG"], primaryCategory: "cs.LG",
  translation: { status: "translated", title: "材料科学发现", abstract: "利用模型探索新材料。", brief: "发现新的材料。" },
  tags: ["LLM", "AI4S"], tagging: { ...paper.tagging,
    scores: { AI4S: 0.91, CodingAgent: 0.02, AgentOps: 0.1, AgentHarness: 0.2, 企业Agent: 0.1 } },
};
const business = {
  ...paper, id: "2610.00003v1", title: "Agents for invoice workflows", abstract: "Agent tracing, diagnosis and execution controls for business invoices.",
  categories: ["cs.AI"], primaryCategory: "cs.AI",
  translation: { status: "translated", title: "发票工作流", abstract: "企业发票处理中的追踪和执行控制。", brief: "处理企业发票。" },
  tags: ["Agent", "AgentOps", "AgentHarness", "企业Agent"], tagging: { ...paper.tagging,
    scores: { AI4S: 0.01, CodingAgent: 0.02, AgentOps: 0.94, AgentHarness: 0.8, 企业Agent: 0.99 } },
};

function day(date, papers) {
  const translated = papers.filter((item) => item.translation.status === "translated").length;
  return { schemaVersion: 1, date, timezone: "Asia/Shanghai", fetchedAt: `${date}T13:30:00+08:00`,
    source: { url: "https://rss.arxiv.org/rss/cs", updatedAt: `${date}T00:00:00-04:00` },
    stats: { fetched: papers.length, matched: papers.length, translated, fallback: papers.length - translated }, papers };
}

function openDaily(days = { "2026-10-22": day("2026-10-22", [paper, science, business]) }) {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-22T05:30:00Z"));
  const entries = Object.entries(days).sort(([a], [b]) => b.localeCompare(a));
  vi.stubGlobal("fetch", vi.fn(async (url) => {
    if (String(url) === `${root}index.json`) return new Response(JSON.stringify({ schemaVersion: 1, updatedAt: null,
      days: entries.map(([date, value]) => ({ date, count: value.papers.length, sha256: hash, file: `${date}/${hash}.json` })) }));
    const selected = entries.find(([date]) => String(url) === `${root}${date}/${hash}.json`);
    return selected ? new Response(JSON.stringify(selected[1])) : new Response("Missing", { status: 404 });
  }));
  window.history.replaceState(null, "", "/arxiv-daily");
  return render(<App />);
}

test("daily topic controls show daily counts and switch one selected tag at a time", async () => {
  const user = userEvent.setup();
  openDaily();
  await screen.findByText("编程助手");
  const filters = screen.getByRole("group", { name: "按主题标签筛选" });
  expect(within(filters).getAllByRole("button")).toHaveLength(10);
  expect(within(filters).getByRole("button", { name: "全部 3 篇" })).toHaveAttribute("aria-pressed", "true");
  expect(within(filters).getByRole("button", { name: "LLM 2 篇" })).toBeVisible();
  expect(within(filters).getByRole("button", { name: "Agent 2 篇" })).toBeVisible();
  for (const tag of ["AI4S", "CodingAgent", "AgentOps", "AgentHarness", "软件工程", "企业Agent"]) {
    expect(within(filters).getByRole("button", { name: `${tag} 1 篇` })).toBeVisible();
  }
  expect(within(filters).getByRole("button", { name: "GUI/Web Agent 0 篇" })).toBeVisible();
  await user.click(within(filters).getByRole("button", { name: "CodingAgent 1 篇" }));
  expect(screen.getAllByRole("article")).toHaveLength(1);
  expect(screen.getByRole("article", { name: "编程助手" })).toBeVisible();
  expect(screen.getByLabelText("显示 1 篇论文")).toBeVisible();
  await user.click(within(filters).getByRole("button", { name: "AI4S 1 篇" }));
  expect(screen.getByRole("article", { name: "材料科学发现" })).toBeVisible();
  expect(screen.queryByRole("article", { name: "编程助手" })).not.toBeInTheDocument();
  expect(within(filters).getByRole("button", { name: "CodingAgent 1 篇" })).toHaveAttribute("aria-pressed", "false");
  await user.click(within(filters).getByRole("button", { name: "全部 3 篇" }));
  expect(screen.getAllByRole("article")).toHaveLength(3);
  const coding = screen.getByRole("article", { name: "编程助手" });
  const labels = within(coding).getByLabelText("主题标签");
  expect(labels).toHaveTextContent("LLM");
  expect(labels).toHaveTextContent("CodingAgent");
  expect(labels).toHaveTextContent("软件工程");
  expect(within(coding).getByLabelText("arXiv 分类")).toHaveTextContent("cs.SE");
});

test("legacy daily papers derive only English rule tags while failed model tagging still publishes its rule tags", async () => {
  const user = userEvent.setup();
  const { tags, tagging, ...legacy } = paper;
  const fallback = { ...business, tags: ["Agent"], tagging: { ...business.tagging, status: "fallback", scores: {} },
    translation: { status: "fallback", title: business.title, abstract: business.abstract, brief: "" } };
  openDaily({ "2026-10-22": day("2026-10-22", [
    { ...legacy, title: "Agentic LLMs that write code", translation: { ...legacy.translation, brief: "AI4S 与企业Agent的中文简介不决定标签。" } },
    fallback,
  ]) });
  await screen.findByText("编程助手");
  const filters = screen.getByRole("group", { name: "按主题标签筛选" });
  expect(within(filters).getByRole("button", { name: "Agent 2 篇" })).toBeVisible();
  expect(within(filters).getByRole("button", { name: "LLM 1 篇" })).toBeVisible();
  expect(within(filters).getByRole("button", { name: "软件工程 1 篇" })).toBeVisible();
  expect(within(filters).getByRole("button", { name: "AI4S 0 篇" })).toBeVisible();
  expect(within(filters).getByRole("button", { name: "CodingAgent 0 篇" })).toBeVisible();
  expect(within(filters).getByRole("button", { name: "企业Agent 0 篇" })).toBeVisible();
  const labels = within(screen.getByRole("article", { name: "编程助手" })).getByLabelText("主题标签");
  expect(labels).toHaveTextContent("LLMAgent软件工程");
  await user.click(within(filters).getByRole("button", { name: "Agent 2 篇" }));
  expect(screen.getAllByRole("article")).toHaveLength(2);
  expect(screen.getByRole("article", { name: business.title })).toBeVisible();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.queryByText(/打标失败|分类失败|fallback/i)).not.toBeInTheDocument();
});

test("legacy rule tags preserve the collector's Unicode word boundaries and prefix matches", async () => {
  const { tags, tagging, ...legacy } = paper;
  openDaily({ "2026-10-22": day("2026-10-22", [{ ...legacy,
    title: "αLLM αAgent and LLMfoo", abstract: "Superagent studies.", categories: ["cs.LG"],
  }]) });
  await screen.findByText("编程助手");
  const filters = screen.getByRole("group", { name: "按主题标签筛选" });
  expect(within(filters).getByRole("button", { name: "LLM 1 篇" })).toBeVisible();
  expect(within(filters).getByRole("button", { name: "Agent 0 篇" })).toBeVisible();
  expect(within(filters).getByRole("button", { name: "软件工程 0 篇" })).toBeVisible();
});

test("published rule labels stay authoritative across browser Unicode versions", async () => {
  // U+088F was unassigned in the collector's Unicode version, but is a letter
  // in newer browser runtimes. These are valid collector-generated rule tags.
  openDaily({ "2026-10-22": day("2026-10-22", [{ ...paper,
    title: "\u088fLLM \u088fAgent", abstract: "English input.",
  }]) });
  await screen.findByRole("article", { name: "编程助手" });
  const filters = screen.getByRole("group", { name: "按主题标签筛选" });
  expect(within(filters).getByRole("button", { name: "LLM 1 篇" })).toBeVisible();
  expect(within(filters).getByRole("button", { name: "Agent 1 篇" })).toBeVisible();
  expect(within(filters).getByRole("button", { name: "CodingAgent 1 篇" })).toBeVisible();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("tag metadata accepts non-whitespace text according to the publisher contract", async () => {
  // Python strip does not discard U+FEFF, so this remains a nonempty string.
  openDaily({ "2026-10-22": day("2026-10-22", [{ ...paper,
    tagging: { ...paper.tagging, model: "\ufeff", rulesVersion: "\ufeff", scores: { ...paper.tagging.scores, "GUI Agent": 0 } },
  }]) });
  expect(await screen.findByRole("article", { name: "编程助手" })).toBeVisible();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test.each([0.7, 0.69])("GUI/Web Agent filters, labels and search reuse archived GUI Agent scores: %s", async (score) => {
  const user = userEvent.setup();
  const gui = { ...paper, id: "2610.00004v1", title: "GUI Agent for desktop tasks",
    translation: { ...paper.translation, title: "桌面操作智能体" },
    tags: score >= 0.7 ? ["LLM", "Agent", "CodingAgent", "GUI Agent", "软件工程"] : paper.tags,
    tagging: { ...paper.tagging, rulesVersion: "daily-tags-v2", scores: { ...paper.tagging.scores, "GUI Agent": score } } };
  openDaily({ "2026-10-22": day("2026-10-22", [paper, gui]) });
  expect(await screen.findByRole("article", { name: "编程助手" })).toBeVisible();
  const card = screen.getByRole("article", { name: "桌面操作智能体" });
  const labels = within(card).getByLabelText("主题标签");
  expect(labels.textContent.includes("GUI/Web Agent")).toBe(score >= 0.7);
  const filter = screen.getByRole("button", { name: `GUI/Web Agent ${score >= 0.7 ? 1 : 0} 篇` });
  await user.click(filter);
  expect(filter).toHaveAttribute("aria-pressed", "true");
  expect(screen.queryAllByRole("article")).toHaveLength(score >= 0.7 ? 1 : 0);
  await user.type(screen.getByRole("searchbox", { name: "搜索日报论文" }), "GUI/Web Agent");
  expect(screen.queryAllByRole("article")).toHaveLength(score >= 0.7 ? 1 : 0);
});

test("topic selection intersects search, keeps full-day counts, and persists with the query across dates", async () => {
  const user = userEvent.setup();
  openDaily({ "2026-10-22": day("2026-10-22", [paper, science, business]), "2026-10-21": day("2026-10-21", [paper, business]) });
  await screen.findByText("编程助手");
  const filters = screen.getByRole("group", { name: "按主题标签筛选" });
  const search = screen.getByRole("searchbox", { name: "搜索日报论文" });
  await user.click(within(filters).getByRole("button", { name: "LLM 2 篇" }));
  await user.type(search, "材料");
  expect(screen.getAllByRole("article")).toHaveLength(1);
  expect(screen.getByRole("article", { name: "材料科学发现" })).toBeVisible();
  expect(within(filters).getByRole("button", { name: "全部 3 篇" })).toBeVisible();
  expect(within(filters).getByRole("button", { name: "LLM 2 篇" })).toHaveAttribute("aria-pressed", "true");
  expect(within(filters).getByRole("button", { name: "Agent 2 篇" })).toBeVisible();
  await user.selectOptions(screen.getByLabelText("日报日期"), "2026-10-21");
  expect(await within(filters).findByRole("button", { name: "全部 2 篇" })).toBeVisible();
  expect(search).toHaveValue("材料");
  expect(within(filters).getByRole("button", { name: "LLM 1 篇" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByLabelText("显示 0 篇论文")).toBeVisible();
  expect(screen.queryAllByRole("article")).toHaveLength(0);
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  await user.clear(search);
  expect(screen.getByRole("article", { name: "编程助手" })).toBeVisible();
  expect(screen.getAllByRole("article")).toHaveLength(1);
  await user.type(search, "企业Agent");
  expect(screen.getByLabelText("显示 0 篇论文")).toBeVisible();
  await user.click(within(filters).getByRole("button", { name: "全部 2 篇" }));
  expect(screen.getByRole("article", { name: "发票工作流" })).toBeVisible();
});

test("daily topic filters retain mutually exclusive paper details", async () => {
  const user = userEvent.setup();
  openDaily();
  await user.click(await screen.findByRole("button", { name: "展开 编程助手 的论文详情" }));
  expect(screen.getByRole("region", { name: "编程助手" })).toBeVisible();
  await user.click(screen.getByRole("button", { name: "展开 发票工作流 的论文详情" }));
  expect(screen.queryByRole("region", { name: "编程助手" })).not.toBeInTheDocument();
  expect(screen.getByRole("region", { name: "发票工作流" })).toBeVisible();
  expect(screen.getAllByRole("button", { name: /^收起 / })).toHaveLength(1);
  const filters = screen.getByRole("group", { name: "按主题标签筛选" });
  await user.click(within(filters).getByRole("button", { name: "企业Agent 1 篇" }));
  expect(screen.getByRole("region", { name: "发票工作流" })).toBeVisible();
  await user.click(screen.getByRole("button", { name: "收起 发票工作流 的论文详情" }));
  expect(screen.queryByRole("region", { name: "发票工作流" })).not.toBeInTheDocument();
});

test.each([
  ["missing tag array", { ...paper, tags: undefined }],
  ["missing tagging state", { ...paper, tagging: undefined }],
  ["null tagging state", { ...paper, tagging: null }],
  ["unknown topic", { ...paper, tags: ["LLM", "Agent", "Unknown"] }],
  ["duplicate topic", { ...paper, tags: ["LLM", "Agent", "LLM", "CodingAgent", "软件工程"] }],
  ["wrong topic order", { ...paper, tags: ["Agent", "LLM", "CodingAgent", "软件工程"] }],
  ["unknown tagging status", { ...paper, tagging: { ...paper.tagging, status: "complete" } }],
  ["extra tagging field", { ...paper, tagging: { ...paper.tagging, extra: true } }],
  ["empty model", { ...paper, tagging: { ...paper.tagging, model: "" } }],
  ["record separator model", { ...paper, tagging: { ...paper.tagging, model: "\u001c\u001d\u001e\u001f" } }],
  ["empty rule version", { ...paper, tagging: { ...paper.tagging, rulesVersion: "" } }],
  ["Unicode whitespace rule version", { ...paper, tagging: { ...paper.tagging, rulesVersion: "\u0085\u00a0\u3000" } }],
  ["threshold out of range", { ...paper, tagging: { ...paper.tagging, threshold: 1.1 } }],
  ["invalid input hash", { ...paper, tagging: { ...paper.tagging, inputSha256: "invalid" } }],
  ["missing scores", { ...paper, tagging: { ...paper.tagging, scores: { CodingAgent: 0.97 } } }],
  ["v2 missing GUI score", { ...paper, tagging: { ...paper.tagging, rulesVersion: "daily-tags-v2" } }],
  ["extra score", { ...paper, tagging: { ...paper.tagging, scores: { ...paper.tagging.scores, LLM: 1 } } }],
  ["score out of range", { ...paper, tagging: { ...paper.tagging, scores: { ...paper.tagging.scores, AI4S: 2 } } }],
  ["score as text", { ...paper, tagging: { ...paper.tagging, scores: { ...paper.tagging.scores, AI4S: "0.1" } } }],
  ["failed state with scores", { ...paper, tagging: { ...paper.tagging, status: "fallback" } }],
  ["missing model tag", { ...paper, tags: ["LLM", "Agent", "软件工程"] }],
  ["unearned model tag", { ...paper, tags: ["LLM", "Agent", "AI4S", "CodingAgent", "软件工程"] }],
])("malformed topic data is a retriable read error instead of a partial daily: %s", async (_name, invalid) => {
  openDaily({ "2026-10-22": day("2026-10-22", [invalid, science]) });
  expect(await screen.findByRole("alert")).toHaveTextContent("暂时无法读取日报");
  expect(screen.queryAllByRole("article")).toHaveLength(0);
});
