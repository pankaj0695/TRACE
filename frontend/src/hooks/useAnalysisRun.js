import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useReducer, useRef } from 'react'
import { api } from '../api/client'
import { keys } from '../api/queries'
import { investigatorSteps, TOOLS } from '../features/analysis/stages'

const initial = { status: 'idle', stages: {}, error: null, events: [], startedAt: null, finishedAt: null }

const withEvent = (state, ev) => ({ ...state, events: [...state.events, { id: state.events.length, ...ev }] })

function reducer(state, action) {
  const at = action.at
  switch (action.type) {
    case 'start':
      return withEvent({ ...initial, status: 'running', startedAt: at }, { at: 0, kind: 'started', stage: null, status: 'ok', text: 'Connecting to analysis stream…' })
    case 'stage': {
      const prev = state.stages[action.stage] ?? {}
      const running = action.status === 'running'
      const next = {
        ...prev,
        status: action.status,
        signal: action.signal ?? prev.signal,
        startedAt: running ? at : (prev.startedAt ?? at),
        endedAt: running ? null : at,
      }
      const rel = at - state.startedAt
      const ev = running
        ? { at: rel, kind: 'call', stage: action.stage, status: 'running', text: `${TOOLS[action.stage]?.call ?? action.stage}(product_id)` }
        : {
            at: rel,
            kind: 'return',
            stage: action.stage,
            status: action.status,
            text: action.signal?.summary ?? action.status,
            ms: action.signal?.duration_ms,
            findings: action.signal?.findings?.length ?? 0,
          }
      let nextState = withEvent({ ...state, stages: { ...state.stages, [action.stage]: next } }, ev)
      if (!running && action.stage === 'investigator') {
        for (const step of investigatorSteps(action.signal)) {
          nextState = withEvent(nextState, { at: rel, kind: 'tool', stage: 'investigator', status: step.status, text: step.text })
        }
      }
      return nextState
    }
    case 'done':
      return withEvent({ ...state, status: 'done', finishedAt: at }, { at: at - state.startedAt, kind: 'result', stage: null, status: 'ok', text: action.text })
    case 'error':
      return withEvent({ ...state, status: 'error', error: action.message, finishedAt: at }, { at: at - state.startedAt, kind: 'error', stage: null, status: 'failed', text: action.message })
    default:
      return state
  }
}

/** Runs the agent pipeline over SSE and mirrors each stage transition (with timings) into local state. */
export function useAnalysisRun(productId) {
  const [state, dispatch] = useReducer(reducer, initial)
  const sourceRef = useRef(null)
  const queryClient = useQueryClient()

  const close = () => {
    sourceRef.current?.close()
    sourceRef.current = null
  }

  const start = useCallback(() => {
    close()
    dispatch({ type: 'start', at: Date.now() })
    const source = new EventSource(api.streamUrl(productId))
    sourceRef.current = source

    source.addEventListener('stage', (e) => dispatch({ type: 'stage', at: Date.now(), ...JSON.parse(e.data) }))
    source.addEventListener('result', (e) => {
      const { analysis } = JSON.parse(e.data)
      queryClient.setQueryData(keys.analysis(productId), analysis)
      queryClient.invalidateQueries({ queryKey: ['products'] })
      queryClient.invalidateQueries({ queryKey: keys.stats })
      const a = analysis.assessment
      dispatch({ type: 'done', at: Date.now(), text: `Analysis saved · risk ${Math.round(a.risk_score)} · ${a.tier}` })
      close()
    })
    source.addEventListener('error', (e) => {
      const message = e.data ? JSON.parse(e.data).message : 'Connection to the analysis service was lost.'
      dispatch({ type: 'error', at: Date.now(), message })
      close()
    })
  }, [productId, queryClient])

  useEffect(() => close, [productId])

  return { ...state, start }
}
