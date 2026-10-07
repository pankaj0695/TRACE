import { Copy, Quote, Star } from 'lucide-react'
import { Empty } from '../../components/ui'
import { navigate } from '../../hooks/useHashRoute'
import { pct } from '../../lib/format'

export function LanguageTab({ signal }) {
  if (!signal || signal.status !== 'ok') return <Empty icon={Quote} title="Language analysis unavailable" />
  const { metrics: m, artifacts: a } = signal

  return (
    <div className="language">
      <dl className="kv-grid">
        <div><dt>Authenticity score</dt><dd>{Math.round(m.authenticity_score * 100)} / 100</dd></div>
        <div><dt>Near-duplicate share</dt><dd>{pct(m.duplicate_share, 1)}</dd></div>
        <div><dt>Templated / generic</dt><dd>{pct(m.templated_share)}</dd></div>
        <div><dt>Copied from other listings</dt><dd>{pct(m.cross_listing_share, 1)}</dd></div>
      </dl>
      <p className="fine">Near-duplicates use {m.similarity_engine} embeddings; cross-listing copies use the corpus TF-IDF index.</p>

      {a.phrases?.length > 0 && (
        <section>
          <h3 className="block-title">Phrases shared by 3+ reviewers</h3>
          <div className="phrases">
            {a.phrases.map((p) => (
              <span key={p.phrase} className="phrase">
                “{p.phrase}” <b>{p.reviewers}</b>
              </span>
            ))}
          </div>
        </section>
      )}

      <section>
        <h3 className="block-title">Near-duplicate clusters</h3>
        {a.clusters?.length ? (
          <div className="clusters">
            {a.clusters.map((c, i) => (
              <article key={i} className="cluster">
                <header className="cluster-head">
                  <Copy size={16} aria-hidden /> {c.size} reviews from different accounts
                </header>
                {c.reviews.map((r) => (
                  <blockquote key={r.id} className="quote">
                    <p>{r.text}</p>
                    <footer>
                      <Star size={12} aria-hidden /> {r.rating} · {r.date} · {r.user_id.slice(0, 10)}…
                    </footer>
                  </blockquote>
                ))}
              </article>
            ))}
          </div>
        ) : (
          <p className="muted">No clusters — reviewers wrote in their own words.</p>
        )}
      </section>

      {a.copies?.length > 0 && (
        <section>
          <h3 className="block-title">Text reused on other listings</h3>
          <ul className="copies">
            {a.copies.map((c) => (
              <li key={`${c.review_id}-${c.other_review_id}`}>
                <button className="link-btn" onClick={() => navigate.product(c.other_product_id)}>
                  {c.other_title}
                </button>
                <span className="muted">similarity {c.score}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
