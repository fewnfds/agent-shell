<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import type { WorkflowCanvasNode } from '@/domain/workflowGraph'

defineProps<{
  nodes: WorkflowCanvasNode[]
}>()

const emit = defineEmits<{
  locateNode: [nodeId: string]
}>()

const { t } = useI18n()

function nodeTypeLabel(node: WorkflowCanvasNode): string {
  const messageKey = node.data.nodeType
  return t(`workflows.editor.${messageKey}`)
}
</script>

<template>
  <section class="workflow-tool-panel" aria-labelledby="workflow-node-tracker-title">
    <header class="workflow-tool-panel-header">
      <h2 id="workflow-node-tracker-title" class="workflow-tool-panel-title">
        {{ $t('workflows.editor.nodeTracker') }}
      </h2>
    </header>

    <div class="workflow-tool-panel-body">
      <div class="workflow-node-tracker-list">
        <button
          v-for="node in nodes"
          :key="node.id"
          class="workflow-node-tracker-item"
          :data-active="Boolean(node.selected)"
          type="button"
          @click="emit('locateNode', node.id)"
        >
          <span class="workflow-node-tracker-icon" aria-hidden="true">
            <i v-if="node.data.nodeType === 'start'" class="bi bi-play-fill" />
            <i v-else-if="node.data.nodeType === 'agent'" class="bi bi-robot" />
            <i v-else-if="node.data.nodeType === 'command'" class="bi bi-circle-half" />
            <i v-else class="bi bi-stop-fill" />
          </span>
          <span class="workflow-node-tracker-copy">
            <span class="workflow-node-tracker-title">{{ node.id }}</span>
            <span class="workflow-node-tracker-meta">{{ nodeTypeLabel(node) }}</span>
          </span>
        </button>
      </div>
    </div>
  </section>
</template>
