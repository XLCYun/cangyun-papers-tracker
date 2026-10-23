import { useEffect, useState } from "react";
import { ArrowUpRight, CaretDown, Circle, FileText, MagnifyingGlass, Minus, Plus, SortDescending } from "@phosphor-icons/react";
import "@fontsource-variable/noto-serif-sc";
import papers from "./data/enterprise-papers.json";
import { PAPER_TAGS, groupPapersByMonth, groupPapersByYear, selectPapers } from "./enterprisePapers.js";
import "./enterprise-research.css";

const external = { target: "_blank", rel: "noopener noreferrer" };
const collectionUnit = papers.some((paper) => paper.documentType === "report") ? "项研究" : "篇论文";

function linkedPaper() {
  try {
    const id = decodeURIComponent(window.location.hash.slice(1));
    return papers.some((paper) => paper.id === id) ? id : null;
  } catch {
    return null;
  }
}

function PaperEntry({ paper, expanded, onToggle }) {
  const sourceOnly = paper.publicationStatus === "source-only";
  const isReport = paper.documentType === "report";
  const documentLabel = isReport ? "报告" : "论文";
  const originalPdf = sourceOnly ? paper.sourcePdfUrl : paper.assets.enPdf;
  return (
    <article className="research-paper" id={paper.id} data-expanded={expanded} aria-labelledby={`${paper.id}-title`}>
      {expanded && <Circle className="research-active-marker" size={12} weight="bold" aria-hidden="true" />}
      <h3 className="research-entry-heading" aria-label={paper.name}>
        <button className="research-entry-toggle" type="button" onClick={onToggle} aria-expanded={expanded} aria-controls={`${paper.id}-details`} aria-label={`${expanded ? "收起" : "展开"} ${paper.name} 的${documentLabel}详情`}>
          <span className="research-entry-copy">
            <span className="research-entry-topline">
              <span className="research-paper-name" id={`${paper.id}-title`}>{paper.name}</span>
              {paper.institutions.length > 0 && <span className="research-institution">{paper.institutions[0]}</span>}
            </span>
            <span className="research-paper-subtitle">{paper.titleZh}</span>
            <span className="research-tags" aria-label={`${documentLabel}标签`}>
              {paper.tags.map((tag) => <span key={tag}>{tag}</span>)}
            </span>
          </span>
          <span className="research-disclosure" aria-hidden="true">{expanded ? <Minus size={19} /> : <Plus size={19} />}</span>
        </button>
      </h3>
      <div className="research-paper-body" id={`${paper.id}-details`} hidden={!expanded} role="region" aria-labelledby={`${paper.id}-title`}>
        <div className="research-paper-reading">
          <p className="research-paper-date">首次公开 <time dateTime={paper.publishedAt}>{paper.publishedAt.replaceAll("-", ".")}</time></p>
          <div className="research-summary-section">
            <h4 className="research-section-title">一句话总结</h4>
            <p className="research-summary">{paper.summary}</p>
          </div>
          <div className="research-abstract-section">
            <h4 className="research-section-title">摘要介绍</h4>
            <div className="research-section-copy">
              <p className="research-abstract">{paper.abstract}</p>
              <p className="research-abstract-note">{isReport ? "依据官方报告整理。" : "依据所收录版本整理，非原文摘要的逐句翻译。"}</p>
            </div>
          </div>
        </div>
        <details className="research-details">
          <summary>版本、作者与引用<CaretDown size={16} aria-hidden="true" /></summary>
          <div className="research-details-content">
            <dl>
              {isReport && <div><dt>文献类型</dt><dd>官方报告</dd></div>}
              <div><dt>收录版本</dt><dd>{paper.version}</dd></div>
              <div><dt>原文标题</dt><dd lang="en">{paper.title}</dd></div>
              {paper.institutions.length > 0 && <div><dt>研究机构</dt><dd lang="en">{paper.institutions.join(" / ")}</dd></div>}
              <div><dt>作者</dt><dd lang="en">{paper.authors.join(", ")}</dd></div>
              {sourceOnly
                ? <div><dt>中文译文</dt><dd>{paper.publicationNote}</dd></div>
                : <div><dt>中文范围</dt><dd>{paper.translationScope}。自动翻译并重新排版。</dd></div>}
              <div><dt>引用</dt><dd lang="en">{paper.citation}</dd></div>
              <div><dt>许可</dt><dd><a href={paper.licenseUrl} {...external}>{paper.license}<ArrowUpRight size={12} aria-hidden="true" /></a></dd></div>
            </dl>
            <div className="research-related">
              {paper.codeUrl && <a href={paper.codeUrl} {...external}>代码仓库<ArrowUpRight size={14} aria-hidden="true" /></a>}
              {!sourceOnly && <a href={paper.assets.zhMarkdown} {...external}>中文 Markdown<ArrowUpRight size={14} aria-hidden="true" /></a>}
              {!sourceOnly && <a href={paper.assets.enMarkdown} {...external}>英文 Markdown<ArrowUpRight size={14} aria-hidden="true" /></a>}
              <a href={`#${paper.id}`}>{documentLabel}固定链接<ArrowUpRight size={14} aria-hidden="true" /></a>
            </div>
          </div>
        </details>
        <div className="research-paper-actions">
          {!sourceOnly && <a className="research-pdf research-pdf-primary" href={paper.assets.zhPdf} {...external} aria-label={`在新窗口预览 ${paper.name} 中文正文 PDF`}><FileText size={20} aria-hidden="true" />中文正文<ArrowUpRight size={16} aria-hidden="true" /></a>}
          {originalPdf && <a className="research-pdf" href={originalPdf} {...external} aria-label={`在新窗口预览 ${paper.name} 英文原文 PDF`}><FileText size={20} aria-hidden="true" />英文原文<ArrowUpRight size={16} aria-hidden="true" /></a>}
          {sourceOnly && <span className="research-availability">{originalPdf ? "中文译文暂未公开" : isReport ? "官方网页报告" : "暂无可用的公开 PDF"}</span>}
          <a className={originalPdf ? "research-source" : "research-pdf"} href={paper.sourceUrl} {...external}>{isReport ? "官方报告" : "论文来源"}<ArrowUpRight size={14} aria-hidden="true" /></a>
        </div>
      </div>
    </article>
  );
}

export default function EnterpriseResearch({ footer }) {
  const [query, setQuery] = useState("");
  const [tag, setTag] = useState("");
  const [expandedId, setExpandedId] = useState(linkedPaper);
  const visiblePapers = selectPapers(papers, { query, tag });
  const years = groupPapersByYear(visiblePapers);

  useEffect(() => {
    document.title = "企业 Agent Benchmark · Research";
    document.documentElement.lang = "zh-CN";
    const meta = document.querySelector('meta[name="theme-color"]');
    const previous = meta?.getAttribute("content");
    meta?.setAttribute("content", "#10100f");
    let frame;
    const revealLinkedPaper = () => {
      const id = linkedPaper();
      if (!id) return;
      setQuery("");
      setTag("");
      setExpandedId(id);
      // The lazy route and filtered entries must render before fragment scrolling.
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => document.getElementById(id)?.scrollIntoView({ block: "start" }));
    };
    revealLinkedPaper();
    window.addEventListener("hashchange", revealLinkedPaper);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("hashchange", revealLinkedPaper);
      if (previous) meta?.setAttribute("content", previous);
    };
  }, []);

  function togglePaper(id) {
    setExpandedId((current) => current === id ? null : id);
  }

  return (
    <div className="research-page">
      <a className="research-skip" href="#research-timeline">跳到论文时间线</a>
      <main className="research-container research-main">
        <section className="research-intro" aria-labelledby="research-title">
          <h1 id="research-title">企业 Agent <span>Benchmark</span></h1>
          <p className="research-collection" aria-label={`已收录 ${papers.length} ${collectionUnit}`}><strong>{String(papers.length).padStart(2, "0")}</strong><span>{collectionUnit}</span></p>
        </section>
        <div className="research-toolbar">
          <label className="research-search"><MagnifyingGlass size={20} aria-hidden="true" /><span className="research-sr-only">搜索论文、作者或标签</span><input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索论文、作者或标签" /></label>
          <div className="research-tag-filter" role="group" aria-label="按标签筛选">
            <button type="button" aria-pressed={tag === ""} onClick={() => setTag("")}>全部标签</button>
            {PAPER_TAGS.map((value) => <button key={value} type="button" aria-pressed={tag === value} onClick={() => setTag(value)}>{value}</button>)}
          </div>
          <p className="research-result-count" role="status" aria-live="polite"><span className={query || tag ? "" : "research-sr-only"}>{visiblePapers.length} {collectionUnit}</span><SortDescending size={17} aria-hidden="true" />最新在前</p>
        </div>
        <div className="research-timeline" id="research-timeline" tabIndex={-1}>
          {years.map(({ year, papers: items }) => <section className="research-year" key={year} aria-label={`${year} 年论文`}>
            <h2 className="research-year-label">{year}</h2>
            {groupPapersByMonth(items).map(({ month, papers: monthPapers }) => <section className="research-month" key={month} aria-label={`${year} 年 ${Number(month.slice(5))} 月论文`}>
              <div className="research-month-marker"><Circle size={15} weight="bold" aria-hidden="true" /><time dateTime={month}>{month.slice(5)} <span>月</span></time></div>
              <div className="research-month-papers">{monthPapers.map((paper) => <PaperEntry key={paper.id} paper={paper} expanded={expandedId === paper.id} onToggle={() => togglePaper(paper.id)} />)}</div>
            </section>)}
          </section>)}
          {!visiblePapers.length && <div className="research-empty"><MagnifyingGlass size={28} aria-hidden="true" /><h2>没有找到相关论文</h2><p>试试其他关键词，或查看全部标签。</p><button type="button" onClick={() => { setQuery(""); setTag(""); }}>清除筛选</button></div>}
        </div>
      </main>
      <footer className="research-footer research-container">{footer}</footer>
    </div>
  );
}
