import { AlertTriangle, ChevronDown, CircleHelp, ShieldAlert, ShieldCheck } from 'lucide-react'
import { TIER } from '../lib/format'

const TONE_ICON = { ok: ShieldCheck, warn: AlertTriangle, danger: ShieldAlert, neutral: CircleHelp }

export function Badge({ tone = 'neutral', icon: Icon, children, size }) {
  return (
    <span className={`badge badge-${tone} ${size === 'sm' ? 'badge-sm' : ''}`}>
      {Icon && <Icon size={size === 'sm' ? 13 : 15} strokeWidth={2.2} aria-hidden />}
      {children}
    </span>
  )
}

export function TierBadge({ tier, size }) {
  const meta = TIER[tier] ?? TIER.insufficient_data
  return (
    <Badge tone={meta.tone} icon={TONE_ICON[meta.tone]} size={size}>
      {meta.label}
    </Badge>
  )
}

export function SeverityBadge({ severity }) {
  const tone = { critical: 'danger', high: 'danger', medium: 'warn', low: 'neutral' }[severity]
  return (
    <Badge tone={tone} icon={TONE_ICON[tone]} size="sm">
      {severity[0].toUpperCase() + severity.slice(1)}
    </Badge>
  )
}

export function Button({ variant = 'outline', icon: Icon, children, ...props }) {
  return (
    <button className={`btn btn-${variant}`} {...props}>
      {Icon && <Icon size={18} strokeWidth={2} aria-hidden />}
      {children}
    </button>
  )
}

export function Select({ label, icon: Icon, value, onChange, options }) {
  return (
    <label className="select">
      {Icon && <Icon size={18} aria-hidden />}
      <span className="sr-only">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <ChevronDown size={18} aria-hidden />
    </label>
  )
}

export const Skeleton = ({ w = '100%', h = 16 }) => <span className="skeleton" style={{ width: w, height: h }} />

export function Empty({ icon: Icon, title, children }) {
  return (
    <div className="empty">
      {Icon && <Icon size={28} strokeWidth={1.6} aria-hidden />}
      <p className="empty-title">{title}</p>
      {children && <p className="empty-body">{children}</p>}
    </div>
  )
}

export function Meter({ value, tone = 'ink' }) {
  return (
    <span className="meter" role="meter" aria-valuenow={Math.round(value * 100)} aria-valuemin={0} aria-valuemax={100}>
      <span className={`meter-fill meter-${tone}`} style={{ width: `${Math.max(2, value * 100)}%` }} />
    </span>
  )
}
