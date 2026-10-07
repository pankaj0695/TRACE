export const compact = (n) => (n == null ? '—' : Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(n))

export const pct = (v, digits = 0) => (v == null ? '—' : `${(v * 100).toFixed(digits)}%`)

export const date = (iso) =>
  iso ? new Date(iso).toLocaleDateString('en', { month: 'short', day: 'numeric', year: 'numeric' }) : '—'

export const relative = (iso) => {
  if (!iso) return 'never'
  const mins = Math.round((Date.now() - new Date(iso)) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.round(mins / 60)
  return hours < 24 ? `${hours}h ago` : date(iso)
}

export const riskTone = (risk) => (risk >= 0.6 ? 'danger' : risk >= 0.3 ? 'warn' : 'ok')

export const TIER = {
  low: { label: 'Low', tone: 'ok' },
  medium: { label: 'Medium', tone: 'warn' },
  high: { label: 'High', tone: 'danger' },
  critical: { label: 'Critical', tone: 'danger' },
  insufficient_data: { label: 'Insufficient', tone: 'neutral' },
}

export const AGENTS = {
  ingestion: { label: 'Ingestion', role: 'Load & normalise reviews' },
  anomaly: { label: 'Anomaly', role: 'Volume, timing, ratings' },
  authenticity: { label: 'Authenticity', role: 'Duplicates & templates (IR)' },
  network: { label: 'Network', role: 'Reviewer knowledge graph' },
  scoring: { label: 'Trust scoring', role: 'Weighted aggregation' },
  orchestrator: { label: 'Orchestrator', role: 'Resolve & report' },
}
