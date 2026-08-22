<script setup lang="ts">
import { LteAlert, LteButton, LteCard } from '@adminlte/vue'
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'

import {
  managementApi,
  type EventFeedFilters,
  type EventFeedItem,
  type EventFeedResponse,
  type EventLevel,
  type EventSource,
  type ManagementEvent,
  type RuntimeDiagnostics,
  type SystemLogSettings,
} from '@/api'
import DataTableWorkbench from '@/components/data-table/DataTableWorkbench.vue'
import { formattingLocale } from '@/locales'
import type {
  DataTableAppliedQuery,
  DataTableConfig,
  DataTableFilterValue,
} from '@/components/data-table/types'
import PageShell from '@/components/PageShell.vue'
import { useConfirmation } from '@/composables/useConfirmation'
import { useManagementError } from '@/composables/useManagementError'
import { useManagementEvents } from '@/composables/useManagementEvents'
import { useToasts } from '@/composables/useToasts'
import { triggerBrowserDownload } from '@/utils/download'

const sources: EventSource[] = ['system', 'runtime']
const levels: EventLevel[] = ['debug', 'info', 'warning', 'error']

interface EventFeedApi {
  listEventFeed(filters: EventFeedFilters): Promise<EventFeedResponse>
  downloadEvent(source: EventSource, id: string): Promise<Blob>
  getRuntimeDiagnostics(): Promise<RuntimeDiagnostics>
  updateRuntimeDiagnosticRetention(value: number): Promise<RuntimeDiagnostics>
  getSystemLogSettings(): Promise<SystemLogSettings>
  updateSystemLogSettings(value: number): Promise<SystemLogSettings>
  deleteMatchingEventFeed(filters: EventFeedFilters): Promise<{ deleted: number }>
  watchApiServerEvents(
    onEvent: (event: ManagementEvent) => void,
    onError?: (error: unknown) => void,
  ): () => void
}

const props = defineProps<{ api?: EventFeedApi }>()

const { locale, t, te } = useI18n()
const api: EventFeedApi = props.api ?? managementApi
const route = useRoute()
const confirmation = useConfirmation()
const managementError = useManagementError()
const { notify } = useToasts()

function toDateTimeLocal(value: Date): string {
  const part = (number: number) => String(number).padStart(2, '0')
  return `${value.getFullYear()}-${part(value.getMonth() + 1)}-${part(value.getDate())}`
    + `T${part(value.getHours())}:${part(value.getMinutes())}:${part(value.getSeconds())}`
}

function localDateTimeToIso(value: string): string {
  return new Date(value).toISOString()
}

const initialNow = new Date()
const initialStart = new Date(initialNow)
initialStart.setHours(0, 0, 0, 0)
const initialStartedAt = toDateTimeLocal(initialStart)
const initialEndedAt = toDateTimeLocal(initialNow)

const initialSource = typeof route.query.source === 'string'
  && sources.includes(route.query.source as EventSource)
  ? [route.query.source as EventSource]
  : []
const eventTable = ref<{
  reload: () => Promise<void>
  reloadFirst: () => Promise<void>
  setQuery: (value: Partial<DataTableAppliedQuery>) => Promise<boolean>
} | null>(null)
const controlsLoading = ref(false)
const controlsReady = ref(false)
const controlsError = ref('')
const stale = ref(false)
const retentionDrafts = ref({ runtime: 20 })
const savedRetentions = ref({ runtime: 20 })
const systemLogSizeDraft = ref(5)
const savedSystemLogSize = ref(5)
const systemLogSizeMin = ref(1)
const savingControl = ref('')

function describeFailure(error: unknown): string {
  return managementError.describe(error).display
}

function notifyFailure(title: string, error: unknown): void {
  notify({ tone: 'danger', title, message: describeFailure(error) })
}

function filterList<T extends string>(value: DataTableFilterValue | undefined): T[] {
  return Array.isArray(value) ? value as T[] : []
}

function filterText(value: DataTableFilterValue | undefined): string {
  return typeof value === 'string' ? value : ''
}

function eventWindow(query: DataTableAppliedQuery): Pick<EventFeedFilters, 'started_at' | 'ended_at'> {
  return {
    started_at: localDateTimeToIso(filterText(query.filters.started_at)),
    ended_at: localDateTimeToIso(filterText(query.filters.ended_at)),
  }
}

function deletedCount(result: unknown): number {
  if (!result || typeof result !== 'object' || !('deleted' in result)) return 0
  return Number((result as { deleted: unknown }).deleted) || 0
}

function formatTime(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(formattingLocale(locale.value), {
    dateStyle: 'short',
    timeStyle: 'medium',
  }).format(date)
}

function displaySummary(item: EventFeedItem): string {
  const key = `eventFeed.systemSummaries.${item.summary}`
  return item.source === 'system' && te(key) ? t(key) : item.summary
}

function downloadFilename(item: EventFeedItem, blob: Blob): string {
  const parsed = new Date(item.occurred_at)
  const stamp = Number.isNaN(parsed.getTime())
    ? 'unknown-time'
    : parsed.toISOString().replace(/[-:]/g, '').replace(/\.\d{3}Z$/, 'Z')
  const extension = item.source === 'runtime' && blob.type.startsWith('text/plain')
    ? 'log'
    : 'json'
  const kind = item.download_kind === 'diagnostic_detail'
    ? 'diagnostic-detail'
    : `event-${item.source}`
  return `agent-shell-${kind}-${stamp}-${item.id.slice(0, 8)}.${extension}`
}

async function download(item: EventFeedItem): Promise<void> {
  const blob = await api.downloadEvent(item.source, item.id)
  triggerBrowserDownload(blob, downloadFilename(item, blob))
}

const eventTableConfig: DataTableConfig<EventFeedItem> = {
  id: 'event-feed',
  ariaLabel: () => t('eventFeed.pagination.ariaLabel'),
  emptyMessage: () => t('eventFeed.empty'),
  loadErrorTitle: () => t('eventFeed.feedback.loadFailed'),
  rowKey: (item) => `${item.source}:${item.id}`,
  provider: {
    mode: 'numbered',
    load: async (request) => {
      const response = await api.listEventFeed({
        ...eventWindow(request),
        source: filterList<EventSource>(request.filters.source),
        level: filterList<EventLevel>(request.filters.level),
        query: request.query,
        page: request.page,
        page_size: request.pageSize,
      })
      return { rows: response.items, total: response.total }
    },
  },
  search: {
    label: () => t('eventFeed.filters.query'),
    placeholder: () => t('eventFeed.filters.placeholder'),
  },
  filters: [
    {
      key: 'started_at',
      kind: 'datetime',
      label: () => t('eventFeed.filters.startedAt'),
      initialValue: initialStartedAt,
    },
    {
      key: 'ended_at',
      kind: 'datetime',
      label: () => t('eventFeed.filters.endedAt'),
      initialValue: initialEndedAt,
    },
    {
      key: 'source',
      kind: 'multi',
      label: () => t('eventFeed.filters.sources'),
      initialValue: initialSource,
      options: sources.map((source) => ({
        value: source,
        label: () => t(`eventFeed.sources.${source}`),
      })),
    },
    {
      key: 'level',
      kind: 'multi',
      label: () => t('eventFeed.filters.levels'),
      options: levels.map((level) => ({
        value: level,
        label: () => t(`eventFeed.levels.${level}`),
      })),
    },
  ],
  validateQuery: (query) => {
    const startedAt = new Date(filterText(query.filters.started_at))
    const endedAt = new Date(filterText(query.filters.ended_at))
    return Number.isNaN(startedAt.getTime())
      || Number.isNaN(endedAt.getTime())
      || endedAt < startedAt
      ? t('eventFeed.filters.invalidWindow')
      : null
  },
  columns: [
    { key: 'time', label: () => t('eventFeed.columns.time'), value: (item) => formatTime(item.occurred_at) },
    { key: 'source', label: () => t('eventFeed.columns.source'), value: (item) => t(`eventFeed.sources.${item.source}`) },
    { key: 'level', label: () => t('eventFeed.columns.level'), value: (item) => t(`eventFeed.levels.${item.level}`) },
    { key: 'summary', label: () => t('eventFeed.columns.summary'), value: displaySummary },
  ],
  detail: true,
  rowActions: [
    {
      key: 'download-event',
      label: (item) => t(item.download_kind === 'diagnostic_detail'
        ? 'eventFeed.downloadDetail'
        : 'eventFeed.downloadEntry'),
      tone: 'secondary',
      icon: 'download',
      visible: (item) => item.download_kind !== null,
      run: (item) => download(item),
      failureTitle: () => t('eventFeed.feedback.downloadFailed'),
    },
  ],
  bulkAction: {
    label: () => t('common.delete'),
    busyLabel: () => t('common.deleting'),
    icon: 'delete',
    enabled: () => true,
    confirm: () => ({
      title: t('eventFeed.delete.title'),
      description: t('eventFeed.delete.filteredDescription'),
      confirmLabel: t('common.delete'),
      cancelLabel: t('common.cancel'),
      dangerous: true,
    }),
    run: async (context) => {
      stale.value = false
      return api.deleteMatchingEventFeed({
        ...eventWindow(context.applied),
        source: filterList<EventSource>(context.applied.filters.source),
        level: filterList<EventLevel>(context.applied.filters.level),
        query: context.applied.query,
      })
    },
    successTitle: (result) => t('eventFeed.feedback.deleted', { count: deletedCount(result) }),
    failureTitle: () => t('eventFeed.feedback.deleteFailed'),
  },
  pageSize: 50,
  pageSizeOptions: [25, 50, 100],
}

async function loadControls(): Promise<void> {
  controlsLoading.value = true
  controlsError.value = ''
  try {
    const [diagnostics, systemLog] = await Promise.all([
      api.getRuntimeDiagnostics(),
      api.getSystemLogSettings(),
    ])
    const loadedRetentions = {
      runtime: diagnostics.retention_limit,
    }
    retentionDrafts.value = loadedRetentions
    savedRetentions.value = { ...loadedRetentions }
    systemLogSizeDraft.value = systemLog.max_size_mib
    savedSystemLogSize.value = systemLog.max_size_mib
    systemLogSizeMin.value = systemLog.min_size_mib
    controlsReady.value = true
  } catch (error) {
    controlsError.value = describeFailure(error)
  } finally {
    controlsLoading.value = false
  }
}

async function refreshWindow(): Promise<void> {
  stale.value = false
  await eventTable.value?.setQuery({
    filters: { ended_at: toDateTimeLocal(new Date()) },
  })
}

async function refreshAll(): Promise<void> {
  await Promise.all([refreshWindow(), loadControls()])
}

async function saveRetention(source: 'runtime'): Promise<void> {
  const value = retentionDrafts.value[source]
  if (value < savedRetentions.value[source]) {
    const accepted = await confirmation.confirm({
      title: t('eventFeed.retention.confirmTitle'),
      description: t('eventFeed.retention.confirmDescription', { count: value }),
      confirmLabel: t('common.save'),
      cancelLabel: t('common.cancel'),
      dangerous: true,
    })
    if (!accepted) return
  }
  savingControl.value = `${source}-retention`
  try {
    const result = await api.updateRuntimeDiagnosticRetention(value)
    retentionDrafts.value[source] = result.retention_limit
    savedRetentions.value[source] = result.retention_limit
    notify({
      tone: 'success',
      title: t('eventFeed.feedback.retentionSaved', { count: result.retention_limit }),
    })
    markStale()
  } catch (error) {
    notifyFailure(t('eventFeed.feedback.retentionFailed'), error)
  } finally {
    savingControl.value = ''
  }
}

async function saveSystemLogSettings(): Promise<void> {
  const value = systemLogSizeDraft.value
  if (value < savedSystemLogSize.value) {
    const accepted = await confirmation.confirm({
      title: t('eventFeed.retention.systemConfirmTitle'),
      description: t('eventFeed.retention.systemConfirmDescription', { count: value }),
      confirmLabel: t('common.save'),
      cancelLabel: t('common.cancel'),
      dangerous: true,
    })
    if (!accepted) return
  }
  savingControl.value = 'system-log-settings'
  try {
    const result = await api.updateSystemLogSettings(value)
    systemLogSizeDraft.value = result.max_size_mib
    savedSystemLogSize.value = result.max_size_mib
    systemLogSizeMin.value = result.min_size_mib
    notify({
      tone: 'success',
      title: t('eventFeed.feedback.systemLogSizeSaved', { count: result.max_size_mib }),
    })
    markStale()
  } catch (error) {
    notifyFailure(t('eventFeed.feedback.systemLogSizeFailed'), error)
  } finally {
    savingControl.value = ''
  }
}

function markStale(): void {
  stale.value = true
}

function handleEvent(event: ManagementEvent): void {
  if (['history_changed', 'runtime_diagnostic', 'system_log']
    .includes(event.type)) markStale()
}

useManagementEvents(handleEvent, api, markStale)

onMounted(() => { void loadControls() })
</script>

<template>
  <PageShell>
    <template #actions>
      <LteButton v-if="stale" class="action-button" data-testid="load-new-events" @click="refreshWindow">
        <i class="bi bi-arrow-clockwise" aria-hidden="true" />
        {{ t('common.refresh') }}
      </LteButton>
    </template>

    <template #status>
      <LteAlert v-if="controlsError" theme="danger" :title="t('eventFeed.feedback.loadFailed')">
        {{ controlsError }}
      </LteAlert>
    </template>

    <LteCard class="mb-3" :title="t('eventFeed.retention.title')">
      <div v-if="controlsLoading" class="d-flex align-items-center gap-2" aria-busy="true">
        <span class="spinner-border spinner-border-sm" aria-hidden="true" />
        <span>{{ t('common.loading') }}</span>
      </div>

      <div v-if="controlsReady">
        <div class="row g-3" data-ui-control-row>
          <form
            v-for="source in (['runtime'] as const)"
            :key="source"
            class="col-lg-3"
            :data-testid="`retention-${source}`"
            @submit.prevent="saveRetention(source)"
          >
            <label class="form-label" :for="`retention-${source}`">{{ t(`eventFeed.sources.${source}`) }}</label>
            <div class="input-group">
              <input
                :id="`retention-${source}`"
                v-model.number="retentionDrafts[source]"
                class="form-control"
                min="1"
                required
                step="1"
                type="number"
              >
              <LteButton class="action-button" :disabled="savingControl === `${source}-retention`" type="submit">
                <i class="bi bi-floppy" aria-hidden="true" />
                {{ t('common.save') }}
              </LteButton>
            </div>
          </form>
          <form class="col-lg-3" data-testid="system-log-settings" @submit.prevent="saveSystemLogSettings">
            <label class="form-label" for="system-log-max-size">{{ t('eventFeed.retention.systemMaxSize') }}</label>
            <div class="input-group">
              <input
                id="system-log-max-size"
                v-model.number="systemLogSizeDraft"
                class="form-control"
                :min="systemLogSizeMin"
                required
                step="1"
                type="number"
              >
              <span class="input-group-text">{{ 'MiB' }}</span>
              <LteButton class="action-button" :disabled="savingControl === 'system-log-settings'" type="submit">
                <i class="bi bi-floppy" aria-hidden="true" />
                {{ t('common.save') }}
              </LteButton>
            </div>
          </form>
        </div>
      </div>
    </LteCard>

    <DataTableWorkbench
      ref="eventTable"
      :config="eventTableConfig"
      @query-applied="stale = false"
    >
      <template #filter-actions>
        <LteButton class="action-button" :disabled="controlsLoading" type="button" @click="refreshAll">
          <span v-if="controlsLoading" class="spinner-border spinner-border-sm" aria-hidden="true" />
          <i v-else class="bi bi-arrow-clockwise" aria-hidden="true" />
          {{ t('common.refresh') }}
        </LteButton>
      </template>
      <template #cell-summary="{ value }"><span class="text-break">{{ value }}</span></template>
      <template #detail="{ row }">
        <article>
          <pre v-if="row.inline_content" class="bg-body-tertiary border rounded p-3 overflow-auto mb-0">{{ row.inline_content }}</pre>
          <p v-if="row.matched_in_content" class="text-body-secondary mb-0">
            {{ t('eventFeed.matchedInContent') }}
          </p>
        </article>
      </template>
    </DataTableWorkbench>
  </PageShell>
</template>
