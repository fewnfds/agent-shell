<script setup lang="ts">
import {
  ConnectionLineType,
  ConnectionMode,
  VueFlow,
  type VueFlowStore,
} from '@vue-flow/core'
import { computed, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'

import type {
  RuntimeMonitoringNodeSummary,
  WorkflowGraphDocument,
  WorkflowNodeCatalogItem,
  WorkflowNodeType,
} from '@/api'
import WorkflowNodeEndpoints from '@/components/workflow/WorkflowNodeEndpoints.vue'
import { runtimeWorkflowCanvasState } from '@/domain/runtimeMonitoring'
import {
  workflowCanvasNodeEndpoints,
  type WorkflowEndpointDirection,
} from '@/domain/workflowGraph'

const props = defineProps<{
  document: WorkflowGraphDocument
  nodeCatalog: WorkflowNodeCatalogItem[]
  nodeSummaries: RuntimeMonitoringNodeSummary[]
  selectedNodeId: string
}>()

const emit = defineEmits<{
  selectNode: [nodeId: string]
}>()

const { t } = useI18n()

const canvas = computed(() => runtimeWorkflowCanvasState(props.document, props.nodeCatalog))
const summaries = computed(() => new Map(
  props.nodeSummaries.map((summary) => [summary.workflow_node_id, summary]),
))

function nodeEndpoints(
  nodeType: WorkflowNodeType,
  direction: WorkflowEndpointDirection,
) {
  return workflowCanvasNodeEndpoints(props.nodeCatalog, nodeType, direction)
}

function nodeConfigSummary(nodeType: WorkflowNodeType, data: { mainAgentId: string; commandId?: string }): string {
  if (nodeType === 'agent') {
    return data.mainAgentId || t('runtimeMonitoring.graph.unconfiguredAgent')
  }
  if (nodeType === 'command') {
    return data.commandId || t('runtimeMonitoring.graph.unconfiguredCommand')
  }
  return t(`runtimeMonitoring.graph.nodeTypes.${nodeType}`)
}

function runningCount(nodeId: string): number {
  return summaries.value.get(nodeId)?.status_counts.running ?? 0
}

function selectNode(nodeId: string): void {
  emit('selectNode', nodeId)
}

function attemptSummary(nodeId: string): string {
  const summary = summaries.value.get(nodeId)
  if (!summary) return t('runtimeMonitoring.graph.noAttempts')
  const statusOrder = ['running', 'completed', 'failed', 'cancelled', 'interrupted', 'incomplete']
  const statusParts = statusOrder.flatMap((status) => {
    const count = summary.status_counts[status] ?? 0
    return count > 0
      ? [t('runtimeMonitoring.graph.statusCount', {
          status: t(`runtimeMonitoring.nodeStatuses.${status}`),
          count,
        })]
      : []
  })
  return t('runtimeMonitoring.graph.attemptSummary', {
    count: summary.attempt_count,
    statuses: statusParts.join(t('common.itemSeparator')),
  })
}

async function initializeFlow(instance: VueFlowStore): Promise<void> {
  await nextTick()
  await instance.setViewport(canvas.value.viewport)
}
</script>

<template>
  <VueFlow
    :edges="canvas.edges"
    :nodes="canvas.nodes"
    class="workflow-canvas-flow runtime-monitoring-flow"
    :connection-line-type="ConnectionLineType.Bezier"
    :connection-mode="ConnectionMode.Strict"
    default-marker-color="var(--bs-primary)"
    :delete-key-code="null"
    :edges-updatable="false"
    :elements-selectable="false"
    :max-zoom="2"
    :min-zoom="0.25"
    :nodes-connectable="false"
    :nodes-draggable="false"
    :zoom-on-double-click="false"
    @init="initializeFlow"
  >
    <template #node-start="{ id, data }">
      <div
        class="workflow-node workflow-node--terminal runtime-monitoring-node"
        :aria-label="t('runtimeMonitoring.graph.openNodeAttempts', { node: id })"
        :aria-pressed="id === selectedNodeId"
        :data-selected="id === selectedNodeId"
        :data-running="runningCount(id) > 0"
        role="button"
        tabindex="0"
        @click="selectNode(id)"
        @keydown.enter.stop.prevent="selectNode(id)"
        @keydown.space.stop.prevent="selectNode(id)"
      >
        <span class="workflow-node-icon" aria-hidden="true"><i class="bi bi-play-fill" /></span>
        <span class="runtime-monitoring-node-copy">
          <span class="workflow-node-title">{{ id }}</span>
          <span class="workflow-node-summary">{{ nodeConfigSummary('start', data) }}</span>
          <span class="runtime-monitoring-node-status">{{ attemptSummary(id) }}</span>
        </span>
        <WorkflowNodeEndpoints direction="output" :endpoints="nodeEndpoints('start', 'output')" />
      </div>
    </template>

    <template #node-agent="{ id, data }">
      <div
        class="workflow-node workflow-node--agent runtime-monitoring-node"
        :aria-label="t('runtimeMonitoring.graph.openNodeAttempts', { node: id })"
        :aria-pressed="id === selectedNodeId"
        :data-selected="id === selectedNodeId"
        :data-running="runningCount(id) > 0"
        role="button"
        tabindex="0"
        @click="selectNode(id)"
        @keydown.enter.stop.prevent="selectNode(id)"
        @keydown.space.stop.prevent="selectNode(id)"
      >
        <WorkflowNodeEndpoints direction="input" :endpoints="nodeEndpoints('agent', 'input')" />
        <div class="workflow-node-header">
          <span class="workflow-node-icon" aria-hidden="true"><i class="bi bi-robot" /></span>
          <span class="workflow-node-title">{{ id }}</span>
        </div>
        <span class="workflow-node-summary">{{ nodeConfigSummary('agent', data) }}</span>
        <span class="runtime-monitoring-node-status">{{ attemptSummary(id) }}</span>
        <WorkflowNodeEndpoints direction="output" :endpoints="nodeEndpoints('agent', 'output')" />
      </div>
    </template>

    <template #node-command="{ id, data }">
      <div
        class="workflow-node workflow-node--command runtime-monitoring-node"
        :aria-label="t('runtimeMonitoring.graph.openNodeAttempts', { node: id })"
        :aria-pressed="id === selectedNodeId"
        :data-selected="id === selectedNodeId"
        :data-running="runningCount(id) > 0"
        role="button"
        tabindex="0"
        @click="selectNode(id)"
        @keydown.enter.stop.prevent="selectNode(id)"
        @keydown.space.stop.prevent="selectNode(id)"
      >
        <WorkflowNodeEndpoints direction="input" :endpoints="nodeEndpoints('command', 'input')" />
        <div class="workflow-node-header">
          <span class="workflow-node-icon" aria-hidden="true"><i class="bi bi-circle-half" /></span>
          <span class="workflow-node-title">{{ id }}</span>
        </div>
        <span class="workflow-node-summary">{{ nodeConfigSummary('command', data) }}</span>
        <span class="runtime-monitoring-node-status">{{ attemptSummary(id) }}</span>
        <WorkflowNodeEndpoints direction="output" :endpoints="nodeEndpoints('command', 'output')" />
      </div>
    </template>

    <template #node-end="{ id, data }">
      <div
        class="workflow-node workflow-node--terminal runtime-monitoring-node"
        :aria-label="t('runtimeMonitoring.graph.openNodeAttempts', { node: id })"
        :aria-pressed="id === selectedNodeId"
        :data-selected="id === selectedNodeId"
        :data-running="runningCount(id) > 0"
        role="button"
        tabindex="0"
        @click="selectNode(id)"
        @keydown.enter.stop.prevent="selectNode(id)"
        @keydown.space.stop.prevent="selectNode(id)"
      >
        <WorkflowNodeEndpoints direction="input" :endpoints="nodeEndpoints('end', 'input')" />
        <span class="workflow-node-icon" aria-hidden="true"><i class="bi bi-stop-fill" /></span>
        <span class="runtime-monitoring-node-copy">
          <span class="workflow-node-title">{{ id }}</span>
          <span class="workflow-node-summary">{{ nodeConfigSummary('end', data) }}</span>
          <span class="runtime-monitoring-node-status">{{ attemptSummary(id) }}</span>
        </span>
      </div>
    </template>
  </VueFlow>
</template>
