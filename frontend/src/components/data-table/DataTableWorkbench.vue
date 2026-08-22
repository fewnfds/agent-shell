<script setup lang="ts" generic="Row">
import { LteAlert, LteButton, LteCard } from '@adminlte/vue'
import { computed, onMounted, ref, useSlots } from 'vue'
import { useI18n } from 'vue-i18n'

import PaginationControls from '@/components/PaginationControls.vue'
import { useConfirmation } from '@/composables/useConfirmation'
import { useDataTable } from '@/composables/useDataTable'
import { useManagementError } from '@/composables/useManagementError'
import { useToasts } from '@/composables/useToasts'

import {
  dataTableText,
  type DataTableAppliedQuery,
  type DataTableBulkContext,
  type DataTableConfig,
  type DataTableFilterValue,
  type DataTableRowAction,
} from './types'

const props = defineProps<{ config: DataTableConfig<Row> }>()
const emit = defineEmits<{
  queryApplied: []
  detailToggled: [row: Row, expanded: boolean]
}>()

const { t } = useI18n()
const confirmation = useConfirmation()
const managementError = useManagementError()
const { notify } = useToasts()
const slots = useSlots()
const runningRowAction = ref('')
const runningBulkAction = ref(false)
const expandedRow = ref('')

const {
  applied,
  draftQuery,
  draftFilters,
  hasAppliedFilters,
  loadError,
  loading,
  page,
  pageSize,
  rows,
  matchingRows,
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
} = useDataTable(props.config)

const filters = computed(() => props.config.filters ?? [])
const rowActions = computed(() => props.config.rowActions ?? [])
const hasControls = computed(() => Boolean(
  props.config.search
    || filters.value.length
    || props.config.bulkAction
    || slots['filter-controls']
    || slots['filter-actions'],
))
const hasFilterActions = computed(() => Boolean(
  props.config.bulkAction || slots['filter-actions'] || (!props.config.search && filters.value.length),
))
const columnSpan = computed(() => props.config.columns.length + (
  rowActions.value.length ? 1 : 0
))
const bulkContext = computed<DataTableBulkContext<Row>>(() => ({
  applied: applied.value,
  matchingRows: props.config.provider.mode === 'local' ? matchingRows.value : rows.value,
  visibleRows: rows.value,
  total: total.value,
  hasAppliedFilters: hasAppliedFilters.value,
}))
const bulkEnabled = computed(() => Boolean(
  props.config.bulkAction?.enabled(bulkContext.value),
))
const loadErrorText = computed(() => loadError.value
  ? managementError.describe(loadError.value, props.config.loadErrorMessageKey).display
  : '')

function label(value: string | (() => string)): string {
  return dataTableText(value)
}

function actionLabel(action: DataTableRowAction<Row>, row: Row): string {
  if (runningRowAction.value === `${action.key}:${props.config.rowKey(row)}` && action.busyLabel) {
    return label(action.busyLabel)
  }
  return typeof action.label === 'function' ? action.label(row) : action.label
}

function visibleActions(row: Row): readonly DataTableRowAction<Row>[] {
  return rowActions.value.filter((action) => action.visible?.(row) ?? true)
}

function singleValue(value: DataTableFilterValue | undefined): string {
  return typeof value === 'string' ? value : ''
}

function multiValue(value: DataTableFilterValue | undefined): string[] {
  return Array.isArray(value) ? value : []
}

function inputValue(event: Event): string {
  return (event.target as HTMLInputElement | HTMLSelectElement).value
}

function toggleMulti(key: string, option: string, checked: boolean): void {
  const current = multiValue(draftFilters.value[key])
  updateFilter(key, checked
    ? [...new Set([...current, option])]
    : current.filter((value) => value !== option))
}

function toggleDetail(row: Row): void {
  const key = props.config.rowKey(row)
  const expanded = expandedRow.value !== key
  expandedRow.value = expanded ? key : ''
  emit('detailToggled', row, expanded)
}

function interactiveRowTarget(event: Event): boolean {
  const target = event.target
  return target instanceof Element && Boolean(target.closest(
    'a, button, input, select, textarea, label, [role="button"]',
  ))
}

function clickRow(event: MouseEvent, row: Row): void {
  if (!props.config.detail || interactiveRowTarget(event)) return
  toggleDetail(row)
}

function keyRow(event: KeyboardEvent, row: Row): void {
  if (
    !props.config.detail
    || interactiveRowTarget(event)
    || !['Enter', ' '].includes(event.key)
  ) return
  event.preventDefault()
  toggleDetail(row)
}

async function runRowAction(action: DataTableRowAction<Row>, row: Row): Promise<void> {
  const key = `${action.key}:${props.config.rowKey(row)}`
  if (runningRowAction.value || action.disabled?.(row)) return
  if (action.confirm && !await confirmation.confirm(action.confirm(row))) return
  runningRowAction.value = key
  try {
    await action.run(row)
    if (action.successTitle) notify({ tone: 'success', title: label(action.successTitle) })
    if (action.reloadAfter === 'first') await reloadFirst()
    else if (action.reloadAfter === 'current') await reload()
  } catch (error) {
    notify({
      tone: 'danger',
      title: action.failureTitle ? label(action.failureTitle) : t('errors.requestFailed'),
      message: managementError.describe(error, action.failureMessageKey).display,
    })
  } finally {
    runningRowAction.value = ''
  }
}

async function runBulkAction(): Promise<void> {
  const action = props.config.bulkAction
  if (!action || runningBulkAction.value || !bulkEnabled.value) return
  const context = bulkContext.value
  if (!await confirmation.confirm(action.confirm(context))) return
  runningBulkAction.value = true
  try {
    const result = await action.run(context)
    if (action.successTitle) {
      const title = typeof action.successTitle === 'function'
        ? action.successTitle(result)
        : action.successTitle
      notify({ tone: 'success', title })
    }
    await reloadFirst()
  } catch (error) {
    notify({
      tone: 'danger',
      title: label(action.failureTitle),
      message: managementError.describe(error, action.failureMessageKey).display,
    })
    await reload()
  } finally {
    runningBulkAction.value = false
  }
}

async function submitQuery(): Promise<void> {
  if (await apply()) emit('queryApplied')
}

async function clearQuery(): Promise<void> {
  emit('queryApplied')
  await reset()
}

onMounted(() => { void reload() })

defineExpose<{
  reload: () => Promise<void>
  reloadFirst: () => Promise<void>
  setQuery: (value: Partial<DataTableAppliedQuery>) => Promise<boolean>
}>({ reload, reloadFirst, setQuery })
</script>

<template>
  <LteCard v-if="hasControls" class="mb-3">
    <form class="collection-filter-form" role="search" @submit.prevent="submitQuery">
      <div v-if="config.search || filters.length || slots['filter-controls']" class="collection-filter-grid">
        <div v-if="config.search" class="collection-query">
          <label class="form-label" :for="`${config.id}-query`">{{ label(config.search.label) }}</label>
          <div class="input-group">
            <input
              :id="`${config.id}-query`"
              v-model="draftQuery"
              class="form-control"
              :placeholder="label(config.search.placeholder)"
              type="search"
            >
            <LteButton class="action-button" :disabled="loading" type="submit">
              <i class="bi bi-search" aria-hidden="true" />
              {{ t('common.search') }}
            </LteButton>
            <LteButton class="action-button" :disabled="loading" type="button" @click="clearQuery">
              <i class="bi bi-arrow-clockwise" aria-hidden="true" />
              {{ t('common.reset') }}
            </LteButton>
          </div>
        </div>

        <template v-for="filter in filters" :key="filter.key">
          <div v-if="filter.kind === 'text' || filter.kind === 'datetime'">
            <label class="form-label" :for="`${config.id}-filter-${filter.key}`">{{ label(filter.label) }}</label>
            <input
              :id="`${config.id}-filter-${filter.key}`"
              autocomplete="off"
              class="form-control"
              :placeholder="filter.kind === 'text' && filter.placeholder ? label(filter.placeholder) : undefined"
              :step="filter.kind === 'datetime' ? 1 : undefined"
              :type="filter.kind === 'datetime' ? 'datetime-local' : 'text'"
              :value="singleValue(draftFilters[filter.key])"
              @input="updateFilter(filter.key, inputValue($event))"
            >
          </div>
          <div v-else-if="filter.kind === 'single'">
            <label class="form-label" :for="`${config.id}-filter-${filter.key}`">{{ label(filter.label) }}</label>
            <select
              :id="`${config.id}-filter-${filter.key}`"
              class="form-select"
              :value="singleValue(draftFilters[filter.key])"
              @change="updateFilter(filter.key, inputValue($event))"
            >
              <option value="">{{ t('common.all') }}</option>
              <option v-for="option in filter.options" :key="option.value" :value="option.value">
                {{ label(option.label) }}
              </option>
            </select>
          </div>
          <fieldset v-else class="collection-filter-fieldset">
            <legend class="collection-filter-legend form-label">{{ label(filter.label) }}</legend>
            <div class="collection-filter-options">
              <template v-for="option in filter.options" :key="option.value">
                <input
                  :id="`${config.id}-filter-${filter.key}-${option.value}`"
                  class="btn-check"
                  type="checkbox"
                  :checked="multiValue(draftFilters[filter.key]).includes(option.value)"
                  @change="toggleMulti(filter.key, option.value, ($event.target as HTMLInputElement).checked)"
                >
                <label class="btn btn-outline-primary btn-sm" :for="`${config.id}-filter-${filter.key}-${option.value}`">
                  {{ label(option.label) }}
                </label>
              </template>
            </div>
          </fieldset>
        </template>

        <fieldset v-if="slots['filter-controls']" class="collection-filter-fieldset">
          <legend class="collection-filter-legend form-label">
            <slot name="filter-controls-title" />
          </legend>
          <slot name="filter-controls" />
        </fieldset>

        <fieldset v-if="hasFilterActions" class="collection-filter-fieldset">
          <legend class="collection-filter-legend form-label">{{ t('common.dataTable.operations') }}</legend>
          <div class="collection-filter-options">
            <template v-if="!config.search && filters.length">
              <LteButton class="action-button" :disabled="loading" type="submit">
                <i class="bi bi-search" aria-hidden="true" />
                {{ t('common.search') }}
              </LteButton>
              <LteButton class="action-button" :disabled="loading" type="button" @click="clearQuery">
                <i class="bi bi-arrow-clockwise" aria-hidden="true" />
                {{ t('common.reset') }}
              </LteButton>
            </template>
            <slot name="filter-actions" />
            <LteButton
              v-if="config.bulkAction"
              class="action-button"
              :disabled="loading || runningBulkAction || !bulkEnabled"
              type="button"
              @click="runBulkAction"
            >
              <i v-if="config.bulkAction.icon === 'delete'" class="bi bi-trash" aria-hidden="true" />
              <i v-else-if="config.bulkAction.icon === 'copy'" class="bi bi-copy" aria-hidden="true" />
              <i v-else-if="config.bulkAction.icon === 'download'" class="bi bi-download" aria-hidden="true" />
              <i v-else-if="config.bulkAction.icon === 'edit'" class="bi bi-pencil" aria-hidden="true" />
              <i v-else-if="config.bulkAction.icon === 'view'" class="bi bi-eye" aria-hidden="true" />
              <i v-else class="bi bi-check-lg" aria-hidden="true" />
              {{ runningBulkAction && config.bulkAction.busyLabel
                ? label(config.bulkAction.busyLabel)
                : label(config.bulkAction.label) }}
            </LteButton>
          </div>
        </fieldset>
      </div>

      <p v-if="queryValidationError" class="text-danger mb-0" role="alert">
        {{ queryValidationError }}
      </p>
    </form>
  </LteCard>

  <LteCard>
    <div v-if="loading" class="d-flex align-items-center gap-2 p-3" role="status">
      <span class="spinner-border" aria-hidden="true" />
      <span>{{ t('common.loading') }}</span>
    </div>
    <div v-else-if="loadError" data-testid="data-table-error" role="alert">
      <LteAlert :title="label(config.loadErrorTitle)" theme="danger">{{ loadErrorText }}</LteAlert>
      <LteButton class="action-button" type="button" @click="reload">
        <i class="bi bi-arrow-clockwise" aria-hidden="true" />
        {{ t('common.retry') }}
      </LteButton>
    </div>
    <p v-else-if="rows.length === 0" class="text-center text-body-secondary p-3" role="status">
      {{ label(hasAppliedFilters && config.filteredEmptyMessage
        ? config.filteredEmptyMessage
        : config.emptyMessage) }}
    </p>
    <div
      v-else
      class="table-responsive collection-table-viewport"
      :data-scroll="config.scroll ?? 'responsive'"
      data-testid="data-table"
    >
      <table
        class="table table-hover align-middle collection-table"
        :aria-label="label(config.ariaLabel)"
        :data-table-id="config.id"
      >
        <thead class="management-table-head">
          <tr>
            <th v-for="column in config.columns" :key="column.key" scope="col">{{ label(column.label) }}</th>
            <th v-if="rowActions.length" scope="col">{{ t('common.dataTable.actions') }}</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="row in rows" :key="config.rowKey(row)">
            <tr
              data-testid="data-table-row"
              :aria-expanded="config.detail ? expandedRow === config.rowKey(row) : undefined"
              :tabindex="config.detail ? 0 : undefined"
              @click="clickRow($event, row)"
              @keydown="keyRow($event, row)"
            >
              <td v-for="column in config.columns" :key="column.key">
                <slot :name="`cell-${column.key}`" :row="row" :value="column.value(row)">
                  {{ column.value(row) }}
                </slot>
              </td>
              <td v-if="rowActions.length">
                <div class="collection-row-actions">
                  <LteButton
                    v-for="action in visibleActions(row)"
                    :key="action.key"
                    class="icon-action-button"
                    :data-action="action.key"
                    :aria-label="actionLabel(action, row)"
                    :disabled="Boolean(runningRowAction) || Boolean(action.disabled?.(row))"
                    size="sm"
                    :title="actionLabel(action, row)"
                    type="button"
                    @click="runRowAction(action, row)"
                  >
                    <i v-if="action.icon === 'activate'" class="bi bi-check-lg" aria-hidden="true" />
                    <i v-else-if="action.icon === 'copy'" class="bi bi-copy" aria-hidden="true" />
                    <i v-else-if="action.icon === 'delete'" class="bi bi-trash" aria-hidden="true" />
                    <i v-else-if="action.icon === 'download'" class="bi bi-download" aria-hidden="true" />
                    <i v-else-if="action.icon === 'edit'" class="bi bi-pencil" aria-hidden="true" />
                    <i v-else class="bi bi-eye" aria-hidden="true" />
                    <span class="visually-hidden">{{ actionLabel(action, row) }}</span>
                  </LteButton>
                </div>
              </td>
            </tr>
            <tr v-if="config.detail && expandedRow === config.rowKey(row)" data-testid="data-table-detail">
              <td :colspan="columnSpan"><slot name="detail" :row="row" /></td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>

    <PaginationControls
      v-if="!loading && !loadError"
      :id="config.id"
      :aria-label="label(config.ariaLabel)"
      :item-count="rows.length"
      :page="page"
      :page-size="pageSize"
      :page-size-options="config.pageSizeOptions ? [...config.pageSizeOptions] : undefined"
      :total="total"
      :total-pages="totalPages"
      @change="changePage"
      @page-size-change="changePageSize"
    />
  </LteCard>
</template>
