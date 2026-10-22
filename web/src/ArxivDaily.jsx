import { useEffect, useState } from "react";
import { ArrowLeft, ArrowUpRight, MagnifyingGlass, Minus, Plus } from "@phosphor-icons/react";
import { loadDailyDocument, loadDailyIndex } from "./dailyData.js";
import dailyTags from "../../shared/daily-tags.json";

const beijingDate = () => new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
}).format(new Date());

function DailyPaper({ paper, index, expanded, onToggle }) {
  const title = paper.translation.title;
  const titleId = `daily-${paper.id}-title`;
  const detailsId = `daily-${paper.id}-details`;
  return <article className="daily-paper" data-expanded={expanded} aria-labelledby={titleId}>
    <h2><button type="button" className="daily-paper-header" onClick={onToggle} aria-expanded={expanded} aria-controls={detailsId} aria-label={`${expanded ? "收起" : "展开"} ${title} 的论文详情`}>
      <span className="daily-paper-number">{String(index + 1).padStart(2, "0")}</span>
      <span><span className="daily-paper-title" id={titleId}>{title}</span>
        {title !== paper.title && <span className="daily-paper-original" lang="en">{paper.title}</span>}
        {paper.translation.brief && <span className="daily-paper-brief">{paper.translation.brief}</span>}
        <span className="daily-paper-tags" aria-label="主题标签">{paper.tags.map((tag) => <span key={tag}>{tag}</span>)}</span>
        <span className="daily-paper-meta"><span>{paper.authors.join(", ")}</span><span className="daily-paper-categories" aria-label="arXiv 分类">{paper.categories.map((category) => <span key={category}>{category}</span>)}</span></span>
      </span><span className="research-disclosure" aria-hidden="true">{expanded ? <Minus size={19} /> : <Plus size={19} />}</span>
    </button></h2>
    <div className="daily-paper-details" role="region" aria-labelledby={titleId} id={detailsId} hidden={!expanded}>
      {paper.translation.status === "translated" && <section className="daily-abstract"><h3>中文摘要</h3><p>{paper.translation.abstract}</p></section>}
      <section className="daily-abstract"><h3>英文摘要</h3><p lang="en">{paper.abstract}</p></section>
      <p className="daily-detail-meta">arXiv:{paper.id}{paper.affiliations.length > 0 && <> · {paper.affiliations.join(" / ")}</>}</p>
      <div className="daily-actions">
        {[["arXiv", paper.absUrl], ["HTML", paper.htmlUrl], ["PDF", paper.pdfUrl]].filter(([, href]) => href).map(([label, href]) => <a href={href} key={label} target="_blank" rel="noopener noreferrer">{label}<ArrowUpRight size={14} aria-hidden="true" /></a>)}
      </div>
    </div>
  </article>;
}

export default function ArxivDaily({ footer }) {
  const [today] = useState(beijingDate);
  const [date, setDate] = useState(today);
  const [days, setDays] = useState([]);
  const [papers, setPapers] = useState([]);
  const [query, setQuery] = useState("");
  const [selectedTag, setSelectedTag] = useState("全部");
  const [status, setStatus] = useState("loading");
  const [expandedId, setExpandedId] = useState(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000);
    setStatus("loading");
    setPapers([]);
    setExpandedId(null);
    loadDailyIndex(controller.signal).then(async (index) => {
      if (active) setDays(index.days);
      const entry = index.days.find((item) => item.date === date);
      const daily = entry ? await loadDailyDocument(entry, controller.signal) : { papers: [] };
      if (active) {
        setPapers(daily.papers);
        setStatus("ready");
      }
    }).catch(() => { if (active) setStatus("error"); }).finally(() => clearTimeout(timeout));
    return () => { active = false; controller.abort(); clearTimeout(timeout); };
  }, [date, attempt]);

  useEffect(() => { document.title = "每日 arXiv · CY Lab Research"; }, []);
  const dates = [...new Set([today, ...days.map((entry) => entry.date)])].sort().reverse();
  const terms = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  const visiblePapers = papers.filter((paper) => {
    if (selectedTag !== "全部" && !paper.tags.includes(selectedTag)) return false;
    const text = [paper.title, paper.abstract, paper.translation.title, paper.translation.abstract,
      paper.translation.brief, ...paper.authors, ...paper.affiliations, ...paper.categories, ...paper.tags].join(" ").toLocaleLowerCase();
    return terms.every((term) => text.includes(term));
  });
  return <div className="research-page">
    <main className="research-container research-main">
      <a className="daily-back" href="/"><ArrowLeft size={14} aria-hidden="true" />研究首页</a>
      <section className="research-intro daily-intro" aria-labelledby="daily-title">
        <h1 id="daily-title">每日 arXiv</h1>
        <p className="research-collection" aria-label={status === "ready" ? `显示 ${visiblePapers.length} 篇论文` : "正在读取论文数量"}><strong>{status === "ready" ? visiblePapers.length : "—"}</strong><span>篇论文</span></p>
      </section>
      <div className="daily-toolbar">
        <label className="daily-date">日报日期<select value={date} onChange={(event) => setDate(event.target.value)}>{dates.map((value) => <option value={value} key={value}>{value}</option>)}</select></label>
        <label className="research-search"><MagnifyingGlass size={20} aria-hidden="true" /><span className="research-sr-only">搜索日报论文</span><input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索论文、作者、标签或分类" /></label>
        <p className="daily-current-date">LLM / Agent</p>
      </div>
      <div className="daily-tags" role="group" aria-label="按主题标签筛选">
        {["全部", ...dailyTags].map((tag) => {
          const count = tag === "全部" ? papers.length : papers.filter((paper) => paper.tags.includes(tag)).length;
          return <button type="button" key={tag} aria-pressed={selectedTag === tag}
            aria-label={`${tag} ${count} 篇`} onClick={() => setSelectedTag(tag)}>
            <span>{tag}</span><span className="daily-tag-count">{count}</span>
          </button>;
        })}
      </div>
      <div className="daily-list">
        {status === "loading" && <p className="daily-load" role="status">正在读取论文…</p>}
        {status === "error" && <div className="daily-error" role="alert"><p>暂时无法读取日报。</p><button type="button" onClick={() => setAttempt((value) => value + 1)}>重试</button></div>}
        {status === "ready" && visiblePapers.map((paper, index) => <DailyPaper paper={paper} index={index} key={paper.id} expanded={expandedId === paper.id} onToggle={() => setExpandedId((current) => current === paper.id ? null : paper.id)} />)}
      </div>
    </main>
    <footer className="research-footer research-container">{footer}</footer>
  </div>;
}
