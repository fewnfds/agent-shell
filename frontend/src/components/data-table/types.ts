import type { ConfirmationRequest } from '@/composables/useConfirmation'

type DataTableText = string | (() => string)
export type DataTableFilterValue = string | string[]

export interface DataTableAppliedQuery {
  query: string
  filters: Record<string, DataTableFilterValue>
}

export interface DataTableRequest extends DataTableAppliedQuery {
  page: number
  pageSize: number
}

interface DataTableNumberedResult<Row> {
  rows: Row[]
  total: number
}

interface DataTableLocalProvider<Row> {
  mode: 'local'
  rows?: () => readonly Row[]
  load?: () => Promise<readonly Row[]>
}

interface DataTableNumberedProvider<Row> {
  mode: 'numbered'
  load: (request: DataTableRequest) => Promise<DataTableNumberedResult<Row>>
}

type DataTableProvider<Row> =
  | DataTableLocalProvider<Row>
  | DataTableNumberedProvider<Row>

interface DataTableColumn<Row> {
  key: string
  label: DataTableText
  value: (row: Row) => unknown
}

interface DataTableSearch<Row> {
  label: DataTableText
  placeholder: DataTableText
  values?: (row: Row) => readonly string[]
}

interface DataTableFilterOption {
  value: string
  label: DataTableText
}

interface DataTableFilterBase<Row> {
  key: string
  label: DataTableText
  values?: (row: Row) => string | readonly string[]
}

interface DataTableTextFilter<Row> extends DataTableFilterBase<Row> {
  kind: 'text'
  placeholder?: DataTableText
  initialValue?: string
}

interface DataTableDateTimeFilter<Row> extends DataTableFilterBase<Row> {
  kind: 'datetime'
  initialValue?: string
}

interface DataTableSingleFilter<Row> extends DataTableFilterBase<Row> {
  kind: 'single'
  options: readonly DataTableFilterOption[]
  initialValue?: string
}

interface DataTableMultiFilter<Row> extends DataTableFilterBase<Row> {
  kind: 'multi'
  options: readonly DataTableFilterOption[]
  initialValue?: readonly string[]
}

export type DataTableFilter<Row> =
  | DataTableTextFilter<Row>
  | DataTableDateTimeFilter<Row>
  | DataTableSingleFilter<Row>
  | DataTableMultiFilter<Row>

type DataTableActionTone = 'primary' | 'secondary' | 'info' | 'success' | 'warning' | 'danger'
export type DataTableActionIcon = 'activate' | 'copy' | 'delete' | 'download' | 'edit' | 'view'

export interface DataTableRowAction<Row> {
  key: string
  label: DataTableText | ((row: Row) => string)
  busyLabel?: DataTableText
  tone: DataTableActionTone
  icon: DataTableActionIcon
  visible?: (row: Row) => boolean
  disabled?: (row: Row) => boolean
  confirm?: (row: Row) => ConfirmationRequest
  run: (row: Row) => Promise<unknown> | unknown
  successTitle?: DataTableText
  failureTitle?: DataTableText
  failureMessageKey?: string
  reloadAfter?: false | 'current' | 'first'
}

export interface DataTableBulkContext<Row> {
  applied: DataTableAppliedQuery
  matchingRows: readonly Row[]
  visibleRows: readonly Row[]
  total: number
  hasAppliedFilters: boolean
}

interface DataTableBulkAction<Row> {
  label: DataTableText
  busyLabel?: DataTableText
  icon: DataTableActionIcon
  enabled: (context: DataTableBulkContext<Row>) => boolean
  confirm: (context: DataTableBulkContext<Row>) => ConfirmationRequest
  run: (context: DataTableBulkContext<Row>) => Promise<unknown>
  successTitle?: DataTableText | ((result: unknown) => string)
  failureTitle: DataTableText
  failureMessageKey?: string
}

export interface DataTableConfig<Row> {
  id: string
  ariaLabel: DataTableText
  emptyMessage: DataTableText
  filteredEmptyMessage?: DataTableText
  loadErrorTitle: DataTableText
  loadErrorMessageKey?: string
  rowKey: (row: Row) => string
  columns: readonly DataTableColumn<Row>[]
  provider: DataTableProvider<Row>
  search?: DataTableSearch<Row>
  filters?: readonly DataTableFilter<Row>[]
  validateQuery?: (query: DataTableAppliedQuery) => string | null
  rowActions?: readonly DataTableRowAction<Row>[]
  bulkAction?: DataTableBulkAction<Row>
  detail?: boolean
  pageSize?: number
  pageSizeOptions?: readonly number[]
  scroll?: 'responsive' | 'vertical'
}

export function dataTableText(value: DataTableText): string {
  return typeof value === 'function' ? value() : value
}
