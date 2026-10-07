import { useId } from 'react'

/** Single-series trend line with a soft area fill; the card title names the series. */
export function Sparkline({ values, tone = 'ok', width = 200, height = 64 }) {
  const gradient = useId()
  if (!values?.length) return <svg width={width} height={height} aria-hidden />
  const points = values.length === 1 ? [values[0], values[0]] : values
  const max = Math.max(...points, 1)
  const min = Math.min(...points, 0)
  const x = (i) => (i / (points.length - 1)) * (width - 4) + 2
  const y = (v) => height - 4 - ((v - min) / (max - min || 1)) * (height - 10)
  const line = points.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
  const color = `var(--${tone === 'danger' ? 'danger' : 'ok'})`

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="sparkline" aria-hidden>
      <defs>
        <linearGradient id={gradient} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor={color} stopOpacity="0.18" />
          <stop offset="1" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={`${line} L${x(points.length - 1)},${height} L${x(0)},${height} Z`} fill={`url(#${gradient})`} />
      <path d={line} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  )
}
