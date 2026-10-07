import { SearchX, Star } from 'lucide-react'
import { motion } from 'motion/react'
import { useReviewSearch } from '../../api/queries'
import { Empty, Meter, Skeleton } from '../../components/ui'
import { navigate } from '../../hooks/useHashRoute'
import { date } from '../../lib/format'
import { ProductThumb } from '../console/ProductTable'

export function SearchPage({ query }) {
  const { data, isLoading, isFetching } = useReviewSearch(query)

  return (
    <div className="page">
      <p className="eyebrow">Review search · TF-IDF recall + semantic re-rank</p>
      <div className="page-head">
        <h1 className="page-title">“{query}”</h1>
        <span className="muted">{isFetching ? 'Searching…' : `${data?.length ?? 0} matching reviews`}</span>
      </div>

      <section className="table-card">
        {isLoading && (
          <div className="waiting">
            {Array.from({ length: 5 }, (_, i) => (
              <Skeleton key={i} h={56} />
            ))}
          </div>
        )}
        {data?.length === 0 && (
          <Empty icon={SearchX} title="No reviews match">
            Try describing the complaint or phrase in different words.
          </Empty>
        )}
        <ul className="results">
          {data?.map((hit, i) => (
            <motion.li
              key={hit.review.id}
              className="result"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: Math.min(i, 10) * 0.03 }}
              onClick={() => navigate.product(hit.review.product_id)}
            >
              {hit.product && <ProductThumb product={hit.product} size={48} />}
              <div className="result-body">
                <div className="result-top">
                  <span className="listing-title">{hit.product?.title ?? hit.review.product_id}</span>
                  <span className="result-score">
                    <Meter value={hit.score} /> {hit.score.toFixed(2)}
                  </span>
                </div>
                <p className="result-text">
                  {hit.review.title && <strong>{hit.review.title}. </strong>}
                  {hit.review.text}
                </p>
                <span className="listing-meta">
                  <Star size={12} aria-hidden /> {hit.review.rating} · {date(new Date(hit.review.ts).toISOString())} ·{' '}
                  {hit.review.verified ? 'verified' : 'unverified'} · {hit.product?.store ?? 'unknown seller'}
                </span>
              </div>
            </motion.li>
          ))}
        </ul>
      </section>
    </div>
  )
}
