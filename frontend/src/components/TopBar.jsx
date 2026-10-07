import { Bot, CornerDownLeft, Network, Search } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useHealth } from '../api/queries'
import { navigate } from '../hooks/useHashRoute'
import { useConsoleFilters, useSearchMode } from '../store/ui'

const MODES = [
  { value: 'products', label: 'Listings' },
  { value: 'reviews', label: 'Reviews' },
]

export function TopBar({ section, searchQuery }) {
  const { mode, setMode } = useSearchMode()
  const { q, setQuery } = useConsoleFilters()
  const [text, setText] = useState(section === 'search' ? searchQuery ?? '' : mode === 'reviews' ? '' : q)
  const [syncedQuery, setSyncedQuery] = useState(searchQuery)
  const { data: health } = useHealth()

  // Landing on a review-search URL shows that query and scope in the bar.
  if (section === 'search' && searchQuery && searchQuery !== syncedQuery) {
    setSyncedQuery(searchQuery)
    setText(searchQuery)
  }
  useEffect(() => {
    if (section === 'search') setMode('reviews')
  }, [section, setMode])

  useEffect(() => {
    if (mode !== 'products') return
    const id = setTimeout(() => {
      if (text !== q) {
        setQuery(text)
        if (section !== 'console') navigate.console()
      }
    }, 250)
    return () => clearTimeout(id)
  }, [text, mode, q, section, setQuery])

  const submit = (e) => {
    e.preventDefault()
    if (mode === 'reviews' && text.trim().length >= 2) navigate.search(text.trim())
  }

  const switchMode = (next) => {
    setMode(next)
    setText(next === 'reviews' ? searchQuery ?? '' : q)
  }

  return (
    <header className="topbar">
      <a className="brand" href="#/" aria-label="TRACE console home">
        <span className="brand-mark">T</span>
        <span className="brand-name">TRACE</span>
      </a>

      <form className="search" role="search" onSubmit={submit}>
        <Search size={22} aria-hidden />
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={mode === 'products' ? 'Search listings, sellers, ASINs…' : 'Semantic search across every review…'}
          aria-label="Search"
        />
        {mode === 'reviews' && text.trim().length >= 2 && (
          <kbd className="search-hint">
            <CornerDownLeft size={14} aria-hidden /> search
          </kbd>
        )}
        <div className="segmented" role="tablist" aria-label="Search scope">
          {MODES.map((m) => (
            <button key={m.value} type="button" role="tab" aria-selected={mode === m.value} onClick={() => switchMode(m.value)}>
              {m.label}
            </button>
          ))}
        </div>
      </form>

      <div className="topbar-status">
        <span className="engine" title="Knowledge graph backend">
          <Network size={18} aria-hidden /> {health?.graph_backend ?? '…'}
        </span>
        <span className="engine" title="Report model">
          <Bot size={18} aria-hidden />
          <span className={`dot ${health?.llm === 'disabled' ? 'dot-warn' : 'dot-ok'}`} />
          {health ? (health.llm === 'disabled' ? 'rules only' : health.llm) : '…'}
        </span>
        <span className="avatar" aria-label="Signed in as S G">SG</span>
      </div>
    </header>
  )
}
