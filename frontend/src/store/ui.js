import { create } from 'zustand'

export const PAGE_SIZE = 12

/** Console view preferences survive navigation to a listing and back. */
export const useConsoleFilters = create((set) => ({
  q: '',
  tier: '',
  sort: 'risk',
  page: 0,
  setQuery: (q) => set({ q, page: 0 }),
  setTier: (tier) => set({ tier, page: 0 }),
  setSort: (sort) => set({ sort, page: 0 }),
  setPage: (page) => set({ page }),
}))

export const useSearchMode = create((set) => ({
  mode: 'products',
  setMode: (mode) => set({ mode }),
}))
