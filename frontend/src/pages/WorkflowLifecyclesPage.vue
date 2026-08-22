<script setup lang="ts">
import { LteAlert, LteButton } from '@adminlte/vue'
import { reactive } from 'vue'
import { useI18n } from 'vue-i18n'

import {
  managementApi,
  type WorkflowLifecycleDetail,
  type WorkflowLifecycleSummary,
  type WorkflowRunEvent,
  type WorkflowRunDetail,
  type WorkflowRunRecord,
} from '@/api'
import DataTableWorkbench from '@/components/data-table/DataTableWorkbench.vue'
import type { DataTableConfig } from '@/components/data-table/types'
import PageShell from '@/components/PageShell.vue'
import { useManagementError } from '@/composables/useManagementError'
import { useToasts } from '@/composables/useToasts'
import { triggerBrowserDownload } from '@/utils/download'

const { t } = useI18n()
const managementError = useManagementError()
const { notify } = useToasts()

const details = reactive<Record<string, WorkflowLifecycleDetail | undefined>>({})
const detailLoading = reactive<Record<string, boolean>>({})
const detailErrors = reactive<Record<string, boolean>>({})
const downloadingRuns = reactive<Record<string, boolean>>({})
const selectedRuns = reactive<Record<string, string | undefined>>({})
const runDetails = reactive<Record<string, WorkflowRunDetail | undefined>>({})
const runDetailLoading = reactive<Record<string, boolean>>({})
const runDetailErrors = reactive<Record<string, boolean>>({})
const loadingMoreEvents = reactive<Record<string, boolean>>({})

function localTime(value: string | null): string {
  if (!value) return t('common.none')
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString()
}

function shortId(value: string | null): string {
  if (!value) return t('common.none')
  return value.length > 16 ? `${value.slice(0, 8)}...${value.slice(-4)}` : value
}

function runStatus(status: WorkflowRunRecord['status']): string {
  return t(`workflowLifecycles.runStatuses.${status}`)
}

function observationStatus(status: WorkflowLifecycleSummary['observation_status']): string {
  return t(`workflowLifecycles.observationStatuses.${status}`)
}

function eventSubject(event: WorkflowRunEvent): string {
  return event.subject_name || event.workflow_node_id || shortId(event.subject_id)
}

async function toggleRunDetail(lifecycleId: string, run: WorkflowRunRecord): Promise<void> {
  if (selectedRuns[lifecycleId] === run.run_id) {
    selectedRuns[lifecycleId] = undefined
    return
  }
  selectedRuns[lifecycleId] = run.run_id
  if (runDetails[run.run_id] || runDetailLoading[run.run_id]) return
  runDetailLoading[run.run_id] = true
  runDetailErrors[run.run_id] = false
  try {
    runDetails[run.run_id] = await managementApi.getWorkflowRun(lifecycleId, run.run_id)
  } catch {
    runDetailErrors[run.run_id] = true
  } finally {
    runDetailLoading[run.run_id] = false
  }
}

async function loadDetail(row: WorkflowLifecycleSummary, expanded: boolean): Promise<void> {
  if (!expanded || details[row.lifecycle_id] || detailLoading[row.lifecycle_id]) return
  detailLoading[row.lifecycle_id] = true
  detailErrors[row.lifecycle_id] = false
  try {
    details[row.lifecycle_id] = await managementApi.getWorkflowLifecycle(row.lifecycle_id)
  } catch {
    detailErrors[row.lifecycle_id] = true
  } finally {
    detailLoading[row.lifecycle_id] = false
  }
}

async function downloadLifecycle(row: WorkflowLifecycleSummary): Promise<void> {
  const blob = await managementApi.downloadWorkflowLifecycle(row.lifecycle_id)
  triggerBrowserDownload(blob, `agent-shell-lifecycle-${row.lifecycle_id}.zip`)
}

async function downloadRun(run: WorkflowRunRecord): Promise<void> {
  if (downloadingRuns[run.run_id]) return
  downloadingRuns[run.run_id] = true
  try {
    const blob = await managementApi.downloadWorkflowRun(run.lifecycle_id, run.run_id)
    triggerBrowserDownload(blob, `agent-shell-run-${run.run_id}.zip`)
  } catch (error) {
    notify({
      tone: 'danger',
      title: t('workflowLifecycles.downloadFailed'),
      message: managementError.describe(error).display,
    })
  } finally {
    downloadingRuns[run.run_id] = false
  }
}

async function loadMoreEvents(detail: WorkflowLifecycleDetail): Promise<void> {
  if (!detail.event_has_more || loadingMoreEvents[detail.lifecycle_id]) return
  loadingMoreEvents[detail.lifecycle_id] = true
  try {
    const page = await managementApi.listWorkflowLifecycleEvents(
      detail.lifecycle_id,
      detail.next_event_sequence,
    )
    detail.events.push(...page.items)
    detail.next_event_sequence = page.next_after_sequence
    detail.event_has_more = page.has_more
  } catch (error) {
    notify({
      tone: 'danger',
      title: t('workflowLifecycles.detail.loadMoreEventsFailed'),
      message: managementError.describe(error).display,
    })
  } finally {
    loadingMoreEvents[detail.lifecycle_id] = false
  }
}

const tableConfig: DataTableConfig<WorkflowLifecycleSummary> = {
  id: 'workflow-lifecycles',
  ariaLabel: () => t('workflowLifecycles.tableAriaLabel'),
  emptyMessage: () => t('workflowLifecycles.empty'),
  filteredEmptyMessage: () => t('workflowLifecycles.filteredEmpty'),
  loadErrorTitle: () => t('workflowLifecycles.loadFailed'),
  rowKey: (row) => row.lifecycle_id,
  provider: {
    mode: 'numbered',
    load: async (request) => {
      const response = await managementApi.listWorkflowLifecycles({
        page: request.page,
        page_size: request.pageSize,
        query: request.query,
      })
      return { rows: response.items, total: response.total }
    },
  },
  search: {
    label: () => t('common.search'),
    placeholder: () => t('workflowLifecycles.searchPlaceholder'),
    values: (row) => [row.workflow_name, row.lifecycle_id, row.request_id],
  },
  columns: [
    {
      key: 'workflow',
      label: () => t('workflowLifecycles.columns.parentWorkflow'),
      value: (row) => row.workflow_name || row.workflow_id,
    },
    {
      key: 'created',
      label: () => t('workflowLifecycles.columns.created'),
      value: (row) => localTime(row.created_at),
    },
    {
      key: 'status',
      label: () => t('workflowLifecycles.columns.status'),
      value: (row) => row.lifecycle_status === 'deleting'
        ? t('workflowLifecycles.lifecycleStatuses.deleting')
        : t(`workflowLifecycles.parentStatuses.${row.parent_status}`),
    },
    {
      key: 'runs',
      label: () => t('workflowLifecycles.columns.runs'),
      value: (row) => `${row.active_run_count} / ${row.run_count}`,
    },
    {
      key: 'failed',
      label: () => t('workflowLifecycles.columns.failedRuns'),
      value: (row) => row.failed_run_count,
    },
    {
      key: 'usage',
      label: () => t('workflowLifecycles.columns.tokens'),
      value: (row) => row.usage.total_tokens.toLocaleString(),
    },
    {
      key: 'observation',
      label: () => t('workflowLifecycles.columns.observation'),
      value: (row) => observationStatus(row.observation_status),
    },
  ],
  rowActions: [
    {
      key: 'download',
      label: () => t('workflowLifecycles.downloadLifecycle'),
      tone: 'info',
      icon: 'download',
      run: downloadLifecycle,
      failureTitle: () => t('workflowLifecycles.downloadFailed'),
    },
    {
      key: 'delete',
      label: () => t('common.delete'),
      tone: 'danger',
      confirm: (row) => ({
        title: t('workflowLifecycles.deleteTitle'),
        description: t('workflowLifecycles.deleteDescription', {
          name: row.workflow_name || row.lifecycle_id,
        }),
        confirmLabel: t('common.delete'),
        cancelLabel: t('common.cancel'),
        dangerous: true,
      }),
      run: (row) => managementApi.deleteWorkflowLifecycle(row.lifecycle_id),
      successTitle: () => t('workflowLifecycles.deleted'),
      failureTitle: () => t('workflowLifecycles.deleteFailed'),
      reloadAfter: 'current',
    },
  ],
  detail: true,
  pageSize: 10,
  pageSizeOptions: [10],
}
</script>

<template>
  <PageShell>
    <DataTableWorkbench :config="tableConfig" @detail-toggled="loadDetail">
      <template #detail="{ row }">
        <div v-if="detailLoading[row.lifecycle_id]" class="d-flex align-items-center gap-2 p-3" role="status">
          <span class="spinner-border spinner-border-sm" aria-hidden="true" />
          <span>{{ t('common.loading') }}</span>
        </div>
        <LteAlert
          v-else-if="detailErrors[row.lifecycle_id]"
          :title="t('workflowLifecycles.detailLoadFailed')"
          theme="danger"
        />
        <div v-else-if="details[row.lifecycle_id]" class="p-3">
          <div class="d-flex flex-wrap align-items-center gap-3 mb-3">
            <div>
              <div class="fw-semibold">{{ details[row.lifecycle_id]!.workflow_name }}</div>
              <code>{{ details[row.lifecycle_id]!.lifecycle_id }}</code>
            </div>
            <dl class="d-flex flex-wrap gap-3 mb-0 ms-auto">
              <div>
                <dt class="small text-body-secondary">{{ t('workflowLifecycles.detail.checkpoints') }}</dt>
                <dd class="mb-0">{{ details[row.lifecycle_id]!.checkpoint_count }}</dd>
              </div>
              <div>
                <dt class="small text-body-secondary">{{ t('workflowLifecycles.detail.storeItems') }}</dt>
                <dd class="mb-0">{{ details[row.lifecycle_id]!.store_item_count }}</dd>
              </div>
              <div>
                <dt class="small text-body-secondary">{{ t('workflowLifecycles.detail.diagnostics') }}</dt>
                <dd class="mb-0">{{ details[row.lifecycle_id]!.diagnostics.length }}</dd>
              </div>
            </dl>
          </div>

          <section class="mb-3" :aria-label="t('workflowLifecycles.detail.runs')">
            <h2 class="h5 mb-2">{{ t('workflowLifecycles.detail.runs') }}</h2>
            <div class="table-responsive">
              <table class="table align-middle mb-0">
                <thead>
                  <tr>
                    <th scope="col">{{ t('workflowLifecycles.run.target') }}</th>
                    <th scope="col">{{ t('workflowLifecycles.run.kind') }}</th>
                    <th scope="col">{{ t('workflowLifecycles.run.status') }}</th>
                    <th scope="col">{{ t('workflowLifecycles.run.runId') }}</th>
                    <th scope="col">{{ t('workflowLifecycles.run.parent') }}</th>
                    <th scope="col">{{ t('workflowLifecycles.run.depth') }}</th>
                    <th scope="col">{{ t('workflowLifecycles.run.tokens') }}</th>
                    <th scope="col">{{ t('common.dataTable.actions') }}</th>
                  </tr>
                </thead>
                <tbody>
                  <template v-for="run in details[row.lifecycle_id]!.runs" :key="run.run_id">
                  <tr>
                    <td>{{ run.target_name || run.target_id }}</td>
                    <td>{{ t(`workflowLifecycles.runKinds.${run.run_kind}`) }}</td>
                    <td>
                      {{ runStatus(run.status) }}
                      <span v-if="run.error_code" class="d-block small text-danger">{{ run.error_code }}</span>
                    </td>
                    <td><code>{{ shortId(run.run_id) }}</code></td>
                    <td><code>{{ shortId(run.parent_run_id) }}</code></td>
                    <td>{{ run.run_depth }}</td>
                    <td>{{ run.usage.total_tokens.toLocaleString() }}</td>
                    <td>
                      <div class="d-flex gap-1">
                      <LteButton
                        class="icon-action-button"
                        :aria-label="t('workflowLifecycles.viewRun')"
                        size="sm"
                        theme="secondary"
                        :title="t('workflowLifecycles.viewRun')"
                        type="button"
                        @click="toggleRunDetail(row.lifecycle_id, run)"
                      >
                        <i class="bi bi-eye" aria-hidden="true" />
                      </LteButton>
                      <LteButton
                        class="icon-action-button"
                        :aria-label="t('workflowLifecycles.downloadRun')"
                        :disabled="downloadingRuns[run.run_id]"
                        size="sm"
                        theme="info"
                        :title="t('workflowLifecycles.downloadRun')"
                        type="button"
                        @click="downloadRun(run)"
                      >
                        <i class="bi bi-download" aria-hidden="true" />
                      </LteButton>
                      </div>
                    </td>
                  </tr>
                  <tr v-if="selectedRuns[row.lifecycle_id] === run.run_id">
                    <td colspan="8">
                      <dl class="row g-3 mb-0 p-3">
                        <div class="col-12 col-lg-4">
                          <dt class="small text-body-secondary">{{ t('workflowLifecycles.run.threadId') }}</dt>
                          <dd class="mb-0"><code>{{ run.thread_id }}</code></dd>
                        </div>
                        <div class="col-12 col-lg-4">
                          <dt class="small text-body-secondary">{{ t('workflowLifecycles.run.launcher') }}</dt>
                          <dd class="mb-0"><code>{{ run.launcher_id || t('common.none') }}</code></dd>
                        </div>
                        <div class="col-12 col-lg-4">
                          <dt class="small text-body-secondary">{{ t('workflowLifecycles.run.task') }}</dt>
                          <dd class="mb-0"><code>{{ run.background_task_id || t('common.none') }}</code></dd>
                        </div>
                        <div class="col-12 col-md-6 col-lg-3">
                          <dt class="small text-body-secondary">{{ t('workflowLifecycles.run.started') }}</dt>
                          <dd class="mb-0">{{ localTime(run.started_at) }}</dd>
                        </div>
                        <div class="col-12 col-md-6 col-lg-3">
                          <dt class="small text-body-secondary">{{ t('workflowLifecycles.run.finished') }}</dt>
                          <dd class="mb-0">{{ localTime(run.finished_at) }}</dd>
                        </div>
                        <div class="col-12 col-md-6 col-lg-3">
                          <dt class="small text-body-secondary">{{ t('workflowLifecycles.detail.checkpoints') }}</dt>
                          <dd class="mb-0">
                            {{ run.checkpoint_available
                              ? (runDetails[run.run_id]?.checkpoint_count ?? t('common.loading'))
                              : t('workflowLifecycles.run.notAvailable') }}
                          </dd>
                        </div>
                        <div class="col-12 col-md-6 col-lg-3">
                          <dt class="small text-body-secondary">{{ t('workflowLifecycles.detail.timeline') }}</dt>
                          <dd class="mb-0">{{ runDetails[run.run_id]?.event_count ?? t('common.loading') }}</dd>
                        </div>
                        <div class="col-12 col-md-6 col-lg-3">
                          <dt class="small text-body-secondary">{{ t('workflowLifecycles.detail.diagnostics') }}</dt>
                          <dd class="mb-0">{{ runDetails[run.run_id]?.diagnostic_count ?? t('common.loading') }}</dd>
                        </div>
                        <div class="col-12 col-md-6 col-lg-3">
                          <dt class="small text-body-secondary">{{ t('workflowLifecycles.columns.observation') }}</dt>
                          <dd class="mb-0">{{ observationStatus(run.observation_status) }}</dd>
                        </div>
                      </dl>
                      <div v-if="runDetailLoading[run.run_id]" class="d-flex align-items-center gap-2 p-3" role="status">
                        <span class="spinner-border spinner-border-sm" aria-hidden="true" />
                        <span>{{ t('common.loading') }}</span>
                      </div>
                      <LteAlert
                        v-else-if="runDetailErrors[run.run_id]"
                        :title="t('workflowLifecycles.run.detailLoadFailed')"
                        theme="danger"
                      />
                    </td>
                  </tr>
                  </template>
                </tbody>
              </table>
            </div>
          </section>

          <section :aria-label="t('workflowLifecycles.detail.timeline')">
            <h2 class="h5 mb-2">{{ t('workflowLifecycles.detail.timeline') }}</h2>
            <p v-if="details[row.lifecycle_id]!.events.length === 0" class="text-body-secondary mb-0">
              {{ t('workflowLifecycles.detail.noEvents') }}
            </p>
            <div v-else class="table-responsive">
              <table class="table align-middle mb-0">
                <thead>
                  <tr>
                    <th scope="col">#</th>
                    <th scope="col">{{ t('workflowLifecycles.event.time') }}</th>
                    <th scope="col">{{ t('workflowLifecycles.event.run') }}</th>
                    <th scope="col">{{ t('workflowLifecycles.event.kind') }}</th>
                    <th scope="col">{{ t('workflowLifecycles.event.subject') }}</th>
                    <th scope="col">{{ t('workflowLifecycles.event.phase') }}</th>
                    <th scope="col">{{ t('workflowLifecycles.event.node') }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="event in details[row.lifecycle_id]!.events" :key="event.sequence">
                    <td>{{ event.sequence }}</td>
                    <td>{{ localTime(event.occurred_at) }}</td>
                    <td><code>{{ shortId(event.run_id) }}</code></td>
                    <td>{{ t(`workflowLifecycles.subjectKinds.${event.subject_kind}`) }}</td>
                    <td>{{ eventSubject(event) }}</td>
                    <td>{{ t(`workflowLifecycles.eventPhases.${event.phase}`) }}</td>
                    <td><code>{{ event.workflow_node_id || t('common.none') }}</code></td>
                  </tr>
                </tbody>
              </table>
            </div>
            <LteButton
              v-if="details[row.lifecycle_id]!.event_has_more"
              class="mt-2"
              :disabled="loadingMoreEvents[row.lifecycle_id]"
              size="sm"
              theme="secondary"
              type="button"
              @click="loadMoreEvents(details[row.lifecycle_id]!)"
            >
              {{ loadingMoreEvents[row.lifecycle_id]
                ? t('common.loading')
                : t('workflowLifecycles.detail.loadMoreEvents') }}
            </LteButton>
          </section>
        </div>
      </template>
    </DataTableWorkbench>
  </PageShell>
</template>
