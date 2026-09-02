<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import type { RuntimeMonitoringRunTreeNode } from '@/domain/runtimeMonitoring'

defineOptions({ name: 'RuntimeRunTreeItem' })

defineProps<{
  item: RuntimeMonitoringRunTreeNode
  selectedRunId: string
  orphanRunIds: readonly string[]
}>()

const emit = defineEmits<{
  select: [runId: string]
}>()

const { t } = useI18n()

function statusIcon(status: RuntimeMonitoringRunTreeNode['run']['status']): string {
  if (status === 'running') return 'bi-arrow-repeat'
  if (status === 'completed') return 'bi-check-circle'
  if (status === 'failed') return 'bi-x-circle'
  if (status === 'cancelled') return 'bi-slash-circle'
  if (status === 'interrupted') return 'bi-exclamation-circle'
  return 'bi-clock'
}
</script>

<template>
  <li class="runtime-run-tree-item">
    <button
      class="runtime-run-index-button"
      :aria-current="item.run.run_id === selectedRunId ? 'true' : undefined"
      :data-selected="item.run.run_id === selectedRunId"
      type="button"
      @click="emit('select', item.run.run_id)"
    >
      <span class="runtime-run-index-icon" aria-hidden="true">
        <i class="bi" :class="statusIcon(item.run.status)" />
      </span>
      <span class="runtime-run-index-copy">
        <span class="runtime-run-index-title">{{ item.run.workflow_name || item.run.workflow_id }}</span>
        <span class="runtime-run-index-id">{{ item.run.run_id }}</span>
        <span class="runtime-run-index-status">
          {{ t(`workflowLifecycles.runStatuses.${item.run.status}`) }}
          <span v-if="orphanRunIds.includes(item.run.run_id)">
            · {{ t('runtimeMonitoring.runIndex.orphan') }}
          </span>
        </span>
      </span>
    </button>
    <ul v-if="item.children.length" class="runtime-run-tree-children">
      <RuntimeRunTreeItem
        v-for="child in item.children"
        :key="child.run.run_id"
        :item="child"
        :orphan-run-ids="orphanRunIds"
        :selected-run-id="selectedRunId"
        @select="emit('select', $event)"
      />
    </ul>
  </li>
</template>
