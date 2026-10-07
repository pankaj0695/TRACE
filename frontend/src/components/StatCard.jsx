import { motion } from 'motion/react'
import { Badge, Skeleton } from './ui'
import { Sparkline } from './Sparkline'

export function StatCard({ label, value, caption, badge, trend, trendTone, loading, index = 0 }) {
  return (
    <motion.article
      className="stat-card"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.06, duration: 0.35, ease: [0.2, 0.7, 0.2, 1] }}
    >
      <header className="stat-head">
        <h3 className="stat-label">{label}</h3>
        {badge && <Badge size="sm" {...badge}>{badge.text}</Badge>}
      </header>
      <p className="stat-value">{loading ? <Skeleton w={96} h={34} /> : value}</p>
      <footer className="stat-foot">
        <span className="stat-caption">{caption}</span>
        {trend && <Sparkline values={trend} tone={trendTone} width={150} height={56} />}
      </footer>
    </motion.article>
  )
}
