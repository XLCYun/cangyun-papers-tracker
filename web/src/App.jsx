import "@fontsource-variable/noto-serif-sc";
import "./enterprise-research.css";
import "./site.css";
import ArxivDaily from "./ArxivDaily.jsx";
import FilingLinks from "./FilingLinks.jsx";
import { ArrowUpRight } from "@phosphor-icons/react";
import { lazy, Suspense } from "react";

const EnterpriseResearch = lazy(() => import("./EnterpriseResearch.jsx"));

function ResearchHome() {
  return <div className="research-page">
    <main className="research-container research-main hub-main">
      <h1 className="hub-title"><span>Research</span></h1>
      <p className="hub-description">追踪每日论文，整理企业智能体评测。</p>
      <nav className="hub-entries" aria-label="研究专题">
        <a className="hub-entry" href="/arxiv-daily"><span className="hub-entry-number">01</span><div><h2>每日 arXiv</h2><p>LLM 与 Agent 论文，每日更新。</p></div><ArrowUpRight aria-hidden="true" /></a>
        <a className="hub-entry" href="/enterprise-agent-benchmark"><span className="hub-entry-number">02</span><div><h2>企业 Agent Benchmark</h2><p>企业任务与经营模拟评测，按时间整理。</p></div><ArrowUpRight aria-hidden="true" /></a>
      </nav>
    </main>
    <footer className="research-footer research-container"><FilingLinks /></footer>
  </div>;
}

export default function App() {
  const path = window.location.pathname.replace(/\/+$/, "") || "/";
  if (path === "/arxiv-daily") return <ArxivDaily footer={<FilingLinks />} />;
  if (path === "/enterprise-agent-benchmark") return <Suspense fallback={<div className="research-page"><main className="research-container research-main"><p className="daily-load" role="status">正在读取研究时间线…</p></main></div>}><EnterpriseResearch footer={<FilingLinks />} /></Suspense>;
  if (path === "/") return <ResearchHome />;
  return <div className="research-page"><main className="research-container research-main not-found"><h1>页面未找到</h1><a href="/">返回研究首页</a></main><footer className="research-footer research-container"><FilingLinks /></footer></div>;
}
