import { AnimatePresence, motion } from 'motion/react'
import { TopBar } from './components/TopBar'
import { AnalysisPage } from './features/analysis/AnalysisPage'
import { ConsolePage } from './features/console/ConsolePage'
import { SearchPage } from './features/search/SearchPage'
import { useHashRoute } from './hooks/useHashRoute'

export default function App() {
  const { section, id, params } = useHashRoute()
  const key = `${section}:${id ?? params.q ?? ''}`

  return (
    <>
      <TopBar section={section} searchQuery={params.q} />
      <main>
        <AnimatePresence mode="wait">
          <motion.div key={key} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.18 }}>
            {section === 'product' && id ? (
              <AnalysisPage productId={id} />
            ) : section === 'search' && params.q ? (
              <SearchPage query={params.q} />
            ) : (
              <ConsolePage />
            )}
          </motion.div>
        </AnimatePresence>
      </main>
    </>
  )
}
