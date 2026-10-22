const external = { target: "_blank", rel: "noopener noreferrer" };

export default function FilingLinks() {
  const icp = import.meta.env.VITE_ICP_FILING_NUMBER || "粤ICP备2026124110号-1";
  const police = import.meta.env.VITE_POLICE_FILING_NUMBER || "粤公网安备44030002017147号";
  const policeCode = import.meta.env.VITE_POLICE_FILING_CODE || "44030002017147";
  return <div className="filing-links">
    <a href="https://beian.miit.gov.cn/#/Integrated/index" {...external}>{icp}</a>
    <a href={`https://beian.mps.gov.cn/#/query/webSearch?code=${encodeURIComponent(policeCode)}`} {...external}>
      <img className="police-mark" src="/assets/police-filing.png" alt="" aria-hidden="true" />{police}
    </a>
  </div>;
}
