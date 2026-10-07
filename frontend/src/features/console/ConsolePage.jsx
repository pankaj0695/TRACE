import { ArrowDownUp, Download, Filter, ScanSearch } from 'lucide-react'
import { api } from '../../api/client'
import { useProducts, useStats } from '../../api/queries'
import { StatCard } from '../../components/StatCard'
import { Button, Select } from '../../components/ui'
import { navigate } from '../../hooks/useHashRoute'
import { compact } from '../../lib/format'
import { useConsoleFilters } from '../../store/ui'
import { ProductTable } from './ProductTable'

const TIERS = [
  { value: '', label: 'All risk tiers' },
  { value: 'critical', label: 'Critical' },
  { value: 'high', label: 'High' },
  { value: 'medium', label: 'Medium' },
  { value: 'low', label: 'Low' },
  { value: 'unscanned', label: 'Not scanned' },
]
const SORTS = [
  { value: 'risk', label: 'Highest risk' },
  { value: 'spike', label: 'Largest burst' },
  { value: 'reviews', label: 'Most reviews' },
  { value: 'title', label: 'Title A–Z' },
]

export function ConsolePage() {
  const { tier, sort, setTier, setSort } = useConsoleFilters()
  const { data: stats, isLoading } = useStats()
  const { data: nextSuspect } = useProducts({ tier: 'unscanned', sort: 'spike', limit: 1 })
  const suspect = nextSuspect?.items[0]?.product

  const trend = stats?.recent.map((r) => r.risk) ?? []
  const flaggedShare = stats?.analyzed ? stats.flagged / stats.analyzed : 0

  return (
    <div className="page">
      <p className="eyebrow">Trust &amp; safety console</p>
      <div className="page-head">
        <h1 className="page-title">Console</h1>
        <div className="page-actions">
          <Select label="Risk tier" icon={Filter} value={tier} onChange={setTier} options={TIERS} />
          <Select label="Sort" icon={ArrowDownUp} value={sort} onChange={setSort} options={SORTS} />
          <a className="btn btn-outline" href={api.exportUrl} download>
            <Download size={18} aria-hidden /> Export audit
          </a>
          <Button variant="primary" icon={ScanSearch} disabled={!suspect} onClick={() => navigate.product(suspect.id)}>
            Scan top suspect
          </Button>
        </div>
      </div>

      <div className="stat-grid">
        <StatCard
          index={0}
          loading={isLoading}
          label="Monitored listings"
          value={compact(stats?.monitored)}
          caption={`${compact(stats?.reviews)} reviews · ${compact(stats?.reviewers)} reviewers`}
          badge={{ tone: 'neutral', text: 'Amazon Fashion' }}
        />
        <StatCard
          index={1}
          loading={isLoading}
          label="Listings analysed"
          value={compact(stats?.analyzed)}
          caption="risk trend, latest scans"
          badge={{ tone: 'ok', text: `${stats ? Math.round((stats.analyzed / stats.monitored) * 100) : 0}% coverage` }}
          trend={trend}
        />
        <StatCard
          index={2}
          loading={isLoading}
          label="Flagged for review"
          value={compact(stats?.flagged)}
          caption={`${stats?.tiers.high ?? 0} high · ${stats?.tiers.critical ?? 0} critical · ${stats?.tiers.medium ?? 0} medium`}
          badge={{ tone: stats?.flagged ? 'danger' : 'ok', text: stats?.flagged ? `${Math.round(flaggedShare * 100)}% of scans` : 'Clean' }}
        />
        <StatCard
          index={3}
          loading={isLoading}
          label="Average trust score"
          value={stats?.avg_trust ?? '—'}
          caption="100 = no manipulation signals"
          badge={{ tone: (stats?.avg_trust ?? 100) >= 70 ? 'ok' : 'warn', text: (stats?.avg_trust ?? 100) >= 70 ? 'Healthy' : 'Watch' }}
        />
      </div>

      <ProductTable />
    </div>
  )
}
