import { AGENTS } from '../../lib/format'

export const STAGES = Object.keys(AGENTS)
export const DETECTORS = ['anomaly', 'authenticity', 'network']

/**
 * What each agent does, shown as its "tool calls". The call names mirror the backend agents; the operations are
 * descriptive (the stream reports agent-level start/finish, not per-operation events).
 */
export const TOOLS = {
  ingestion: { call: 'ingestion.load_reviews', ops: ['sqlite: read reviews', 'normalise text & timestamps'] },
  anomaly: { call: 'anomaly.analyze', ops: ['burst window scan', 'rating skew vs category', 'verified-purchase share'] },
  authenticity: { call: 'authenticity.analyze', ops: ['MiniLM embeddings', 'near-duplicate clusters', 'template phrases'] },
  network: { call: 'network.analyze', ops: ['reviewer graph (networkx)', 'co-review rings', 'new-account cohort'] },
  scoring: { call: 'scoring.fuse', ops: ['confidence-weighted fusion', 'detector conflict check'] },
  orchestrator: { call: 'orchestrator.report', ops: ['LLM report draft', 'policy mapping'] },
}

/** Merges live stream state with the last saved analysis so the pipeline always has something truthful to show. */
export function stageState(run, analysis) {
  return Object.fromEntries(
    STAGES.map((name) => {
      const live = run.stages[name]
      if (live) return [name, live]
      if (run.status === 'running') return [name, { status: 'idle' }]
      const signal = analysis?.signals[name]
      return [name, signal ? { status: signal.status, signal } : { status: run.status === 'done' ? 'skipped' : 'idle' }]
    }),
  )
}

/** Rebuilds an approximate timeline from a saved analysis (per-agent durations) when no live run happened this session. */
export function eventsFromAnalysis(analysis) {
  if (!analysis) return []
  const sig = analysis.signals
  const dur = (n) => sig[n]?.duration_ms ?? 0
  const events = []
  let id = 0
  const push = (at, kind, stage, status, text) => events.push({ id: id++, at, kind, stage, status, text })

  push(0, 'started', null, 'ok', `Pipeline ${STAGES.length} agents · saved run`)
  let t = 0
  const call = (name, start) => {
    if (!sig[name]) return start
    push(start, 'call', name, 'running', `${TOOLS[name].call}(product_id)`)
    const end = start + dur(name)
    push(end, 'return', name, sig[name].status, `${sig[name].summary}`)
    return end
  }
  t = call('ingestion', t)
  const detectorEnd = Math.max(t, ...DETECTORS.map((d) => call(d, t)))
  t = call('scoring', detectorEnd)
  t = call('orchestrator', t)
  push(t, 'result', null, 'ok', `Analysis saved · risk ${Math.round(analysis.assessment.risk_score)} · ${analysis.assessment.tier}`)
  return events.sort((a, b) => a.at - b.at || a.id - b.id)
}
