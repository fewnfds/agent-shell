<script setup lang="ts">
import { LteAlert, LteButton, LteCard } from '@adminlte/vue'
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import {
  managementApi,
  type LangGraphLifecyclePage,
  type LangGraphLifecycleSummary,
  type WorkflowLifecycleBulkDeleteResult,
  type WorkflowLifecycleSettings,
  type WorkflowLifecycleSettingsUpdate,
} from '@/api'
import DataTableWorkbench from '@/components/data-table/DataTableWorkbench.vue'
import type { DataTableConfig } from '@/components/data-table/types'
import PageShell from '@/components/PageShell.vue'
import { useManagementError } from '@/composables/useManagementError'
import { useToasts } from '@/composables/useToasts'

interface WorkflowLifecyclesApi {
  listWorkflowLifecycles(
    request?: { page?: number; page_size?: number; query?: string },
  ): Promise<LangGraphLifecyclePage>
  deleteWorkflowLifecycle(id: string): Promise<{ ok: boolean }>
  deleteWorkflowLifecyclesMatching(query: string): Promise<WorkflowLifecycleBulkDeleteResult>
  getWorkflowLifecycleSettings(): Promise<WorkflowLifecycleSettings>
  updateWorkflowLifecycleSettings(
    payload: WorkflowLifecycleSettingsUpdate,
  ): Promise<WorkflowLifecycleSettings>
}

const props = defineProps<{ api?: WorkflowLifecyclesApi }>()
const api = props.api ?? managementApi
const { t } = useI18n()
const router = useRouter()
const managementError = useManagementError()
const { notify } = useToasts()
const lifecycleSettings = ref<WorkflowLifecycleSettings | null>(null)
const retainedLifecycles = ref(20)
const settingsLoading = ref(true)
const settingsSaving = ref(false)
const settingsError = ref('')

const settingsValid = computed(() => {
  const value = Number(retainedLifecycles.value)
  return lifecycleSettings.value !== null
    && Number.isInteger(value)
    && value >= lifecycleSettings.value.minimums.retained_lifecycles
})

async function loadSettings(): Promise<void> {
  settingsLoading.value = true
  settingsError.value = ''
  try {
    const result = await api.getWorkflowLifecycleSettings()
    lifecycleSettings.value = result
    retainedLifecycles.value = result.retained_lifecycles
  } catch (error) {
    settingsError.value = managementError.describe(error).display
  } finally {
    settingsLoading.value = false
  }
}

async function saveSettings(): Promise<void> {
  if (!settingsValid.value) return
  settingsSaving.value = true
  settingsError.value = ''
  try {
    const result = await api.updateWorkflowLifecycleSettings({
      retained_lifecycles: Number(retainedLifecycles.value),
    })
    lifecycleSettings.value = result
    retainedLifecycles.value = result.retained_lifecycles
    notify({ tone: 'success', title: t('workflowLifecycles.settings.saved') })
  } catch (error) {
    settingsError.value = managementError.describe(error).display
  } finally {
    settingsSaving.value = false
  }
}

function localTime(value: string): string {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString()
}

function subjectNames(row: LangGraphLifecycleSummary): string[] {
  return row.subjects.map((subject) => subject.name || subject.id)
}

const tableConfig: DataTableConfig<LangGraphLifecycleSummary> = {
  id: 'workflow-lifecycles',
  ariaLabel: () => t('workflowLifecycles.tableAriaLabel'),
  emptyMessage: () => t('workflowLifecycles.empty'),
  filteredEmptyMessage: () => t('workflowLifecycles.filteredEmpty'),
  loadErrorTitle: () => t('workflowLifecycles.loadFailed'),
  rowKey: (row) => row.lifecycle_id,
  provider: {
    mode: 'numbered',
    load: async (request) => {
      const response = await api.listWorkflowLifecycles({
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
    values: (row) => [
      ...row.subjects.flatMap((subject) => [
        subject.graph_kind,
        subject.id,
        subject.name,
      ]),
      row.lifecycle_id,
      row.request_id,
    ],
  },
  columns: [
    {
      key: 'graphs',
      label: () => t('workflowLifecycles.columns.graphs'),
      value: (row) => subjectNames(row).join(', ') || t('common.none'),
    },
    {
      key: 'created',
      label: () => t('workflowLifecycles.columns.created'),
      value: (row) => localTime(row.created_at),
    },
    {
      key: 'status',
      label: () => t('workflowLifecycles.columns.status'),
      value: (row) => t(`workflowLifecycles.runStatuses.${row.status}`),
    },
    {
      key: 'runs',
      label: () => t('workflowLifecycles.columns.runs'),
      value: (row) => `${row.active_run_count} / ${row.run_count}`,
    },
    {
      key: 'errors',
      label: () => t('workflowLifecycles.columns.errorRuns'),
      value: (row) => row.error_run_count,
    },
  ],
  rowActions: [
    {
      key: 'monitor',
      label: () => t('workflowLifecycles.monitor'),
      icon: 'view',
      tone: 'primary',
      run: (row) => router.push(
        `/system/workflow-lifecycles/${encodeURIComponent(row.lifecycle_id)}/monitoring`,
      ),
      reloadAfter: false,
    },
    {
      key: 'delete',
      label: () => t('common.delete'),
      icon: 'delete',
      tone: 'danger',
      disabled: (row) => row.active_run_count > 0,
      confirm: (row) => ({
        title: t('workflowLifecycles.deleteTitle'),
        description: t('workflowLifecycles.deleteDescription', {
          name: subjectNames(row).join(', ') || row.lifecycle_id,
        }),
        confirmLabel: t('common.delete'),
        cancelLabel: t('common.cancel'),
        dangerous: true,
      }),
      run: (row) => api.deleteWorkflowLifecycle(row.lifecycle_id),
      successTitle: () => t('workflowLifecycles.deleted'),
      failureTitle: () => t('workflowLifecycles.deleteFailed'),
      reloadAfter: 'current',
    },
  ],
  bulkAction: {
    label: () => t('workflowLifecycles.bulkDelete.action'),
    busyLabel: () => t('common.deleting'),
    icon: 'delete',
    enabled: (context) => context.total > 0,
    confirm: (context) => ({
      title: t('workflowLifecycles.bulkDelete.title'),
      description: t('workflowLifecycles.bulkDelete.description', { count: context.total }),
      confirmLabel: t('common.delete'),
      cancelLabel: t('common.cancel'),
      dangerous: true,
    }),
    run: (context) => api.deleteWorkflowLifecyclesMatching(context.applied.query),
    successTitle: (result) => {
      const response = result as { deleted: number; skipped_active: number }
      return response.skipped_active
        ? t('workflowLifecycles.bulkDelete.completedWithActive', response)
        : t('workflowLifecycles.bulkDelete.completed', response)
    },
    failureTitle: () => t('workflowLifecycles.bulkDelete.failed'),
  },
  pageSize: 10,
  pageSizeOptions: [10],
}

onMounted(() => { void loadSettings() })
</script>

<template>
  <PageShell>
    <LteCard class="mb-3" :title="t('workflowLifecycles.settings.title')">
      <div v-if="settingsLoading" class="d-flex align-items-center gap-2" aria-busy="true">
        <span class="spinner-border spinner-border-sm" aria-hidden="true" />
        <span>{{ t('common.loading') }}</span>
      </div>

      <LteAlert
        v-if="settingsError"
        theme="danger"
        :title="t('workflowLifecycles.settings.failed')"
      >
        {{ settingsError }}
      </LteAlert>

      <div v-if="lifecycleSettings" class="row g-3" data-ui-control-row>
        <form
          class="col-lg-3"
          data-testid="workflow-lifecycle-settings"
          @submit.prevent="saveSettings"
        >
          <label class="form-label" for="retained-lifecycles">
            {{ t('workflowLifecycles.settings.retainedLifecycles') }}
          </label>
          <div class="input-group">
            <input
              id="retained-lifecycles"
              v-model.number="retainedLifecycles"
              class="form-control"
              :min="lifecycleSettings.minimums.retained_lifecycles"
              required
              step="1"
              type="number"
            >
            <LteButton
              class="action-button"
              :disabled="settingsSaving || !settingsValid"
              type="submit"
            >
              <span
                v-if="settingsSaving"
                class="spinner-border spinner-border-sm"
                aria-hidden="true"
              />
              <i v-else class="bi bi-floppy" aria-hidden="true" />
              {{ t('common.save') }}
            </LteButton>
          </div>
          <p class="form-text mb-0">
            {{ t('workflowLifecycles.settings.retainedLifecyclesHelp') }}
          </p>
        </form>
      </div>
    </LteCard>

    <DataTableWorkbench :config="tableConfig" />
  </PageShell>
</template>
