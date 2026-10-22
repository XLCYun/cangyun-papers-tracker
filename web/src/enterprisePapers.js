export const PAPER_TAGS = Object.freeze([
  "办公协作", "客服销售", "财务金融", "供应链", "经营模拟",
  "数据分析", "法律合规", "医疗健康", "通用评测",
]);

export function selectPapers(papers, { query = "", tag = "" } = {}) {
  const terms = query.trim().toLocaleLowerCase().replaceAll("tau", "τ").split(/\s+/).filter(Boolean);
  return papers.filter((paper) => {
    const text = [paper.name, paper.title, paper.titleZh, paper.summary, paper.abstract,
      ...paper.tags, ...paper.authors, ...paper.institutions].join(" ").toLocaleLowerCase();
    return (!tag || paper.tags.includes(tag)) && terms.every((term) => text.includes(term));
  }).sort((a, b) => b.publishedAt.localeCompare(a.publishedAt) || a.id.localeCompare(b.id));
}

export function groupPapersByYear(papers) {
  return [...new Set(papers.map((paper) => paper.publishedAt.slice(0, 4)))].sort().reverse()
    .map((year) => ({ year, papers: papers.filter((paper) => paper.publishedAt.startsWith(year)) }));
}

export function groupPapersByMonth(papers) {
  return [...new Set(papers.map((paper) => paper.publishedAt.slice(0, 7)))].sort().reverse()
    .map((month) => ({ month, papers: selectPapers(papers.filter((paper) => paper.publishedAt.startsWith(`${month}-`))) }));
}

export function validatePapers(papers) {
  const ids = new Set();
  for (const paper of papers) {
    if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(paper.id) || ids.has(paper.id)) throw new Error(`Invalid or duplicate paper id: ${paper.id}`);
    ids.add(paper.id);
    if (paper.documentType != null && !["paper", "report"].includes(paper.documentType)) throw new Error(`Invalid document type: ${paper.id}`);
    const date = new Date(paper.publishedAt);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(paper.publishedAt) || !Number.isFinite(+date) || date.toISOString().slice(0, 10) !== paper.publishedAt) throw new Error(`Invalid publication date: ${paper.id}`);
    for (const key of ["name", "title", "titleZh", "version", "summary", "abstract", "citation", "license", "translationScope"]) {
      if (typeof paper[key] !== "string" || !paper[key].trim()) throw new Error(`Missing ${key}: ${paper.id}`);
    }
    for (const key of ["tags", "authors", "institutions"]) {
      if (!Array.isArray(paper[key]) || (key !== "institutions" && !paper[key].length) || paper[key].some((value) => typeof value !== "string" || !value.trim())) throw new Error(`Missing ${key}: ${paper.id}`);
    }
    if (paper.tags.length > 3 || new Set(paper.tags).size !== paper.tags.length || paper.tags.some((tag) => !PAPER_TAGS.includes(tag))) {
      throw new Error(`Invalid tags: ${paper.id}; choose up to three distinct business categories`);
    }
    const linkKeys = ["sourceUrl", "licenseUrl"];
    // Source-only entries can explicitly state that no public PDF is available.
    // Published file bundles still require an actual source PDF URL.
    if (paper.sourcePdfUrl !== null || paper.publicationStatus !== "source-only") linkKeys.push("sourcePdfUrl");
    if (paper.codeUrl != null) linkKeys.push("codeUrl");
    for (const key of linkKeys) {
      const url = new URL(paper[key]);
      if (url.protocol !== "https:" || url.username || url.password) throw new Error(`Invalid ${key}: ${paper.id}`);
    }
    if (paper.publicationStatus != null && !["published", "source-only"].includes(paper.publicationStatus)) throw new Error(`Invalid publication status: ${paper.id}`);
    if (paper.publicationStatus === "source-only") {
      if (typeof paper.publicationNote !== "string" || !paper.publicationNote.trim()) throw new Error(`Missing publication note: ${paper.id}`);
      if (!paper.assets || Array.isArray(paper.assets) || typeof paper.assets !== "object" || Object.keys(paper.assets).length) throw new Error(`Source-only paper must not expose archived assets: ${paper.id}`);
      continue;
    }
    for (const [key, filename] of Object.entries({ enPdf: "en.pdf", zhPdf: "zh.pdf", enMarkdown: "en.md", zhMarkdown: "zh.md" })) {
      const url = new URL(paper.assets?.[key]);
      const pattern = new RegExp(`^/research/enterprise-agent/${paper.id}/[a-f0-9]{64}/${filename.replace(".", "\\.")}$`);
      if (url.origin !== "https://updates.cyunlab.com" || url.username || url.password || url.search || url.hash || !pattern.test(url.pathname)) throw new Error(`Invalid or unpublished ${key}: ${paper.id}`);
    }
  }
}
