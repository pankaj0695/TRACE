import { ArrowLeft, RefreshCw, Star, TriangleAlert } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useState } from 'react'
import { useLatestAnalysis, useProduct } from '../../api/queries'
import { Button, Empty, Skeleton } from '../../components/ui'
import { useAnalysisRun } from '../../hooks/useAnalysisRun'
import { compact } from '../../lib/format'
import { ProductThumb } from '../console/ProductTable'
import { AgentPipeline } from './AgentPipeline'
import { LanguageTab } from './LanguageTab'
import { NetworkTab } from './NetworkTab'
import { ReportTab } from './ReportTab'
import { ScoreCard } from './ScoreCard'
import { SignalsTab } from './SignalsTab'
import { stageState } from './stages'

const TABS = [
  { id: 'report', label: 'Report' },
  { id: 'signals', label: 'Signals' },
  { id: 'network', label: 'Reviewer graph' },
  { id: 'language', label: 'Language' },
]

function TabPanel({ tab, analysis }) {
  switch (tab) {
    case 'signals':
      return <SignalsTab analysis={analysis} />
    case 'network':
      return <NetworkTab signal={analysis.signals.network} />
    case 'language':
      return <LanguageTab signal={analysis.signals.authenticity} />
    default:
      return <ReportTab analysis={analysis} />
  }
}

export function AnalysisPage({ productId }) {
  const { data: product, isError } = useProduct(productId)
  const { data: analysis, isLoading } = useLatestAnalysis(productId)
  const run = useAnalysisRun(productId)
  const [tab, setTab] = useState('report')
  const running = run.status === 'running'
  const { start } = run

  useEffect(() => {
    if (!isLoading && analysis === null && run.status === 'idle') start()
  }, [isLoading, analysis, run.status, start])

  if (isError) {
    return (
      <div className="page">
        <Empty icon={TriangleAlert} title="Listing not found">
          <a href="#/">Back to the console</a>
        </Empty>
      </div>
    )
  }

  return (
    <div className="page">
      <a href="#/" className="back-link">
        <ArrowLeft size={18} aria-hidden /> Console
      </a>
      <p className="eyebrow">Listing · {productId}</p>

      <header className="listing-head">
        {product ? <ProductThumb product={product} size={96} /> : <Skeleton w={96} h={96} />}
        <div className="listing-head-text">
          <h1 className="listing-name" title={product?.title}>{product?.title ?? <Skeleton w="60%" h={28} />}</h1>
          {product && (
            <div className="chips">
              <span className="chip">{product.store ?? 'Unknown seller'}</span>
              <span className="chip">{compact(product.review_count)} reviews in scope</span>
              <span className="chip">
                <Star size={14} aria-hidden /> {product.avg_rating ?? '—'} ({compact(product.rating_count)} ratings)
              </span>
              {product.price && <span className="chip">${product.price.toFixed(2)}</span>}
            </div>
          )}
        </div>
        <Button variant="primary" icon={RefreshCw} onClick={start} disabled={running}>
          {running ? 'Analysing…' : analysis ? 'Re-run analysis' : 'Run analysis'}
        </Button>
      </header>

      {run.status === 'error' && (
        <div className="callout callout-danger" role="alert">
          <TriangleAlert size={18} aria-hidden />
          <p>{run.error}</p>
          <button className="text-btn" onClick={start}>Retry</button>
        </div>
      )}

      <div className="analysis-grid">
        <div className="analysis-side">
          <ScoreCard analysis={analysis} running={running} />
          <AgentPipeline stages={stageState(run, analysis)} running={running} />
        </div>

        <section className="workspace">
          <div className="tabs" role="tablist">
            {TABS.map((t) => (
              <button key={t.id} role="tab" aria-selected={tab === t.id} className="tab" onClick={() => setTab(t.id)}>
                {t.label}
                {tab === t.id && <motion.span layoutId="tab-underline" className="tab-underline" />}
              </button>
            ))}
          </div>
          <div className={`workspace-body ${running && analysis ? 'is-stale' : ''}`}>
            {analysis ? (
              <AnimatePresence mode="wait">
                <motion.div
                  key={tab}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -4 }}
                  transition={{ duration: 0.2 }}
                >
                  <TabPanel tab={tab} analysis={analysis} />
                </motion.div>
              </AnimatePresence>
            ) : (
              <div className="waiting">
                <Skeleton w="70%" h={28} />
                <Skeleton w="95%" />
                <Skeleton w="88%" />
                <Skeleton w="40%" />
                <p className="muted">The orchestrator is routing this listing through the detection agents. Results stream in as each agent finishes.</p>
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  )
}
