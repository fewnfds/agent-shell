import { computed, ref } from 'vue'

import type {
  DataTableAppliedQuery,
  DataTableConfig,
  DataTableFilter,
  DataTableFilterValue,
  DataTableRequest,
} from '@/components/data-table/types'
import { matchesSearchText } from '@/utils/search'

function cloneValue(value: DataTableFilterValue): DataTableFilterValue {
  return Array.isArray(value) ? [...value] : value
}

function initialFilterValue<Row>(filter: DataTableFilter<Row>): DataTableFilterValue {
  if (filter.kind === 'multi') return [...(filter.initialValue ?? [])]
  return filter.initialValue ?? ''
}

function initialFilters<Row>(filters: readonly DataTableFilter<Row>[]): Record<string, DataTableFilterValue> {
  return Object.fromEntries(filters.map((filter) => [filter.key, initialFilterValue(filter)]))
}

function cloneFilters(filters: Record<string, DataTableFilterValue>): Record<string, DataTableFilterValue> {
  return Object.fromEntries(Object.entries(filters).map(([key, value]) => [key, cloneValue(value)]))
}

function normalizedFilters(filters: Record<string, DataTableFilterValue>): Record<string, DataTableFilterValue> {
  return Object.fromEntries(Object.entries(filters).map(([key, value]) => [
    key,
    Array.isArray(value)
      ? [...new Set(value.map((item) => item.trim()).filter(Boolean))]
      : value.trim(),
  ]))
}

function activeValue(value: DataTableFilterValue): boolean {
  return Array.isArray(value) ? value.length > 0 : Boolean(value)
}

function rowFilterMatches<Row>(
  row: Row,
  filter: DataTableFilter<Row>,
  selected: DataTableFilterValue,
): boolean {
  if (!activeValue(selected)) return true
  if (!filter.values) return true
  const raw = filter.values(row)
  const values = Array.isArray(raw) ? raw.map(String) : [String(raw)]
  if (filter.kind === 'text') return matchesSearchText(String(selected), values)
  if (filter.kind === 'single' || filter.kind === 'datetime') {
    return values.includes(String(selected))
  }
  return (selected as string[]).some((value) => values.includes(value))
}

export function useDataTable<Row>(config: DataTableConfig<Row>) {
  const filters = config.filters ?? []
  const defaults = initialFilters(filters)
  const draftQuery = ref('')
  const draftFilters = ref<Record<string, DataTableFilterValue>>(cloneFilters(defaults))
  const appliedQuery = ref('')
  const appliedFilters = ref<Record<string, DataTableFilterValue>>(cloneFilters(defaults))
  const page = ref(1)
  const pageSize = ref(config.pageSize ?? 20)
  const remoteRows = ref<Row[]>([])
  const loadedLocalRows = ref<Row[]>([])
  const remoteTotal = ref(0)
  const queryValidationError = ref('')
  const loading = ref(false)
  const loadError = ref<unknown | null>(null)
  let requestSequence = 0

  const applied = computed<DataTableAppliedQuery>(() => ({
    query: appliedQuery.value,
    filters: cloneFilters(appliedFilters.value),
  }))

  const hasAppliedFilters = computed(() => (
    Boolean(appliedQuery.value)
    || Object.values(appliedFilters.value).some(activeValue)
  ))

  const localFilteredRows = computed<Row[]>(() => {
    if (config.provider.mode !== 'local') return []
    const source = config.provider.rows ? config.provider.rows() : loadedLocalRows.value
    return source.filter((row) => {
      if (appliedQuery.value && config.search?.values
        && !matchesSearchText(appliedQuery.value, config.search.values(row))) return false
      return filters.every((filter) => rowFilterMatches(
        row,
        filter,
        appliedFilters.value[filter.key] ?? initialFilterValue(filter),
      ))
    })
  })

  const total = computed(() => config.provider.mode === 'local'
    ? localFilteredRows.value.length
    : remoteTotal.value)

  const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))

  const rows = computed<Row[]>(() => {
    if (config.provider.mode !== 'local') return remoteRows.value
    const start = (page.value - 1) * pageSize.value
    return localFilteredRows.value.slice(start, start + pageSize.value)
  })

  function request(): DataTableRequest {
    return {
      ...applied.value,
      page: page.value,
      pageSize: pageSize.value,
    }
  }

  async function reload(): Promise<void> {
    if (config.provider.mode === 'local') {
      const provider = config.provider
      if (!provider.load) {
        page.value = Math.min(page.value, totalPages.value)
        loadError.value = null
        return
      }
      const sequence = ++requestSequence
      loading.value = true
      loadError.value = null
      try {
        const loaded = await provider.load()
        if (sequence !== requestSequence) return
        loadedLocalRows.value = [...loaded]
        page.value = Math.min(page.value, totalPages.value)
      } catch (error) {
        if (sequence === requestSequence) loadError.value = error
      } finally {
        if (sequence === requestSequence) loading.value = false
      }
      return
    }
    const provider = config.provider
    const sequence = ++requestSequence
    loading.value = true
    loadError.value = null
    try {
      const result = await provider.load(request())
      if (sequence !== requestSequence) return
      remoteRows.value = result.rows
      remoteTotal.value = result.total
      const boundedPage = Math.min(page.value, totalPages.value)
      if (boundedPage !== page.value) {
        page.value = boundedPage
        await reload()
      }
    } catch (error) {
      if (sequence === requestSequence) loadError.value = error
    } finally {
      if (sequence === requestSequence) loading.value = false
    }
  }

  function resetPage(): void {
    page.value = 1
  }

  async function apply(): Promise<boolean> {
    const nextApplied: DataTableAppliedQuery = {
      query: draftQuery.value.trim(),
      filters: normalizedFilters(draftFilters.value),
    }
    queryValidationError.value = config.validateQuery?.(nextApplied) ?? ''
    if (queryValidationError.value) return false
    appliedQuery.value = nextApplied.query
    appliedFilters.value = nextApplied.filters
    resetPage()
    await reload()
    return true
  }

  async function reset(): Promise<void> {
    draftQuery.value = ''
    draftFilters.value = cloneFilters(defaults)
    appliedQuery.value = ''
    appliedFilters.value = cloneFilters(defaults)
    queryValidationError.value = ''
    resetPage()
    await reload()
  }

  async function setQuery(value: Partial<DataTableAppliedQuery>): Promise<boolean> {
    draftQuery.value = value.query ?? appliedQuery.value
    draftFilters.value = value.filters !== undefined
      ? { ...cloneFilters(appliedFilters.value), ...cloneFilters(value.filters) }
      : cloneFilters(appliedFilters.value)
    return apply()
  }

  function updateFilter(key: string, value: DataTableFilterValue): void {
    draftFilters.value = { ...draftFilters.value, [key]: cloneValue(value) }
  }

  async function changePage(target: number): Promise<void> {
    const bounded = Math.max(1, Math.trunc(target))
    if (bounded > totalPages.value) return
    if (bounded === page.value) return
    page.value = bounded
    await reload()
  }

  async function changePageSize(value: number): Promise<void> {
    if (!Number.isInteger(value) || value <= 0 || value === pageSize.value) return
    pageSize.value = value
    resetPage()
    await reload()
  }

  async function reloadFirst(): Promise<void> {
    resetPage()
    await reload()
  }

  return {
    applied,
    draftQuery,
    draftFilters,
    hasAppliedFilters,
    loadError,
    loading,
    page,
    pageSize,
    rows,
    matchingRows: localFilteredRows,
    total,
    totalPages,
    queryValidationError,
    apply,
    changePage,
    changePageSize,
    reload,
    reloadFirst,
    reset,
    setQuery,
    updateFilter,
  }
}
