<script setup lang="ts">
import {
  ConnectionLineType,
  VueFlow,
  type VueFlowStore,
} from '@vue-flow/core'
import { computed, nextTick, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type {
  ConfigurationSummary,
  WorkflowGraphDocument,
  WorkflowNodeCatalogItem,
  WorkflowNodeType,
} from '@/api'
import WorkflowNodeEndpoints from '@/components/workflow/WorkflowNodeEndpoints.vue'
import {
  workflowCanvasNodeEndpoints,
  workflowDocumentToCanvas,
  type WorkflowEndpointDirection,
} from '@/domain/workflowGraph'

const props = defineProps<{
  graph: WorkflowGraphDocument | null
  nodeCatalog: WorkflowNodeCatalogItem[]
  commands: ConfigurationSummary[]
  state: Record<string, unknown> | null
  loading: boolean
  error?: string
}>()

const { t } = useI18n()
let flow: VueFlowStore | null = null

const activeNodeIds = computed(() => {
  const next = props.state?.next
  return new Set(Array.isArray(next) ? next.filter((value): value is string => typeof value === 'string') : [])
})

const canvas = computed(() => {
  if (!props.graph) return null
  const projected = workflowDocumentToCanvas(props.graph, props.nodeCatalog, {
    addDefaultTerminals: false,
  })
  return {
    viewport: projected.viewport,
    nodes: projected.nodes.map((node) => ({
      ...node,
      draggable: false,
      connectable: false,
      selectable: false,
      deletable: false,
      data: { ...node.data, active: activeNodeIds.value.has(node.id) },
    })),
    edges: projected.edges.map((edge) => ({
      ...edge,
      animated: false,
      selectable: false,
      updatable: false,
      deletable: false,
    })),
  }
})

const nodes = computed(() => canvas.value?.nodes ?? [])
const edges = computed(() => canvas.value?.edges ?? [])

function nodeEndpoints(nodeType: WorkflowNodeType, direction: WorkflowEndpointDirection) {
  return workflowCanvasNodeEndpoints(props.nodeCatalog, nodeType, direction)
}

function commandName(commandId: string): string {
  return props.commands.find((item) => item.id === commandId)?.name ?? commandId
}

async function applyFrozenViewport(): Promise<void> {
  if (!flow || !canvas.value) return
  await nextTick()
  await flow.setViewport(canvas.value.viewport)
}

async function initialize(instance: VueFlowStore): Promise<void> {
  flow = instance
  await applyFrozenViewport()
}

watch(() => props.graph, () => { void applyFrozenViewport() })
</script>

<template>
  <section class="workflow-runtime" :aria-label="t('runtimeMonitoring.workflow.title')">
    <div v-if="loading" class="workflow-runtime-loading" aria-busy="true">
      <span class="spinner-border spinner-border-sm" aria-hidden="true" />
    </div>
    <div v-else-if="error" class="workflow-runtime-error" role="alert">
      <i class="bi bi-exclamation-triangle" aria-hidden="true" />
      <span>{{ error }}</span>
    </div>
    <VueFlow
      v-else-if="nodes.length"
      class="workflow-canvas-flow workflow-runtime-flow"
      :nodes="nodes"
      :edges="edges"
      :connection-line-type="ConnectionLineType.Bezier"
      default-marker-color="var(--bs-primary)"
      :nodes-draggable="false"
      :nodes-connectable="false"
      :edges-updatable="false"
      :elements-selectable="false"
      :delete-key-code="null"
      :min-zoom="0.25"
      :max-zoom="2"
      @init="initialize"
    >
      <template #node-start="{ id, data }">
        <div class="workflow-node workflow-node--terminal workflow-runtime-node" :data-running="data.active">
          <span class="workflow-node-icon" aria-hidden="true"><i class="bi bi-play-fill" /></span>
          <span class="workflow-node-title">{{ id }}</span>
          <WorkflowNodeEndpoints direction="output" :endpoints="nodeEndpoints('start', 'output')" />
        </div>
      </template>

      <template #node-command="{ id, data }">
        <div class="workflow-node workflow-node--command workflow-runtime-node" :data-running="data.active">
          <WorkflowNodeEndpoints direction="input" :endpoints="nodeEndpoints('command', 'input')" />
          <div class="workflow-node-header">
            <span class="workflow-node-icon" aria-hidden="true"><i class="bi bi-circle-half" /></span>
            <span class="workflow-node-title">{{ id }}</span>
          </div>
          <span class="workflow-node-summary">{{ commandName(data.commandId ?? '') }}</span>
          <WorkflowNodeEndpoints direction="output" :endpoints="nodeEndpoints('command', 'output')" />
        </div>
      </template>

      <template #node-end="{ id, data }">
        <div class="workflow-node workflow-node--terminal workflow-runtime-node" :data-running="data.active">
          <WorkflowNodeEndpoints direction="input" :endpoints="nodeEndpoints('end', 'input')" />
          <span class="workflow-node-icon" aria-hidden="true"><i class="bi bi-stop-fill" /></span>
          <span class="workflow-node-title">{{ id }}</span>
        </div>
      </template>
    </VueFlow>
    <div v-else class="workflow-runtime-empty">{{ t('runtimeMonitoring.workflow.empty') }}</div>
  </section>
</template>

<style scoped>
.workflow-runtime {
  position: relative;
  height: 100%;
  min-height: 30rem;
}

.workflow-runtime-flow {
  height: 100%;
  min-height: 30rem;
}

.workflow-runtime-loading,
.workflow-runtime-error,
.workflow-runtime-empty {
  display: flex;
  align-items: center;
  gap: .5rem;
  min-height: 30rem;
  padding: 1rem;
  color: var(--bs-secondary-color);
}

.workflow-runtime-error {
  color: var(--bs-danger-text-emphasis);
}

.workflow-runtime-node[data-running='true'] {
  border-color: var(--bs-success);
  background: var(--bs-success-bg-subtle);
  box-shadow: 0 0 0 3px var(--bs-success-border-subtle), var(--bs-box-shadow-sm);
}
</style>
