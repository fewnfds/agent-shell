<script setup lang="ts">
import {
  ConnectionLineType,
  VueFlow,
  type Edge,
  type GraphNode,
  type VueFlowStore,
} from '@vue-flow/core'
import { computed, nextTick, watch } from 'vue'
import { useI18n } from 'vue-i18n'

interface OfficialGraphNode {
  id: string
  type?: string
  data?: unknown
}

interface OfficialGraphEdge {
  source: string
  target: string
  conditional?: boolean
}

const props = defineProps<{
  graph: Record<string, unknown> | null
  state: Record<string, unknown> | null
  loading: boolean
  error?: string
}>()

const { t } = useI18n()
let flow: VueFlowStore | null = null

const officialNodes = computed<OfficialGraphNode[]>(() => {
  const nodes = props.graph?.nodes
  return Array.isArray(nodes) ? nodes.filter(isOfficialNode) : []
})

const officialEdges = computed<OfficialGraphEdge[]>(() => {
  const edges = props.graph?.edges
  return Array.isArray(edges) ? edges.filter(isOfficialEdge) : []
})

const activeNodeIds = computed(() => {
  const next = props.state?.next
  return new Set(Array.isArray(next) ? next.filter((value): value is string => typeof value === 'string') : [])
})

const ranks = computed(() => graphRanks(officialNodes.value, officialEdges.value))
const nodes = computed<GraphNode[]>(() => {
  const grouped = new Map<number, OfficialGraphNode[]>()
  for (const node of officialNodes.value) {
    const rank = ranks.value.get(node.id) ?? 0
    grouped.set(rank, [...(grouped.get(rank) ?? []), node])
  }
  const positions = new Map<string, { x: number, y: number }>()
  for (const [rank, values] of grouped) {
    values.forEach((node, index) => {
      positions.set(node.id, { x: index * 220, y: rank * 120 })
    })
  }
  return officialNodes.value.map((node) => ({
    id: node.id,
    type: 'runtime',
    position: positions.get(node.id) ?? { x: 0, y: 0 },
    data: {
      label: graphNodeLabel(node),
      active: activeNodeIds.value.has(node.id),
      terminal: node.id === '__start__' || node.id === '__end__',
    },
    draggable: false,
    connectable: false,
    selectable: false,
  }))
})

const edges = computed<Edge[]>(() => officialEdges.value.map((edge, index) => ({
  id: `${edge.source}-${edge.target}-${index}`,
  source: edge.source,
  target: edge.target,
  animated: false,
  selectable: false,
})))

function isOfficialNode(value: unknown): value is OfficialGraphNode {
  return value !== null && typeof value === 'object' && typeof (value as { id?: unknown }).id === 'string'
}

function isOfficialEdge(value: unknown): value is OfficialGraphEdge {
  if (value === null || typeof value !== 'object') return false
  const edge = value as { source?: unknown, target?: unknown }
  return typeof edge.source === 'string' && typeof edge.target === 'string'
}

function graphNodeLabel(node: OfficialGraphNode): string {
  if (node.data !== null && typeof node.data === 'object') {
    const name = (node.data as { name?: unknown }).name
    if (typeof name === 'string' && name) return name
  }
  return node.id
}

function graphRanks(
  graphNodes: OfficialGraphNode[],
  graphEdges: OfficialGraphEdge[],
): Map<string, number> {
  const ids = new Set(graphNodes.map((node) => node.id))
  const incoming = new Map([...ids].map((id) => [id, 0]))
  const outgoing = new Map([...ids].map((id) => [id, [] as string[]]))
  for (const edge of graphEdges) {
    if (!ids.has(edge.source) || !ids.has(edge.target)) continue
    incoming.set(edge.target, (incoming.get(edge.target) ?? 0) + 1)
    outgoing.get(edge.source)?.push(edge.target)
  }
  const queue = [...ids].filter((id) => incoming.get(id) === 0)
  const result = new Map<string, number>(queue.map((id) => [id, 0]))
  while (queue.length > 0) {
    const current = queue.shift() as string
    for (const target of outgoing.get(current) ?? []) {
      result.set(target, Math.max(result.get(target) ?? 0, (result.get(current) ?? 0) + 1))
      incoming.set(target, (incoming.get(target) ?? 1) - 1)
      if (incoming.get(target) === 0) queue.push(target)
    }
  }
  graphNodes.forEach((node, index) => {
    if (!result.has(node.id)) result.set(node.id, index)
  })
  return result
}

async function initialize(instance: VueFlowStore): Promise<void> {
  flow = instance
  await nextTick()
  await flow.fitView({ padding: .2 })
}

watch(officialNodes, async () => {
  await nextTick()
  await flow?.fitView({ padding: .2 })
})
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
      class="workflow-runtime-flow"
      :nodes="nodes"
      :edges="edges"
      :connection-line-type="ConnectionLineType.Bezier"
      :nodes-draggable="false"
      :nodes-connectable="false"
      :edges-updatable="false"
      :elements-selectable="false"
      :delete-key-code="null"
      :min-zoom="0.25"
      :max-zoom="2"
      @init="initialize"
    >
      <template #node-runtime="{ data }">
        <div
          class="workflow-runtime-node"
          :class="{
            'workflow-runtime-node--active': data.active,
            'workflow-runtime-node--terminal': data.terminal,
          }"
        >
          <i
            class="bi"
            :class="data.active ? 'bi-arrow-repeat' : data.terminal ? 'bi-record-circle' : 'bi-square'"
            aria-hidden="true"
          />
          <span>{{ data.label }}</span>
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
  background: var(--bs-body-bg);
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

.workflow-runtime-node {
  display: flex;
  align-items: center;
  gap: .5rem;
  min-width: 9rem;
  padding: .7rem .85rem;
  border: 1px solid var(--bs-border-color);
  border-radius: var(--bs-border-radius);
  background: var(--bs-body-bg);
  color: var(--bs-body-color);
  box-shadow: var(--bs-box-shadow-sm);
}

.workflow-runtime-node--terminal {
  background: var(--bs-tertiary-bg);
}

.workflow-runtime-node--active {
  border: 2px solid var(--bs-primary);
  box-shadow: 0 0 0 .2rem var(--bs-primary-bg-subtle);
}

.workflow-runtime-node--active .bi {
  animation: workflow-runtime-spin 1.2s linear infinite;
}

@keyframes workflow-runtime-spin {
  to { transform: rotate(360deg); }
}

@media (prefers-reduced-motion: reduce) {
  .workflow-runtime-node--active .bi { animation: none; }
}
</style>
