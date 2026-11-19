import { useCallback, useEffect, useReducer, useRef } from 'react'
import { API_BASE } from '../api/client'

const initial = { status: 'idle', plan: [], results: {}, running: null, log: [], summary: null, error: null, runId: null, targetS: null, startedAt: null, finishedAt: null }

function reducer(state, a) {
  switch (a.type) {
    case 'connecting':
      return { ...initial, status: 'connecting', startedAt: a.at }
    case 'run_started':
      return { ...state, status: 'running', plan: a.plan, runId: a.run_id, targetS: a.target_s, startedAt: a.at }
    case 'test_started':
      return { ...state, running: a.id }
    case 'test_finished':
      return {
        ...state,
        running: null,
        results: { ...state.results, [a.id]: a },
        log: [...state.log, { t: a.t, level: a.status, msg: `${a.status.toUpperCase().padEnd(7)} ${a.name}${a.detail ? ` · ${a.detail}` : ''}` }].slice(-400),
      }
    case 'log':
      return { ...state, log: [...state.log, { t: a.t, level: 'info', msg: a.msg }].slice(-400) }
    case 'run_finished':
      return { ...state, status: 'done', summary: a.summary, running: null, finishedAt: a.at }
    case 'error':
      return { ...state, status: 'error', error: a.message, running: null, finishedAt: a.at }
    case 'stopped':
      return { ...state, status: 'stopped', running: null, finishedAt: a.at }
    default:
      return state
  }
}

const MESSAGES = {
  401: 'That API key was not accepted.',
  403: 'This key is not allowed to run system tests (analyst role or higher required).',
  409: 'A system-test run is already in progress on the server.',
}

/** Starts a run and follows its SSE stream (fetch, because EventSource cannot send an Authorization header). */
export function useSystemTests() {
  const [state, dispatch] = useReducer(reducer, initial)
  const abortRef = useRef(null)

  const start = useCallback(async (token, profile) => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    dispatch({ type: 'connecting', at: Date.now() })
    try {
      const res = await fetch(`${API_BASE}/system-tests/run?profile=${profile}`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        signal: controller.signal,
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(MESSAGES[res.status] ?? body.detail ?? `Server returned ${res.status}`)
      }
      const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
      let buffer = ''
      let finished = false
      for (;;) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += value
        let cut
        while ((cut = buffer.indexOf('\n\n')) >= 0) {
          const chunk = buffer.slice(0, cut)
          buffer = buffer.slice(cut + 2)
          const data = chunk.split('\n').find((l) => l.startsWith('data:'))
          if (!data) continue
          const event = JSON.parse(data.slice(5))
          if (event.type === 'run_error') throw new Error(event.message)
          if (event.type) dispatch({ ...event, at: Date.now() })
          if (event.type === 'run_finished') finished = true
        }
      }
      if (!finished) throw new Error('The connection closed before the run finished (server restart or timeout).')
    } catch (err) {
      if (err.name === 'AbortError') dispatch({ type: 'stopped', at: Date.now() })
      else dispatch({ type: 'error', message: err.message, at: Date.now() })
    } finally {
      if (abortRef.current === controller) abortRef.current = null
    }
  }, [])

  const stop = useCallback(() => abortRef.current?.abort(), [])
  useEffect(() => () => abortRef.current?.abort(), [])

  return { ...state, start, stop }
}
