import { ArrowRight, Check, CornerDownRight, Flag, Play, TriangleAlert, Wrench, X } from 'lucide-react'
import { motion } from 'motion/react'
import { useEffect, useMemo, useRef } from 'react'
import { duration, seconds, useNow } from '../../hooks/useNow'
import { eventsFromAnalysis, STAGES } from './stages'

const returns0 = (events) => events.filter((e) => e.kind === 'return')

const GLYPH = { started: Play, call: ArrowRight, tool: Wrench, return: CornerDownRight, result: Check, error: TriangleAlert }

function Line({ ev }) {
  const Icon = ev.status === 'failed' ? X : (GLYPH[ev.kind] ?? ArrowRight)
  return (
    <motion.li
      className={`log-line log-${ev.kind} log-${ev.status}`}
      initial={{ opacity: 0, x: -6 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.2 }}
    >
      <time className="log-time">+{seconds(ev.at)}</time>
      <Icon size={13} strokeWidth={2.4} className="log-icon" aria-hidden />
      <span className="log-text">
        {ev.kind === 'call' && <span className="log-verb">call </span>}
        {ev.kind === 'tool' && <span className="log-verb">  tool </span>}
        {ev.kind === 'return' && <span className="log-verb">{ev.stage} → </span>}
        {ev.text}
        {ev.kind === 'return' && ev.ms != null && <span className="log-dim"> · {duration(ev.ms)}</span>}
        {ev.kind === 'return' && ev.findings > 0 && (
          <span className="log-flag">
            <Flag size={11} aria-hidden /> {ev.findings}
          </span>
        )}
      </span>
    </motion.li>
  )
}

/** Live (or last-saved) execution trace: every agent call, its result and timing, in order. */
export function ExecutionTab({ run, analysis, running, onOpenReport }) {
  const now = useNow(running)
  const endRef = useRef(null)
  const live = run.events.length > 0
  const events = useMemo(() => (live ? run.events : eventsFromAnalysis(analysis)), [live, run.events, analysis])
  const total = running ? now - run.startedAt : live ? (run.finishedAt ?? now) - run.startedAt : (events.at(-1)?.at ?? 0)
  const calls = events.filter((e) => e.kind === 'call' || e.kind === 'tool').length
  const stagesDone = new Set(returns0(events).map((e) => e.stage)).size
  const returns = events.filter((e) => e.kind === 'return')
  const failed = returns.filter((e) => e.status === 'failed').length
  const pct = running ? Math.round((Math.min(stagesDone, STAGES.length - 1) / STAGES.length) * 100) : 100

  useEffect(() => {
    if (running) endRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [events.length, running])

  return (
    <div className="exec">
      <div className="exec-stats">
        <div>
          <span className="exec-label">Status</span>
          <strong className={`exec-status ${running ? 'is-live' : failed || run.status === 'error' ? 'is-bad' : ''}`}>
            {running ? 'Running' : run.status === 'error' ? 'Failed' : live ? 'Completed' : 'Last saved run'}
          </strong>
        </div>
        <div>
          <span className="exec-label">Elapsed</span>
          <strong>{seconds(total)}</strong>
        </div>
        <div>
          <span className="exec-label">Tool calls</span>
          <strong>{calls}</strong>
        </div>
        <div>
          <span className="exec-label">Findings</span>
          <strong>{returns.reduce((n, e) => n + (e.findings ?? 0), 0) || (analysis ? analysis.report.findings.length : 0)}</strong>
        </div>
      </div>

      <div className="progress progress-lg" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        <motion.span className={`progress-fill ${running ? 'progress-live' : ''}`} animate={{ width: `${Math.max(4, pct)}%` }} transition={{ duration: 0.5 }} />
      </div>

      <div className="terminal" role="log" aria-live="polite" aria-label="Execution log">
        <div className="terminal-bar">
          <span className="terminal-dots" aria-hidden>
            <i /> <i /> <i />
          </span>
          <span>trace · analysis run</span>
        </div>
        <ol className="log">
          {events.length === 0 && <li className="log-line log-dim">Waiting for the first event…</li>}
          {events.map((ev) => (
            <Line key={ev.id} ev={ev} />
          ))}
          {running && (
            <li className="log-line log-cursor" aria-hidden>
              <span className="cursor" />
            </li>
          )}
          <li ref={endRef} aria-hidden />
        </ol>
      </div>

      {!running && analysis && (
        <div className="exec-actions">
          <p className="fine">
            {live ? 'Run finished.' : 'Timeline reconstructed from the saved run’s per-agent timings.'} Tool-call names mirror the backend agents.
          </p>
          <button type="button" className="btn btn-primary" onClick={onOpenReport}>
            View report <ArrowRight size={18} aria-hidden />
          </button>
        </div>
      )}
    </div>
  )
}
