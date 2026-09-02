<script setup lang="ts">
import { LteAlert } from '@adminlte/vue'
import { useI18n } from 'vue-i18n'

import { managementApi, type WorkflowLifecycleSummary } from '@/api'
import DataTableWorkbench from '@/components/data-table/DataTableWorkbench.vue'
import type { DataTableConfig } from '@/components/data-table/types'
import PageShell from '@/components/PageShell.vue'

const { t } = useI18n()

function localTime(value: string | null): string {
  if (!value) return t('common.none')
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString()
}

function lifecycleStatus(row: WorkflowLifecycleSummary): string {
  if (row.lifecycle_status !== 'active') {
    return t(`workflowLifecycles.lifecycleStatuses.${row.lifecycle_status}`)
  }
  return t(`workflowLifecycles.runStatuses.${row.root_status}`)
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
      value: lifecycleStatus,
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
      key: 'capture',
      label: () => t('workflowLifecycles.columns.capture'),
      value: (row) => row.monitoring_capture_enabled
        ? t('workflowLifecycles.capture.enabled')
        : t('workflowLifecycles.capture.disabled'),
    },
  ],
  rowActions: [
    {
      key: 'delete',
      label: () => t('common.delete'),
      icon: 'delete',
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
    run: (context) => managementApi.deleteWorkflowLifecyclesMatching(context.applied.query),
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
</script>

<template>
  <PageShell>
    <LteAlert
      class="mb-3"
      :title="t('workflowLifecycles.visualizationPendingTitle')"
      theme="info"
    >
      {{ t('workflowLifecycles.visualizationPending') }}
    </LteAlert>
    <DataTableWorkbench :config="tableConfig" />
  </PageShell>
</template>
