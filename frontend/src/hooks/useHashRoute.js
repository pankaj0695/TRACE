import { useSyncExternalStore } from 'react'

const subscribe = (cb) => {
  window.addEventListener('hashchange', cb)
  return () => window.removeEventListener('hashchange', cb)
}
const snapshot = () => window.location.hash || '#/'

/** Minimal hash router: '#/', '#/product/:id', '#/search?q=' */
export function useHashRoute() {
  const hash = useSyncExternalStore(subscribe, snapshot)
  const [path, query = ''] = hash.slice(1).split('?')
  const params = Object.fromEntries(new URLSearchParams(query))
  const [, section, id] = path.split('/')
  return { section: section || 'console', id: id ? decodeURIComponent(id) : null, params }
}

export const navigate = {
  console: () => (window.location.hash = '#/'),
  product: (id) => (window.location.hash = `#/product/${encodeURIComponent(id)}`),
  search: (q) => (window.location.hash = `#/search?${new URLSearchParams({ q })}`),
}
