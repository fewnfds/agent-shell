<script setup lang="ts">
import type { WorkflowNodeCatalogItem } from '@/api'
import { WORKFLOW_NODE_DRAG_MIME } from '@/domain/workflowGraph'

defineProps<{
  command: WorkflowNodeCatalogItem | null
  commandDisabled: boolean
}>()

const emit = defineEmits<{ addCommand: [] }>()

function startDrag(
  event: DragEvent,
  item: WorkflowNodeCatalogItem | null,
  disabled: boolean,
): void {
  if (!item || disabled || !event.dataTransfer) {
    event.preventDefault()
    return
  }
  event.dataTransfer.setData(WORKFLOW_NODE_DRAG_MIME, item.type)
  event.dataTransfer.effectAllowed = 'copy'
}
</script>

<template>
  <section class="workflow-tool-panel" aria-labelledby="workflow-node-library-title">
    <header class="workflow-tool-panel-header">
      <h2 id="workflow-node-library-title" class="workflow-tool-panel-title">
        {{ $t('workflows.editor.nodeLibrary') }}
      </h2>
    </header>
    <div class="workflow-tool-panel-body">
      <h3 class="workflow-tool-panel-section-title">{{ $t('workflows.editor.executionNodes') }}</h3>
      <div class="workflow-node-library-list">
        <button
          v-if="command"
          class="workflow-node-library-item"
          :disabled="commandDisabled"
          :draggable="!commandDisabled"
          type="button"
          @click="emit('addCommand')"
          @dragstart="startDrag($event, command, commandDisabled)"
        >
          <span class="workflow-node-library-icon" aria-hidden="true">
            <i class="bi bi-circle-half" />
          </span>
          <span class="workflow-node-library-copy">
            <span class="workflow-node-library-title">{{ $t('workflows.editor.command') }}</span>
            <span class="workflow-node-library-meta">{{ $t('workflows.editor.commandRouter') }}</span>
          </span>
        </button>
      </div>
    </div>
  </section>
</template>
