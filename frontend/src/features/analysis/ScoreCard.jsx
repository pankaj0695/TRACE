import { Flag } from 'lucide-react'
import { motion } from 'motion/react'
import { Badge, Meter, Skeleton, TierBadge } from '../../components/ui'
import { AGENTS, TIER, riskTone } from '../../lib/format'

const R = 78
const ARC = Math.PI * R

export function ScoreCard({ analysis, running }) {
  if (!analysis) {
    return (
      <section className="score-card">
        <p className="panel-title">Trust score</p>
        <Skeleton w={180} h={96} />
        <p className="muted">{running ? 'Agents are gathering evidence…' : 'No analysis yet.'}</p>
      </section>
    )
  }
  const { trust_score, risk_score, tier, weights, needs_manual_review, conflict } = analysis.assessment
  const tone = TIER[tier]?.tone ?? 'neutral'

  return (
    <section className={`score-card ${running ? 'is-stale' : ''}`}>
      <header className="panel-head">
        <h2 className="panel-title">Trust score</h2>
        <TierBadge tier={tier} />
      </header>

      <div className="gauge">
        <svg viewBox="0 0 180 100" role="img" aria-label={`Trust score ${Math.round(trust_score)} of 100`}>
          <path d={`M12,90 A${R},${R} 0 0 1 168,90`} className="gauge-track" />
          <motion.path
            d={`M12,90 A${R},${R} 0 0 1 168,90`}
            className={`gauge-fill gauge-${tone}`}
            strokeDasharray={ARC}
            initial={{ strokeDashoffset: ARC }}
            animate={{ strokeDashoffset: ARC * (1 - trust_score / 100) }}
            transition={{ duration: 0.9, ease: [0.2, 0.7, 0.2, 1] }}
          />
        </svg>
        <div className="gauge-value">
          <span className="gauge-number">{Math.round(trust_score)}</span>
          <span className="gauge-caption">risk {Math.round(risk_score)} / 100</span>
        </div>
      </div>

      {needs_manual_review && (
        <Badge tone="warn" icon={Flag}>
          {conflict ? 'Detectors disagree · manual review' : 'Manual review recommended'}
        </Badge>
      )}

      <dl className="weights">
        {Object.entries(analysis.signals)
          .filter(([name]) => name in weights)
          .map(([name, s]) => (
            <div key={name} className="weight-row">
              <dt>{AGENTS[name].label}</dt>
              <dd>
                <Meter value={s.risk} tone={riskTone(s.risk)} />
                <span className="weight-num">{Math.round(s.risk * 100)}</span>
              </dd>
            </div>
          ))}
      </dl>
      <p className="fine">Bars show each detector's risk; weights scale with its confidence.</p>
    </section>
  )
}
