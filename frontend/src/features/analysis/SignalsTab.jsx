import { useState } from 'react'
import { Meter } from '../../components/ui'
import { AGENTS, pct, riskTone } from '../../lib/format'

const EVIDENCE_LABEL = {
  volume_spike: 'Volume burst',
  rating_skew: 'Five-star skew',
  spike_rating_shift: 'Burst rating shift',
  unverified: 'Unverified purchases',
  duplicates: 'Near-duplicate text',
  cross_listing: 'Copied across listings',
  templated: 'Templated language',
  review_rings: 'Co-review rings',
  seller_loyal: 'Seller-loyal accounts',
  new_account_cohort: 'New-account cohort',
}

const WINDOW = 104

function burstWindow(weekly, peakStart) {
  if (weekly.length <= WINDOW) return weekly
  const peakIndex = Math.max(0, weekly.findIndex((w) => w.week >= peakStart.slice(0, 10)) - 1)
  const start = Math.min(Math.max(0, peakIndex - WINDOW / 2), weekly.length - WINDOW)
  return weekly.slice(start, start + WINDOW)
}

function VolumeChart({ weekly, peak }) {
  const [hover, setHover] = useState(null)
  const data = burstWindow(weekly, peak.start)
  const max = Math.max(...data.map((d) => d.count), 1)
  const W = 720
  const H = 180
  const gap = 2
  const bar = Math.max(1, (W - gap * data.length) / data.length)
  const WEEK = 7 * 86_400_000
  const [peakStart, peakEnd] = [Date.parse(peak.start), Date.parse(peak.end)]
  const overlapsPeak = (week) => Date.parse(week) <= peakEnd && Date.parse(week) + WEEK > peakStart

  return (
    <figure className="chart">
      <figcaption className="chart-caption">
        Weekly review volume{data.length < weekly.length ? ' · 2 years around the burst' : ''}
        <span className="legend-item">
          <i className="swatch swatch-danger" /> contains the 7-day burst
        </span>
      </figcaption>
      <div className="chart-frame" onMouseLeave={() => setHover(null)}>
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="chart-svg" role="img" aria-label="Weekly review volume">
          {[0.5, 1].map((t) => (
            <line key={t} x1="0" x2={W} y1={H - t * (H - 8)} y2={H - t * (H - 8)} className="gridline" />
          ))}
          {data.map((d, i) => {
            const h = Math.max(d.count ? 2 : 0, (d.count / max) * (H - 8))
            const hot = overlapsPeak(d.week)
            return (
              <g key={d.week} onMouseEnter={() => setHover({ ...d, i })}>
                <rect x={i * (bar + gap)} y={0} width={bar + gap} height={H} fill="transparent" />
                <rect x={i * (bar + gap)} y={H - h} width={bar} height={h} className={hot ? 'bar bar-hot' : hover?.i === i ? 'bar bar-hover' : 'bar'} />
              </g>
            )
          })}
        </svg>
        {hover && (
          <div className="tooltip" style={{ left: `${((hover.i + 0.5) / data.length) * 100}%` }}>
            <strong>{hover.count}</strong> reviews
            <span>week of {hover.week}</span>
          </div>
        )}
        <div className="chart-axis">
          <span>{data[0]?.week}</span>
          <span>peak {max}/wk</span>
          <span>{data.at(-1)?.week}</span>
        </div>
      </div>
    </figure>
  )
}

function RatingBars({ ratings, baselineFive }) {
  const total = Object.values(ratings).reduce((a, b) => a + b, 0) || 1
  return (
    <figure className="chart">
      <figcaption className="chart-caption">Rating distribution</figcaption>
      <ul className="rating-bars">
        {['5', '4', '3', '2', '1'].map((star) => {
          const share = ratings[star] / total
          return (
            <li key={star} title={`${ratings[star]} reviews`}>
              <span className="rating-label">{star}★</span>
              <span className="rating-track">
                <span className="rating-fill" style={{ width: `${share * 100}%` }} />
                {star === '5' && <span className="rating-baseline" style={{ left: `${baselineFive * 100}%` }} title="Category baseline" />}
              </span>
              <span className="rating-value">{pct(share)}</span>
            </li>
          )
        })}
      </ul>
      <p className="fine">Marker on 5★ = category baseline ({pct(baselineFive)}).</p>
    </figure>
  )
}

function EvidenceCard({ name, signal }) {
  const evidence = signal.metrics?.evidence ?? {}
  return (
    <article className="evidence-card">
      <header className="evidence-head">
        <h3>{AGENTS[name].label}</h3>
        <span className="muted">
          risk {Math.round(signal.risk * 100)} · confidence {pct(signal.confidence)}
        </span>
      </header>
      {signal.status === 'failed' ? (
        <p className="error-text">Agent failed: {signal.error}</p>
      ) : (
        <dl className="evidence-list">
          {Object.entries(evidence).map(([key, value]) => (
            <div key={key}>
              <dt>{EVIDENCE_LABEL[key] ?? key}</dt>
              <dd>
                <Meter value={value} tone={riskTone(value)} />
              </dd>
            </div>
          ))}
        </dl>
      )}
    </article>
  )
}

export function SignalsTab({ analysis }) {
  const anomaly = analysis.signals.anomaly
  const m = anomaly?.metrics ?? {}
  return (
    <div className="signals">
      {anomaly?.artifacts?.weekly && (
        <div className="chart-row">
          <VolumeChart weekly={anomaly.artifacts.weekly} peak={anomaly.artifacts.peak} />
          <RatingBars ratings={anomaly.artifacts.ratings} baselineFive={anomaly.artifacts.baseline_five_star} />
        </div>
      )}
      {anomaly?.status === 'ok' && (
        <dl className="kv-grid">
          <div><dt>Peak 7 days</dt><dd>{m.peak_7d} reviews</dd></div>
          <div><dt>Weekly baseline</dt><dd>{m.baseline_per_week}</dd></div>
          <div><dt>Burst ratio</dt><dd>{m.spike_ratio}×</dd></div>
          <div><dt>Busiest day</dt><dd>{m.busiest_day} ({m.busiest_day_count})</dd></div>
          <div><dt>Verified</dt><dd>{pct(m.verified_rate)}</dd></div>
          <div><dt>Unverified in burst</dt><dd>{pct(m.unverified_in_peak)}</dd></div>
        </dl>
      )}
      <div className="evidence-grid">
        {['anomaly', 'authenticity', 'network'].map((name) =>
          analysis.signals[name] ? <EvidenceCard key={name} name={name} signal={analysis.signals[name]} /> : null,
        )}
      </div>
    </div>
  )
}
