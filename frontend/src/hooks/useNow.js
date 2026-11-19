import { useEffect, useState } from 'react'

/** Re-renders every `interval` ms while `active`, returning the current timestamp (for live elapsed timers). */
export function useNow(active, interval = 100) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active) return undefined
    const id = setInterval(() => setNow(Date.now()), interval)
    return () => clearInterval(id)
  }, [active, interval])
  return now
}

export const seconds = (ms) => `${(Math.max(0, ms) / 1000).toFixed(ms < 10000 ? 2 : 1)}s`

/** 17 ms, 1.4 s, 2m 42s */
export const duration = (ms) => (ms < 1000 ? `${Math.round(ms)} ms` : ms < 60000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`)
