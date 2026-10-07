import { Check, CircleDashed, LoaderCircle, X } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { AGENTS } from '../../lib/format'
import { STAGES } from './stages'

const ICON = { running: LoaderCircle, ok: Check, failed: X, skipped: CircleDashed, idle: CircleDashed }

export function AgentPipeline({ stages, running }) {
  return (
    <section className="panel" aria-live="polite">
      <header className="panel-head">
        <h2 className="panel-title">Agent pipeline</h2>
        <span className={`live ${running ? 'live-on' : ''}`}>{running ? 'Running' : 'LangGraph'}</span>
      </header>
      <ol className="pipeline">
        {STAGES.map((name, i) => {
          const { status, signal } = stages[name]
          const Icon = ICON[status] ?? CircleDashed
          const parallel = ['anomaly', 'authenticity', 'network'].includes(name)
          return (
            <li key={name} className={`stage stage-${status}`}>
              <span className="stage-icon">
                <Icon size={16} strokeWidth={2.4} className={status === 'running' ? 'spin' : undefined} aria-hidden />
              </span>
              <div className="stage-body">
                <div className="stage-top">
                  <span className="stage-name">
                    {String(i + 1).padStart(2, '0')} {AGENTS[name].label}
                    {parallel && <span className="stage-tag">parallel</span>}
                  </span>
                  {signal?.duration_ms != null && status !== 'running' && <span className="stage-time">{signal.duration_ms} ms</span>}
                </div>
                <AnimatePresence mode="wait" initial={false}>
                  <motion.p
                    key={signal?.summary ?? status}
                    className="stage-summary"
                    initial={{ opacity: 0, y: 4 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.2 }}
                  >
                    {status === 'running' ? 'Working…' : signal?.summary ?? AGENTS[name].role}
                  </motion.p>
                </AnimatePresence>
              </div>
            </li>
          )
        })}
      </ol>
    </section>
  )
}
