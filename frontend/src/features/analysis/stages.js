import { AGENTS } from '../../lib/format'

export const STAGES = Object.keys(AGENTS)

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
