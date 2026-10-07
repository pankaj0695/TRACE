import { Check, ClipboardCopy, Sparkles, TriangleAlert } from 'lucide-react'
import { useState } from 'react'
import { Badge, SeverityBadge } from '../../components/ui'
import { AGENTS, date } from '../../lib/format'

function toText(analysis) {
  const { report, product, assessment } = analysis
  return [
    `TRACE trust report — ${product.title} (${product.id})`,
    `Risk ${assessment.risk_score}/100 · ${assessment.tier}`,
    '',
    report.headline,
    report.summary,
    '',
    'Findings:',
    ...report.findings.map((f) => `- [${f.severity}] ${f.title} (${f.policy}): ${f.detail}`),
    '',
    'Recommendations:',
    ...report.recommendations.map((r, i) => `${i + 1}. ${r}`),
    '',
    `Reviewer note: ${report.reviewer_note}`,
  ].join('\n')
}

export function ReportTab({ analysis }) {
  const [copied, setCopied] = useState(false)
  const { report } = analysis
  const byLLM = report.generated_by !== 'rules'

  const copy = async () => {
    await navigator.clipboard.writeText(toText(analysis))
    setCopied(true)
    setTimeout(() => setCopied(false), 1600)
  }

  return (
    <div className="report">
      <div className="report-meta">
        <Badge tone={byLLM ? 'info' : 'neutral'} icon={Sparkles} size="sm">
          {byLLM ? `Drafted by ${report.generated_by}` : 'Rule-based draft'}
        </Badge>
        <span className="muted">Analysed {date(analysis.created_at)}</span>
        <button className="text-btn" onClick={copy}>
          {copied ? <Check size={16} /> : <ClipboardCopy size={16} />} {copied ? 'Copied' : 'Copy report'}
        </button>
      </div>

      <h2 className="report-headline">{report.headline}</h2>
      <p className="report-summary">{report.summary}</p>

      {report.reviewer_note && (
        <div className="callout">
          <TriangleAlert size={18} aria-hidden />
          <p>
            <strong>Reviewer note.</strong> {report.reviewer_note}
          </p>
        </div>
      )}

      <h3 className="block-title">Findings · mapped to policy</h3>
      {report.findings.length === 0 ? (
        <p className="muted">No findings — the agents found nothing that needs attention.</p>
      ) : (
        <ul className="findings">
          {report.findings.map((f, i) => (
            <li key={i} className="finding" style={{ animationDelay: `${i * 50}ms` }}>
              <div className="finding-head">
                <SeverityBadge severity={f.severity} />
                <span className="finding-title">{f.title}</span>
              </div>
              <p className="finding-detail">{f.detail}</p>
              <div className="finding-tags">
                <span className="tag">{f.policy}</span>
                <span className="tag tag-quiet">{AGENTS[f.agent]?.label ?? f.agent} agent</span>
              </div>
            </li>
          ))}
        </ul>
      )}

      <h3 className="block-title">Recommended next steps</h3>
      <ol className="steps">
        {report.recommendations.map((r, i) => (
          <li key={i}>{r}</li>
        ))}
      </ol>
    </div>
  )
}
