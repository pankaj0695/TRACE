const BASE = '/api'

export class ApiError extends Error {
  constructor(status, message) {
    super(message)
    this.status = status
  }
}

async function request(path, params) {
  const query = params ? `?${new URLSearchParams(Object.entries(params).filter(([, v]) => v !== '' && v != null))}` : ''
  const res = await fetch(`${BASE}${path}${query}`)
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new ApiError(res.status, body.detail || res.statusText)
  }
  return res.json()
}

export const api = {
  health: () => request('/health'),
  stats: () => request('/stats'),
  products: (params) => request('/products', params),
  product: (id) => request(`/products/${id}`),
  latestAnalysis: (id) => request(`/products/${id}/analysis`),
  searchReviews: (q, k = 20) => request('/search/reviews', { q, k }),
  exportUrl: `${BASE}/analyses/export.csv`,
  streamUrl: (id) => `${BASE}/products/${id}/analysis/stream`,
}
