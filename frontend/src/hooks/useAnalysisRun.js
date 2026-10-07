import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useReducer, useRef } from 'react'
import { api } from '../api/client'
import { keys } from '../api/queries'

const initial = { status: 'idle', stages: {}, error: null }

function reducer(state, action) {
  switch (action.type) {
    case 'start':
      return { status: 'running', stages: {}, error: null }
    case 'stage':
      return {
        ...state,
        stages: { ...state.stages, [action.stage]: { status: action.status, signal: action.signal ?? state.stages[action.stage]?.signal } },
      }
    case 'done':
      return { ...state, status: 'done' }
    case 'error':
      return { ...state, status: 'error', error: action.message }
    default:
      return state
  }
}

/** Runs the agent pipeline over SSE and mirrors each stage transition into local state. */
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
    dispatch({ type: 'start' })
    const source = new EventSource(api.streamUrl(productId))
    sourceRef.current = source

    source.addEventListener('stage', (e) => dispatch({ type: 'stage', ...JSON.parse(e.data) }))
    source.addEventListener('result', (e) => {
      const { analysis } = JSON.parse(e.data)
      queryClient.setQueryData(keys.analysis(productId), analysis)
      queryClient.invalidateQueries({ queryKey: ['products'] })
      queryClient.invalidateQueries({ queryKey: keys.stats })
      dispatch({ type: 'done' })
      close()
    })
    source.addEventListener('error', (e) => {
      const message = e.data ? JSON.parse(e.data).message : 'Connection to the analysis service was lost.'
      dispatch({ type: 'error', message })
      close()
    })
  }, [productId, queryClient])

  useEffect(() => close, [productId])

  return { ...state, start }
}
