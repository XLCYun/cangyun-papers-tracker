import assert from "node:assert/strict";
import { test } from "vitest";
import { PAPER_TAGS, groupPapersByMonth, groupPapersByYear, selectPapers, validatePapers } from "../src/enterprisePapers.js";
import publishedPapers from "../src/data/enterprise-papers.json";

// Keep behavior fixtures stable as the public archive gains papers and shared tags.
const papers = ["workarena-plus-plus-2024", "tau-bench-2024", "workarena-2024"]
  .map((id) => publishedPapers.find((paper) => paper.id === id));

test("every paper has complete metadata and published papers have immutable OSS asset links", () => {
  validatePapers(publishedPapers);
  const missing = structuredClone(papers);
  delete missing[0].assets.zhPdf;
  assert.throws(() => validatePapers(missing));
  const unsafe = structuredClone(papers);
  unsafe[0].assets.zhPdf = "https://updates.cyunlab.com/dsh-desktop/channels/stable/latest.json";
  assert.throws(() => validatePapers(unsafe));
});

test("source-only papers require an explanation and cannot expose archived files", () => {
  const sourceOnly = { ...papers[0], publicationStatus: "source-only", publicationNote: "原文许可未授权公开译文。", assets: {} };
  assert.doesNotThrow(() => validatePapers([sourceOnly]));
  assert.throws(() => validatePapers([{ ...sourceOnly, publicationNote: "" }]));
  assert.throws(() => validatePapers([{ ...sourceOnly, assets: papers[0].assets }]));
  assert.throws(() => validatePapers([{ ...sourceOnly, sourcePdfUrl: "javascript:alert(1)" }]));
  assert.throws(() => validatePapers([{ ...sourceOnly, publicationStatus: "pending" }]));
  assert.throws(() => validatePapers([{ ...sourceOnly, publicationStatus: "published" }]));
});

test("paper tags use the fixed business categories without duplicates or excessive labels", () => {
  assert.equal(PAPER_TAGS.length, 9);
  for (const tags of [["MCP"], ["运维安全"], ["办公协作", "办公协作"], [], PAPER_TAGS.slice(0, 4)]) {
    assert.throws(() => validatePapers([{ ...papers[0], tags }]));
  }
  const crossDomain = { ...papers[0], tags: ["客服销售", "财务金融"] };
  assert.doesNotThrow(() => validatePapers([crossDomain]));
  assert.equal(selectPapers([crossDomain], { tag: "财务金融" }).length, 1);
});

test("source-only entries can explicitly lack a public PDF without weakening asset validation", () => {
  const report = { ...papers[0], documentType: "report", publicationStatus: "source-only",
    publicationNote: "官方网页报告，未发布独立 PDF。", sourcePdfUrl: null, assets: {} };
  assert.doesNotThrow(() => validatePapers([report]));
  assert.doesNotThrow(() => validatePapers([{ ...report, documentType: "paper" }]));
  assert.throws(() => validatePapers([{ ...report, sourcePdfUrl: undefined }]));
  assert.throws(() => validatePapers([{ ...report, documentType: "unknown" }]));
  assert.throws(() => validatePapers([{ ...report, sourcePdfUrl: "javascript:alert(1)" }]));
  assert.throws(() => validatePapers([{ ...report, sourceUrl: null }]));
  assert.throws(() => validatePapers([{ ...report, publicationStatus: "published", assets: papers[0].assets }]));
});

test("a paper may omit undisclosed affiliations and code without weakening required fields", () => {
  const withoutCode = { ...papers[0], codeUrl: null, institutions: [] };
  assert.doesNotThrow(() => validatePapers([withoutCode]));
  assert.throws(() => validatePapers([{ ...withoutCode, codeUrl: "javascript:alert(1)" }]));
  assert.throws(() => validatePapers([{ ...withoutCode, sourceUrl: null }]));
  assert.throws(() => validatePapers([{ ...withoutCode, authors: [] }]));
  assert.throws(() => validatePapers([{ ...withoutCode, institutions: [""] }]));
});

test("timeline uses first publication date and remains newest first across years", () => {
  const input = [papers[2], { ...papers[0], id: "future", publishedAt: "2025-01-02" }, papers[0], papers[1]];
  const sorted = selectPapers(input);
  assert.deepEqual(sorted.map((paper) => paper.id), ["future", "workarena-plus-plus-2024", "tau-bench-2024", "workarena-2024"]);
  assert.deepEqual(groupPapersByYear(sorted).map(({year}) => year), ["2025", "2024"]);
  assert.equal(input[0], papers[2]);
});

test("search supports tau spelling, Chinese tags, authors and combined filters", () => {
  assert.equal(selectPapers(papers, { query: " TAU-BENCH " })[0].id, "tau-bench-2024");
  assert.equal(selectPapers(papers, { query: "Shunyu" }).length, 1);
  assert.equal(selectPapers(papers, { tag: "办公协作" }).length, 2);
  assert.equal(selectPapers(papers, { query: "规划", tag: "办公协作" }).length, 1);
  assert.equal(selectPapers(papers, { query: "WorkArena", tag: "客服销售" }).length, 0);
});

test("month groups keep years distinct and multiple papers newest first within a month", () => {
  const input = [papers[2], papers[1], { ...papers[0], id: "next-year", publishedAt: "2025-03-01" },
    { ...papers[2], id: "later-march", publishedAt: "2024-03-29" }, papers[0]];
  const groups = groupPapersByMonth(input);
  assert.deepEqual(groups.map(({ month }) => month), ["2025-03", "2024-07", "2024-06", "2024-03"]);
  assert.deepEqual(groups[3].papers.map(({ id }) => id), ["later-march", "workarena-2024"]);
  assert.equal(input[0], papers[2]);
  assert.deepEqual(groupPapersByMonth([]), []);
});
