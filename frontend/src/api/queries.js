import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { api } from './client'

export const keys = {
  health: ['health'],
  stats: ['stats'],
  products: (params) => ['products', params],
  product: (id) => ['product', id],
  analysis: (id) => ['analysis', id],
  search: (q) => ['search', q],
}

export const useHealth = () => useQuery({ queryKey: keys.health, queryFn: api.health, staleTime: 60_000 })

export const useStats = () => useQuery({ queryKey: keys.stats, queryFn: api.stats })

export const useProducts = (params) =>
  useQuery({ queryKey: keys.products(params), queryFn: () => api.products(params), placeholderData: keepPreviousData })

export const useProduct = (id) => useQuery({ queryKey: keys.product(id), queryFn: () => api.product(id), enabled: !!id })

export const useLatestAnalysis = (id) =>
  useQuery({
    queryKey: keys.analysis(id),
    queryFn: () => api.latestAnalysis(id).catch((err) => (err.status === 404 ? null : Promise.reject(err))),
    enabled: !!id,
  })

export const useReviewSearch = (q) =>
  useQuery({ queryKey: keys.search(q), queryFn: () => api.searchReviews(q), enabled: q.trim().length >= 2, placeholderData: keepPreviousData })
