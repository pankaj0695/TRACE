import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation } from 'd3-force'
import { Share2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Empty } from '../../components/ui'
import { navigate } from '../../hooks/useHashRoute'

const W = 760
const H = 520

function layout(graph) {
  const nodes = graph.nodes.map((n) => ({ ...n }))
  const links = graph.links.map((l) => ({ ...l }))
  const sim = forceSimulation(nodes)
    .force('link', forceLink(links).id((d) => d.id).distance((l) => (l.kind === 'co_review' ? 40 : 70)).strength(0.4))
    .force('charge', forceManyBody().strength(-45).distanceMax(220))
    .force('collide', forceCollide(11))
    .force('center', forceCenter(W / 2, H / 2))
    .stop()
  for (let i = 0; i < 260; i++) sim.tick()

  const pad = 20
  const xs = nodes.map((n) => n.x)
  const ys = nodes.map((n) => n.y)
  const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)]
  const scale = Math.min((W - 2 * pad) / (maxX - minX || 1), (H - 2 * pad) / (maxY - minY || 1), 1.6)
  const [offX, offY] = [(W - (maxX - minX) * scale) / 2, (H - (maxY - minY) * scale) / 2]
  nodes.forEach((n) => ((n.x = offX + (n.x - minX) * scale), (n.y = offY + (n.y - minY) * scale)))
  return { nodes, links }
}

const nodeClass = (n) =>
  n.kind === 'target'
    ? 'node-target'
    : n.kind === 'product'
      ? n.same_store ? 'node-store' : 'node-product'
      : n.ring ? 'node-ring' : n.loyal ? 'node-loyal' : 'node-reviewer'

function describe(n) {
  if (n.kind === 'reviewer') {
    const flags = [n.ring && 'co-review ring', n.loyal && 'seller-loyal'].filter(Boolean).join(', ')
    return { title: `Reviewer ${n.id.slice(0, 10)}…`, body: `${n.degree} review(s) in graph${flags ? ` · ${flags}` : ''}` }
  }
  return { title: n.title ?? n.id, body: n.kind === 'target' ? 'Listing under review' : n.same_store ? 'Same seller' : n.label }
}

const LEGEND = [
  ['node-target', 'This listing', 'square'],
  ['node-store', 'Same-seller listing', 'square'],
  ['node-product', 'Other listing', 'square'],
  ['node-ring', 'Ring member', 'circle'],
  ['node-loyal', 'Seller-loyal reviewer', 'circle'],
  ['node-reviewer', 'Reviewer', 'circle'],
]

export function NetworkTab({ signal }) {
  const graph = signal?.artifacts?.graph
  const { nodes, links } = useMemo(() => (graph ? layout(graph) : { nodes: [], links: [] }), [graph])
  const [hover, setHover] = useState(null)

  if (!graph || nodes.length <= 1) return <Empty icon={Share2} title="No reviewer graph">These reviewers have no other activity in the dataset.</Empty>
  const m = signal.metrics
  const ring = signal.findings.find((f) => f.code === 'review_ring')

  return (
    <div className="network">
      <figure className="graph-frame" onMouseLeave={() => setHover(null)}>
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Reviewer network graph">
          {links.map((l, i) => (
            <line
              key={i}
              x1={l.source.x} y1={l.source.y} x2={l.target.x} y2={l.target.y}
              className={l.kind === 'co_review' ? 'link link-ring' : 'link'}
            />
          ))}
          {nodes.map((n) => {
            const size = n.kind === 'target' ? 22 : n.kind === 'product' ? 12 : 9
            const common = {
              className: `node ${nodeClass(n)} ${hover?.id === n.id ? 'node-hover' : ''}`,
              onMouseEnter: () => setHover(n),
              onClick: n.kind === 'product' ? () => navigate.product(n.id) : undefined,
            }
            return n.kind === 'reviewer' ? (
              <circle key={n.id} cx={n.x} cy={n.y} r={size / 2 + 1} {...common} />
            ) : (
              <rect key={n.id} x={n.x - size / 2} y={n.y - size / 2} width={size} height={size} {...common} />
            )
          })}
        </svg>
        {hover && (
          <div className="tooltip graph-tip" style={{ left: `${(hover.x / W) * 100}%`, top: `${(hover.y / H) * 100}%` }}>
            <strong>{describe(hover).title}</strong>
            <span>{describe(hover).body}</span>
          </div>
        )}
        <figcaption className="legend">
          {LEGEND.map(([cls, label, shape]) => (
            <span key={cls} className="legend-item">
              <i className={`legend-mark legend-${shape} ${cls}`} /> {label}
            </span>
          ))}
          {graph.truncated && <span className="muted">· showing the most connected reviewers</span>}
        </figcaption>
      </figure>

      <aside className="graph-facts">
        <dl className="kv-stack">
          <div><dt>Graph backend</dt><dd>{m.graph_backend}</dd></div>
          <div><dt>Reviewers</dt><dd>{m.reviewers}</dd></div>
          <div><dt>Active elsewhere</dt><dd>{m.multi_product_reviewers}</dd></div>
          <div><dt>Co-review pairs</dt><dd>{m.co_review_pairs}</dd></div>
          <div><dt>Rings (≥3 accounts)</dt><dd>{m.rings}</dd></div>
          <div><dt>Seller-loyal</dt><dd>{m.seller_loyal}</dd></div>
          <div><dt>New-account cohort</dt><dd>{m.new_account_cohort}</dd></div>
        </dl>
        {ring && (
          <div className="ring-list">
            <h3 className="block-title">Largest ring</h3>
            <ul>
              {ring.evidence.rings[0].map((id) => (
                <li key={id}>{id}</li>
              ))}
            </ul>
          </div>
        )}
        <p className="fine">Squares are listings, circles are reviewers. Dashed red lines join reviewers who co-reviewed other listings. Click a listing to open it.</p>
      </aside>
    </div>
  )
}
