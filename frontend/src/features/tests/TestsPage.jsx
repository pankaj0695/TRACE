import {
  Ban,
  Check,
  ChevronDown,
  CircleDashed,
  Download,
  FlaskConical,
  KeyRound,
  LoaderCircle,
  OctagonAlert,
  Play,
  Square,
  TriangleAlert,
  X,
} from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTestPlan } from '../../api/queries'
import { Empty, Skeleton } from '../../components/ui'
import { duration, useNow } from '../../hooks/useNow'
import { useSystemTests } from '../../hooks/useSystemTests'

const PROFILES = [
  { value: 'full', label: 'Full', hint: '≈ 13 min' },
  { value: 'quick', label: 'Quick', hint: '≈ 2 min' },
]
const STATUS = {
  passed: { icon: Check, label: 'Passed' },
  failed: { icon: X, label: 'Failed' },
  error: { icon: OctagonAlert, label: 'Error' },
  skipped: { icon: Ban, label: 'Skipped' },
  running: { icon: LoaderCircle, label: 'Running' },
  pending: { icon: CircleDashed, label: 'Pending' },
}
const KIND = { negative: 'negative', resilience: 'fault', load: 'load' }
const KEY_STORE = 'trace.systemTests.key'

const readKey = () => {
  try {
    return sessionStorage.getItem(KEY_STORE) ?? ''
  } catch {
    return ''
  }
}
const saveKey = (v) => {
  try {
    sessionStorage.setItem(KEY_STORE, v)
  } catch {
    /* storage unavailable: key lives in memory only */
  }
}
const clock = (ms) => {
  const s = Math.max(0, Math.round(ms / 1000))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

function StatusIcon({ status, size = 16 }) {
  const { icon: Icon } = STATUS[status] ?? STATUS.pending
  return (
    <span className={`t-icon t-${status}`}>
      <Icon size={size} strokeWidth={2.4} className={status === 'running' ? 'spin' : undefined} aria-hidden />
    </span>
  )
}

function Details({ result }) {
  const metrics = Object.entries(result.metrics ?? {})
  const evidence = result.evidence && Object.keys(result.evidence).length ? result.evidence : null
  return (
    <div className="t-details">
      {result.detail && <p className={`t-detail-text t-detail-${result.status}`}>{result.detail}</p>}
      {metrics.length > 0 && (
        <dl className="mini-kv">
          {metrics.map(([k, v]) => (
            <div key={k}>
              <dt>{k.replaceAll('_', ' ')}</dt>
              <dd>{typeof v === 'object' ? JSON.stringify(v) : String(v)}</dd>
            </div>
          ))}
        </dl>
      )}
      {evidence && <pre className="t-evidence">{JSON.stringify(evidence, null, 2)}</pre>}
    </div>
  )
}

function TestRow({ test, result, running }) {
  const [open, setOpen] = useState(false)
  const status = result?.status ?? (running ? 'running' : 'pending')
  const expandable = Boolean(result && (result.detail || Object.keys(result.metrics ?? {}).length || Object.keys(result.evidence ?? {}).length))
  return (
    <li className={`t-row t-row-${status}`}>
      <button type="button" className="t-row-main" onClick={() => expandable && setOpen((o) => !o)} aria-expanded={expandable ? open : undefined} disabled={!expandable}>
        <StatusIcon status={status} />
        <span className="t-name">{test.name}</span>
        {KIND[test.kind] && <span className={`t-kind t-kind-${test.kind}`}>{KIND[test.kind]}</span>}
        <span className="t-time">{result ? duration(result.duration_ms) : running ? '…' : ''}</span>
        {expandable && <ChevronDown size={14} className={`chev ${open ? 'chev-open' : ''}`} aria-hidden />}
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.2 }} style={{ overflow: 'hidden' }}>
            <Details result={result} />
          </motion.div>
        )}
      </AnimatePresence>
    </li>
  )
}

function SuiteCard({ suite, tests, results, running }) {
  const counts = tests.reduce((acc, t) => {
    const s = results[t.id]?.status
    if (s) acc[s] = (acc[s] ?? 0) + 1
    return acc
  }, {})
  const done = tests.filter((t) => results[t.id]).length
  const bad = (counts.failed ?? 0) + (counts.error ?? 0)
  const active = tests.some((t) => t.id === running)
  return (
    <section className={`t-suite ${active ? 't-suite-active' : ''}`}>
      <header className="t-suite-head">
        <h3>{suite}</h3>
        <span className="t-suite-counts">
          {done}/{tests.length}
          {bad > 0 && <span className="t-chip t-chip-bad">{bad} failing</span>}
          {done === tests.length && bad === 0 && done > 0 && <span className="t-chip t-chip-ok">all clear</span>}
        </span>
      </header>
      <ol className="t-rows">
        {tests.map((t) => (
          <TestRow key={t.id} test={t} result={results[t.id]} running={running === t.id} />
        ))}
      </ol>
    </section>
  )
}

function download(run, plan) {
  const report = { run_id: run.runId, summary: run.summary, generated_at: new Date().toISOString(), tests: plan.map((t) => ({ ...t, ...(run.results[t.id] ?? { status: 'not run' }) })) }
  const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' }))
  const a = Object.assign(document.createElement('a'), { href: url, download: `trace-system-tests-${run.runId ?? 'report'}.json` })
  a.click()
  URL.revokeObjectURL(url)
}

export function TestsPage() {
  const [profile, setProfile] = useState('full')
  const [key, setKey] = useState(readKey)
  const run = useSystemTests()
  const { data: planData, isLoading } = useTestPlan(profile)
  const active = run.status === 'running' || run.status === 'connecting'
  const plan = useMemo(() => (run.plan.length ? run.plan : (planData?.tests ?? [])), [run.plan, planData])
  const now = useNow(active, 1000)
  const logRef = useRef(null)

  const suites = useMemo(() => {
    const map = new Map()
    for (const t of plan) map.set(t.suite, [...(map.get(t.suite) ?? []), t])
    return [...map.entries()]
  }, [plan])

  const results = Object.values(run.results)
  const count = (s) => results.filter((r) => r.status === s).length
  const done = results.length
  const elapsed = run.startedAt ? (run.finishedAt ?? now) - run.startedAt : 0
  const target = (run.targetS ?? planData?.target_s ?? 0) * 1000
  const pct = plan.length ? Math.round((done / plan.length) * 100) : 0
  const attention = results.filter((r) => r.status === 'failed' || r.status === 'error')
  const executed = count('passed') + count('failed') + count('error')
  const negatives = plan.filter((t) => t.kind === 'negative').length

  useEffect(() => {
    const el = logRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [run.log.length])

  const begin = () => {
    saveKey(key)
    run.start(key.trim(), profile)
  }

  return (
    <div className="page">
      <p className="eyebrow">Quality assurance</p>
      <div className="page-head">
        <h1 className="page-title">System tests</h1>
        <div className="page-actions">
          {run.summary && (
            <button type="button" className="btn btn-outline" onClick={() => download(run, plan)}>
              <Download size={18} aria-hidden /> Report
            </button>
          )}
        </div>
      </div>

      <section className="t-control">
        <label className="t-key">
          <KeyRound size={18} aria-hidden />
          <span className="sr-only">Analyst API key</span>
          <input type="password" value={key} onChange={(e) => setKey(e.target.value)} placeholder="Analyst API key (TRACE_MCP_API_KEYS)" autoComplete="off" disabled={active} />
        </label>
        <div className="segmented t-profiles" role="tablist" aria-label="Test profile">
          {PROFILES.map((p) => (
            <button key={p.value} type="button" role="tab" aria-selected={profile === p.value} onClick={() => setProfile(p.value)} disabled={active}>
              {p.label} <span className="t-hint">{p.hint}</span>
            </button>
          ))}
        </div>
        {active ? (
          <button type="button" className="btn btn-outline" onClick={run.stop}>
            <Square size={16} aria-hidden /> Stop
          </button>
        ) : (
          <button type="button" className="btn btn-primary" onClick={begin} disabled={!key.trim()}>
            <Play size={18} aria-hidden /> Run {plan.length || ''} tests
          </button>
        )}
      </section>
      <p className="fine t-note">
        Runs against the live backend: real HTTP and MCP calls, real agents and LLM. {negatives} negative cases check that bad input, missing auth and abuse are rejected. Failures are
        genuine. The key is kept for this browser tab only.
      </p>

      {run.status === 'error' && (
        <div className="callout callout-danger" role="alert">
          <TriangleAlert size={18} aria-hidden />
          <p>{run.error}</p>
        </div>
      )}
      {run.status === 'stopped' && (
        <div className="callout" role="status">
          <Square size={18} aria-hidden />
          <p>Run stopped. The server cancels the remaining tests when the stream closes.</p>
        </div>
      )}

      <div className="t-stats">
        {[
          ['Passed', count('passed'), 'ok'],
          ['Failed', count('failed'), count('failed') ? 'bad' : ''],
          ['Errors', count('error'), count('error') ? 'bad' : ''],
          ['Skipped', count('skipped'), ''],
          ['Pass rate', executed ? `${Math.round((count('passed') / executed) * 100)}%` : '—', ''],
          ['Elapsed', run.startedAt ? clock(elapsed) : '—', active ? 'live' : ''],
        ].map(([label, value, tone]) => (
          <div key={label} className={`t-stat ${tone ? `t-stat-${tone}` : ''}`}>
            <span className="exec-label">{label}</span>
            <strong>{value}</strong>
          </div>
        ))}
      </div>

      <div className="t-progress-row">
        <div className="progress progress-lg" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
          <motion.span className={`progress-fill ${active ? 'progress-live' : ''}`} animate={{ width: `${Math.max(done ? 2 : 0, pct)}%` }} transition={{ duration: 0.4 }} />
        </div>
        <span className="t-progress-text">
          {done}/{plan.length || '—'} tests
          {active && target > 0 && ` · ~${clock(Math.max(0, target - elapsed))} left`}
          {run.status === 'done' && run.summary && ` · finished in ${clock(run.summary.duration_s * 1000)}`}
        </span>
      </div>

      {attention.length > 0 && (
        <section className="t-attention" aria-label="Needs attention">
          <h2 className="block-title">Needs attention · {attention.length}</h2>
          <ul>
            {attention.map((r) => (
              <li key={r.id}>
                <StatusIcon status={r.status} />
                <div>
                  <strong>{r.name}</strong> <span className="t-suite-tag">{r.suite}</span>
                  <p>{r.detail}</p>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="t-layout">
        <div className="t-suites">
          {isLoading && !plan.length ? (
            <Skeleton h={240} />
          ) : plan.length ? (
            suites.map(([suite, tests]) => <SuiteCard key={suite} suite={suite} tests={tests} results={run.results} running={run.running} />)
          ) : (
            <Empty icon={FlaskConical} title="Test plan unavailable">
              The backend did not return a test plan. Check that it is deployed and reachable.
            </Empty>
          )}
        </div>
        <aside className="t-side">
          <div className="terminal">
            <div className="terminal-bar">
              <span className="terminal-dots" aria-hidden>
                <i /> <i /> <i />
              </span>
              <span>system tests{run.runId ? ` · run ${run.runId}` : ''}</span>
            </div>
            <ol className="log t-log" ref={logRef} role="log" aria-live="polite">
              {run.log.length === 0 && <li className="log-line log-dim">{active ? 'Starting…' : 'Enter an analyst key and press Run.'}</li>}
              {run.log.map((l, i) => (
                <li key={i} className={`log-line t-log-${l.level}`}>
                  <time className="log-time">{clock(l.t * 1000)}</time>
                  <span />
                  <span className="log-text">{l.msg}</span>
                </li>
              ))}
              {active && (
                <li className="log-line log-cursor" aria-hidden>
                  <span className="cursor" />
                </li>
              )}
            </ol>
          </div>
        </aside>
      </div>
    </div>
  )
}
