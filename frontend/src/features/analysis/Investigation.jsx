import { CircleHelp, SearchCheck, ShieldAlert, ShieldCheck, Wrench } from 'lucide-react'
import { Badge } from '../../components/ui'
import { pct } from '../../lib/format'

const VERDICT = {
  supports_burst: { tone: 'danger', icon: ShieldAlert, label: 'Supports the burst signal' },
  explains_burst: { tone: 'ok', icon: ShieldCheck, label: 'Benign explanation found' },
  unresolvable: { tone: 'warn', icon: CircleHelp, label: 'Unresolvable: needs a human' },
}

export function VerdictBadge({ verdict, size = 'sm' }) {
  const v = VERDICT[verdict] ?? VERDICT.unresolvable
  return (
    <Badge tone={v.tone} icon={v.icon} size={size}>
      {v.label}
    </Badge>
  )
}

/** The Investigator's verdict and every tool call it made, for the reviewer. */
export function InvestigationPanel({ signal }) {
  const m = signal.metrics ?? {}
  const log = signal.artifacts?.log ?? []
  const downgraded = m.model_verdict && m.model_verdict !== 'none' && m.model_verdict !== m.verdict

  return (
    <section className="investigation" aria-label="Investigation">
      <header className="investigation-head">
        <span className="investigation-title">
          <SearchCheck size={18} aria-hidden /> Investigation
        </span>
        <VerdictBadge verdict={m.verdict} />
      </header>

      <p className="investigation-summary">{signal.summary}</p>

      <dl className="mini-kv">
        <div>
          <dt>risk added</dt>
          <dd>{Math.round(signal.risk * 100)}</dd>
        </div>
        <div>
          <dt>confidence</dt>
          <dd>{pct(signal.confidence)}</dd>
        </div>
        <div>
          <dt>tool calls</dt>
          <dd>{m.tool_calls ?? log.length}</dd>
        </div>
        <div>
          <dt>driven by</dt>
          <dd>{m.mode === 'rules' ? 'rules (no model)' : m.model}</dd>
        </div>
      </dl>

      {m.unresolved_reason && (
        <p className="investigation-reason">
          <strong>Why unresolved:</strong> {m.unresolved_reason}
        </p>
      )}
      {downgraded && (
        <p className="fine">
          The model proposed “{m.model_verdict}”; code-level validation changed it because the verdict was not backed by a tool result.
        </p>
      )}

      {log.length > 0 && (
        <ol className="inv-log">
          {log.map((s, i) => (
            <li key={i} className={`inv-log-item inv-${s.status}`}>
              <div className="inv-log-top">
                <code>
                  <Wrench size={11} aria-hidden /> {s.tool}({s.args && Object.keys(s.args).length ? JSON.stringify(s.args) : ''})
                </code>
                <span className={`stage-state stage-state-${s.status === 'ok' ? 'ok' : 'failed'}`}>{s.status}</span>
              </div>
              {s.reason && <p className="inv-log-reason">{s.reason}</p>}
              {s.result && <p className="inv-log-result">{typeof s.result === 'string' ? s.result : JSON.stringify(s.result)}</p>}
            </li>
          ))}
        </ol>
      )}
      <p className="fine">
        The investigator adds one signal; it cannot change weights, thresholds or detector results. Handles (r1, r2…) stand in for reviewer identities.
      </p>
    </section>
  )
}
