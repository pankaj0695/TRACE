import { Check, ChevronDown, CircleDashed, CornerLeftUp, LoaderCircle, Wrench, X } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useState } from 'react'
import { SeverityBadge } from '../../components/ui'
import { duration, seconds, useNow } from '../../hooks/useNow'
import { AGENTS } from '../../lib/format'
import { DETECTORS, STAGES, TOOLS } from './stages'
import { VerdictBadge } from './Investigation'

const ICON = { running: LoaderCircle, ok: Check, failed: X, skipped: CircleDashed, idle: CircleDashed }
const LABEL = { running: 'running', ok: 'done', failed: 'failed', skipped: 'skipped', idle: 'queued' }
const CONDITIONAL = { investigator: { skipped: 'not needed', idle: 'if needed' } }

const fmtMetric = (v) => (typeof v === 'number' ? (Number.isInteger(v) ? v : +v.toFixed(3)) : typeof v === 'boolean' ? String(v) : null)

function InvestigatorOutput({ signal }) {
  const log = signal.artifacts?.log ?? []
  return (
    <div className="stage-output">
      <VerdictBadge verdict={signal.metrics?.verdict} />
      <ol className="inv-steps">
        {log.map((s, i) => (
          <li key={i} className={`inv-step inv-${s.status}`}>
            <code>{s.tool}()</code> <span className="fine">{s.reason}</span>
          </li>
        ))}
      </ol>
      {signal.metrics?.unresolved_reason && <p className="fine">Why unresolved: {signal.metrics.unresolved_reason}</p>}
    </div>
  )
}

function StageOutput({ signal }) {
  if (signal.agent === 'investigator') return <InvestigatorOutput signal={signal} />
  const metrics = Object.entries(signal.metrics ?? {})
    .map(([k, v]) => [k, fmtMetric(v)])
    .filter(([, v]) => v !== null)
    .slice(0, 8)
  return (
    <div className="stage-output">
      {metrics.length > 0 && (
        <dl className="mini-kv">
          {metrics.map(([k, v]) => (
            <div key={k}>
              <dt>{k.replaceAll('_', ' ')}</dt>
              <dd>{v}</dd>
            </div>
          ))}
        </dl>
      )}
      {signal.findings?.length > 0 && (
        <ul className="mini-findings">
          {signal.findings.map((f) => (
            <li key={f.code}>
              <SeverityBadge severity={f.severity} />
              <span>{f.title}</span>
            </li>
          ))}
        </ul>
      )}
      {!metrics.length && !signal.findings?.length && <p className="fine">No additional output.</p>}
    </div>
  )
}

function Stage({ name, index, state, now, parallel }) {
  const [open, setOpen] = useState(false)
  const { status, signal, startedAt } = state
  const Icon = ICON[status] ?? CircleDashed
  const tool = TOOLS[name]
  const expandable = status !== 'running' && status !== 'idle' && signal
  const elapsed = status === 'running' && startedAt ? now - startedAt : signal?.duration_ms

  return (
    <li className={`stage stage-${status} ${parallel ? 'stage-parallel' : ''}`}>
      <span className="stage-icon">
        <Icon size={16} strokeWidth={2.4} className={status === 'running' ? 'spin' : undefined} aria-hidden />
      </span>
      <div className="stage-body">
        <button
          type="button"
          className="stage-top"
          onClick={() => expandable && setOpen((o) => !o)}
          aria-expanded={expandable ? open : undefined}
          disabled={!expandable}
        >
          <span className="stage-name">
            <span className="stage-index">{String(index + 1).padStart(2, '0')}</span> {AGENTS[name].label}
          </span>
          <span className="stage-meta">
            {elapsed != null && status !== 'idle' && (
              <span className="stage-time">{status === 'running' ? seconds(elapsed) : duration(elapsed)}</span>
            )}
            <span className={`stage-state stage-state-${status}`}>{CONDITIONAL[name]?.[status] ?? LABEL[status] ?? status}</span>
            {expandable && <ChevronDown size={14} className={`chev ${open ? 'chev-open' : ''}`} aria-hidden />}
          </span>
        </button>

        <code className="tool-call">
          <Wrench size={11} aria-hidden /> {tool.call}()
        </code>

        <AnimatePresence mode="wait" initial={false}>
          <motion.p
            key={signal?.summary ?? status}
            className="stage-summary"
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
          >
            {status === 'running' ? (
              <span className="ops">
                {tool.ops.map((op, i) => (
                  <span key={op} className="op" style={{ animationDelay: `${i * 0.25}s` }}>
                    {op}
                  </span>
                ))}
              </span>
            ) : name === 'investigator' && status === 'skipped' ? (
              'Not escalated: evidence was consistent.'
            ) : (
              signal?.summary ?? AGENTS[name].role
            )}
          </motion.p>
        </AnimatePresence>

        <AnimatePresence initial={false}>
          {open && expandable && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.22 }}
              style={{ overflow: 'hidden' }}
            >
              <StageOutput signal={signal} />
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </li>
  )
}

export function AgentPipeline({ stages, running, startedAt }) {
  const now = useNow(running)
  const done = STAGES.filter((s) => ['ok', 'failed', 'skipped'].includes(stages[s].status)).length
  const pct = Math.round((done / STAGES.length) * 100)
  const render = (name) => <Stage key={name} name={name} index={STAGES.indexOf(name)} state={stages[name]} now={now} parallel={DETECTORS.includes(name)} />

  return (
    <section className="panel" aria-live="polite">
      <header className="panel-head">
        <h2 className="panel-title">Agent pipeline</h2>
        <span className={`live ${running ? 'live-on' : ''}`}>
          {running ? `${done}/${STAGES.length} · ${seconds(now - startedAt)}` : 'LangGraph'}
        </span>
      </header>
      {running && (
        <div className="progress" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
          <motion.span className="progress-fill" animate={{ width: `${Math.max(4, pct)}%` }} transition={{ duration: 0.4 }} />
        </div>
      )}
      <ol className="pipeline">
        {render('ingestion')}
        <li className="fan" aria-label="Detectors run in parallel">
          <span className="fan-label">parallel fan-out</span>
          <ol className="pipeline fan-list">{DETECTORS.map(render)}</ol>
        </li>
        {render('scoring')}
        <li className={`fan fan-loop ${stages.investigator.status === 'skipped' ? 'fan-off' : ''}`} aria-label="Escalation: only on ambiguous evidence, then re-score">
          <span className="fan-label">
            <CornerLeftUp size={11} aria-hidden /> escalation · re-scores
          </span>
          <ol className="pipeline fan-list">{render('investigator')}</ol>
        </li>
        {render('orchestrator')}
      </ol>
    </section>
  )
}
