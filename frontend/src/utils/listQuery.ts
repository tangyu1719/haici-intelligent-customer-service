export type SortOrder = 'asc' | 'desc'

export interface ListQueryState {
  page: number
  size: number
  sortBy: string
  sortOrder: SortOrder
  keyword: string
  dateFrom: string
  dateTo: string
  id: string
  name: string
}

export interface PageResult<T> {
  total: number
  page: number
  size: number
  items: T[]
}

export function defaultListQuery(size = 20): ListQueryState {
  return {
    page: 1,
    size,
    sortBy: '',
    sortOrder: 'desc',
    keyword: '',
    dateFrom: '',
    dateTo: '',
    id: '',
    name: '',
  }
}

export function toSearchParams(q: ListQueryState, extras?: Record<string, string | number | undefined | null>): string {
  const p = new URLSearchParams()
  p.set('page', String(q.page))
  p.set('size', String(q.size))
  if (q.sortBy) p.set('sort_by', q.sortBy)
  if (q.sortOrder) p.set('sort_order', q.sortOrder)
  if (q.keyword.trim()) p.set('keyword', q.keyword.trim())
  if (q.dateFrom) p.set('date_from', q.dateFrom)
  if (q.dateTo) p.set('date_to', q.dateTo)
  if (q.id.trim()) p.set('id', q.id.trim())
  if (q.name.trim()) p.set('name', q.name.trim())
  if (extras) {
    Object.entries(extras).forEach(([k, v]) => {
      if (v !== undefined && v !== null && String(v).trim() !== '') p.set(k, String(v))
    })
  }
  return p.toString()
}

export function resetPage(q: ListQueryState): ListQueryState {
  return { ...q, page: 1 }
}
