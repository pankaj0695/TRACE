import { ArrowRight, ChevronLeft, ChevronRight, PackageSearch, Star } from 'lucide-react'
import { useState } from 'react'
import { useProducts } from '../../api/queries'
import { Empty, Skeleton, TierBadge } from '../../components/ui'
import { navigate } from '../../hooks/useHashRoute'
import { compact, relative } from '../../lib/format'
import { PAGE_SIZE, useConsoleFilters } from '../../store/ui'

export function ProductThumb({ product, size = 52 }) {
  const [broken, setBroken] = useState(false)
  return (
    <span className="thumb" style={{ width: size, height: size }}>
      {product.image_url && !broken ? (
        <img src={product.image_url} alt="" loading="lazy" onError={() => setBroken(true)} />
      ) : (
        product.title.slice(0, 1)
      )}
    </span>
  )
}

export function ProductTable() {
  const { q, tier, sort, page, setPage } = useConsoleFilters()
  const { data, isLoading, isFetching } = useProducts({ q, tier, sort, limit: PAGE_SIZE, offset: page * PAGE_SIZE })
  const total = data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <section className="table-card" aria-busy={isFetching}>
      <header className="table-card-head">
        <div>
          <h2 className="section-title">Monitored listings</h2>
          <p className="section-sub">{isLoading ? 'Loading…' : `${total} listings · sorted by ${sort === 'risk' ? 'risk' : sort}`}</p>
        </div>
      </header>

      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th>Listing</th>
              <th className="num">Reviews</th>
              <th className="num">Burst</th>
              <th className="num">Rating</th>
              <th>Risk</th>
              <th>Last scan</th>
              <th aria-label="Open" />
            </tr>
          </thead>
          <tbody>
            {isLoading &&
              Array.from({ length: 6 }, (_, i) => (
                <tr key={i}>
                  <td colSpan={7}>
                    <Skeleton h={40} />
                  </td>
                </tr>
              ))}
            {data?.items.map(({ product, scan }) => (
              <tr key={product.id} className="row-link" onClick={() => navigate.product(product.id)}>
                <td>
                  <div className="listing-cell">
                    <ProductThumb product={product} />
                    <div className="listing-text">
                      <a href={`#/product/${product.id}`} className="listing-title" onClick={(e) => e.stopPropagation()}>
                        {product.title}
                      </a>
                      <span className="listing-meta">
                        {product.store ?? 'Unknown seller'} · {product.id}
                      </span>
                    </div>
                  </div>
                </td>
                <td className="num">{compact(product.review_count)}</td>
                <td className="num">
                  <span className={product.spike_ratio >= 10 ? 'burst burst-hot' : 'burst'}>{product.spike_ratio.toFixed(1)}×</span>
                </td>
                <td className="num">
                  <span className="rating">
                    <Star size={14} aria-hidden /> {product.avg_rating?.toFixed(1) ?? '—'}
                  </span>
                </td>
                <td>
                  {scan ? (
                    <span className="risk-cell">
                      <TierBadge tier={scan.tier} size="sm" />
                      <span className="risk-num">{Math.round(scan.risk_score)}</span>
                    </span>
                  ) : (
                    <span className="muted">Not scanned</span>
                  )}
                </td>
                <td className="muted">{relative(scan?.created_at)}</td>
                <td className="row-action">
                  <ArrowRight size={18} aria-hidden />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!isLoading && total === 0 && (
          <Empty icon={PackageSearch} title="No listings match">
            Try a different search or clear the risk filter.
          </Empty>
        )}
      </div>

      <footer className="pager">
        <span className="muted">
          Page {page + 1} of {pages}
        </span>
        <div className="pager-buttons">
          <button className="icon-btn" disabled={page === 0} onClick={() => setPage(page - 1)} aria-label="Previous page">
            <ChevronLeft size={18} />
          </button>
          <button className="icon-btn" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)} aria-label="Next page">
            <ChevronRight size={18} />
          </button>
        </div>
      </footer>
    </section>
  )
}
