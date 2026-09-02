<script setup lang="ts">
import RuntimeRunTreeItem from '@/components/runtime-monitoring/RuntimeRunTreeItem.vue'
import type { RuntimeMonitoringRunTreeNode } from '@/domain/runtimeMonitoring'

defineProps<{
  roots: RuntimeMonitoringRunTreeNode[]
  selectedRunId: string
  orphanRunIds: readonly string[]
}>()

const emit = defineEmits<{
  select: [runId: string]
}>()
</script>

<template>
  <nav :aria-label="$t('runtimeMonitoring.runIndex.ariaLabel')">
    <p v-if="!roots.length" class="mb-0 p-3 text-body-secondary" role="status">
      {{ $t('runtimeMonitoring.runIndex.empty') }}
    </p>
    <ul v-else class="runtime-run-tree">
      <RuntimeRunTreeItem
        v-for="root in roots"
        :key="root.run.run_id"
        :item="root"
        :orphan-run-ids="orphanRunIds"
        :selected-run-id="selectedRunId"
        @select="emit('select', $event)"
      />
    </ul>
  </nav>
</template>
