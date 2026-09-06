<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { ConfigurationSummary, WorkflowNodeHandleSpec } from '@/api'
import type {
  WorkflowCanvasEdge,
  WorkflowCanvasEdgeType,
  WorkflowCanvasNode,
} from '@/domain/workflowGraph'

const props = defineProps<{
  edge: WorkflowCanvasEdge | null
  edgeSourceEndpoints: WorkflowNodeHandleSpec[]
  edgeTargetEndpoints: WorkflowNodeHandleSpec[]
  edgeTypeOptions: WorkflowCanvasEdgeType[]
  inputEndpoints: WorkflowNodeHandleSpec[]
  commands: ConfigurationSummary[]
  node: WorkflowCanvasNode | null
  nodeIds: string[]
  outputEndpoints: WorkflowNodeHandleSpec[]
  stateContract: string
  workflowName: string
}>()

const emit = defineEmits<{
  removeEdge: [edgeId: string]
  removeNode: [nodeId: string]
  selectEdgeSourceEndpoint: [edgeId: string, endpointId: string]
  selectEdgeTargetEndpoint: [edgeId: string, endpointId: string]
  selectEdgeType: [edgeId: string, edgeType: WorkflowCanvasEdgeType]
  updateCommand: [nodeId: string, commandId: string]
  updateNodeId: [nodeId: string, nextNodeId: string]
}>()

const { t } = useI18n()
const nodeIdDraft = ref('')
const nodeIdError = ref('')
const nodeIdFocused = ref(false)
const nodeIdDescribedBy = computed(() => {
  if (nodeIdError.value) return 'workflow-node-id-error'
  return nodeIdFocused.value ? 'workflow-node-id-help' : undefined
})

watch(
  () => props.node?.id,
  (value) => {
    nodeIdDraft.value = value ?? ''
    nodeIdError.value = ''
    nodeIdFocused.value = false
  },
  { immediate: true },
)

const contextTitle = computed(() => {
  if (props.node) return t(`workflows.editor.${props.node.data.nodeType}`)
  if (props.edge) return t('workflows.editor.normalEdge')
  return t('workflows.editor.workflowProperties')
})
const edgeSourceOptions = computed(() => props.edgeSourceEndpoints.filter((endpoint) => (
  endpoint.edge_type === 'normal'
)))
const edgeTargetOptions = computed(() => props.edgeTargetEndpoints.filter((endpoint) => (
  (endpoint.accepted_edge_types ?? [endpoint.edge_type]).includes('normal')
)))

function endpointLabel(endpoint: WorkflowNodeHandleSpec): string {
  return `${t('workflows.editor.normalEdge')} · ${endpoint.id}`
}

function hasConfiguration(options: ConfigurationSummary[], id: string): boolean {
  return Boolean(id && options.some((item) => item.id === id))
}

function updateCommand(event: Event): void {
  if (!props.node || props.node.data.nodeType !== 'command') return
  emit('updateCommand', props.node.id, (event.target as HTMLSelectElement).value)
}

function commitNodeId(): void {
  if (!props.node || ['start', 'end'].includes(props.node.data.nodeType)) return
  const value = nodeIdDraft.value.trim()
  if (!/^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(value)) {
    nodeIdError.value = t('workflows.editor.nodeIdInvalid')
    return
  }
  if (props.nodeIds.some((nodeId) => nodeId === value && nodeId !== props.node?.id)) {
    nodeIdError.value = t('workflows.editor.nodeIdDuplicate')
    return
  }
  nodeIdError.value = ''
  nodeIdDraft.value = value
  if (value !== props.node.id) emit('updateNodeId', props.node.id, value)
}

function blurNodeId(): void {
  commitNodeId()
  nodeIdFocused.value = false
}

function selectEdgeType(event: Event): void {
  if (!props.edge) return
  const edgeType = (event.target as HTMLSelectElement).value as WorkflowCanvasEdgeType
  if (props.edgeTypeOptions.includes(edgeType)) {
    emit('selectEdgeType', props.edge.id, edgeType)
  }
}

function selectEdgeSourceEndpoint(event: Event): void {
  if (props.edge) {
    emit('selectEdgeSourceEndpoint', props.edge.id, (event.target as HTMLSelectElement).value)
  }
}

function selectEdgeTargetEndpoint(event: Event): void {
  if (props.edge) {
    emit('selectEdgeTargetEndpoint', props.edge.id, (event.target as HTMLSelectElement).value)
  }
}
</script>

<template>
  <section class="workflow-tool-panel" aria-labelledby="workflow-inspector-title">
    <header class="workflow-tool-panel-header">
      <h2 id="workflow-inspector-title" class="workflow-tool-panel-title">
        {{ $t('workflows.editor.inspector') }}
      </h2>
    </header>
    <div class="workflow-tool-panel-body">
      <h3 class="workflow-inspector-context">{{ contextTitle }}</h3>
      <template v-if="node">
        <div v-if="node.data.nodeType === 'command'" class="workflow-inspector-row">
          <label class="workflow-inspector-label" for="workflow-node-id"><span>{{ $t('workflows.editor.nodeId') }}</span><span aria-hidden="true">:</span></label>
          <div class="workflow-inspector-control">
            <input id="workflow-node-id" v-model="nodeIdDraft" :aria-describedby="nodeIdDescribedBy" :aria-invalid="Boolean(nodeIdError)" class="form-control form-control-sm font-monospace" maxlength="64" type="text" @blur="blurNodeId" @focus="nodeIdFocused = true" @keydown.enter.prevent="commitNodeId">
            <div v-if="nodeIdFocused && !nodeIdError" id="workflow-node-id-help" class="form-text">{{ $t('workflows.editor.nodeIdHint') }}</div>
            <div v-if="nodeIdError" id="workflow-node-id-error" class="invalid-feedback d-block">{{ nodeIdError }}</div>
          </div>
        </div>
        <div v-else class="workflow-inspector-row">
          <span class="workflow-inspector-label"><span>{{ $t('workflows.editor.nodeId') }}</span><span aria-hidden="true">:</span></span>
          <span class="workflow-inspector-value">{{ node.id }}</span>
        </div>
        <div class="workflow-inspector-row"><span class="workflow-inspector-label"><span>{{ $t('workflows.editor.nodeType') }}</span><span aria-hidden="true">:</span></span><span class="workflow-inspector-value">{{ node.data.nodeType }}</span></div>
        <div class="workflow-inspector-row"><span class="workflow-inspector-label"><span>{{ $t('workflows.editor.typeVersion') }}</span><span aria-hidden="true">:</span></span><span class="workflow-inspector-value">1</span></div>
        <div v-for="endpoint in inputEndpoints" :key="`input-${endpoint.id}`" class="workflow-inspector-row"><span class="workflow-inspector-label"><span>{{ $t('workflows.editor.inputEndpoint') }}</span><span aria-hidden="true">:</span></span><span class="workflow-inspector-value">{{ endpointLabel(endpoint) }}</span></div>
        <div v-for="endpoint in outputEndpoints" :key="`output-${endpoint.id}`" class="workflow-inspector-row"><span class="workflow-inspector-label"><span>{{ $t('workflows.editor.outputEndpoint') }}</span><span aria-hidden="true">:</span></span><span class="workflow-inspector-value">{{ endpointLabel(endpoint) }}</span></div>
        <template v-if="node.data.nodeType === 'command'">
          <div class="workflow-inspector-row">
            <label class="workflow-inspector-label" for="workflow-node-command"><span>{{ $t('workflows.editor.commandConfig') }}</span><span aria-hidden="true">:</span></label>
            <select id="workflow-node-command" class="form-select form-select-sm workflow-inspector-select" :value="node.data.commandId" @change="updateCommand">
              <option v-if="commands.length === 0" value="">{{ $t('workflows.editor.noCommands') }}</option>
              <option v-if="node.data.commandId && !hasConfiguration(commands, node.data.commandId)" disabled :value="node.data.commandId">{{ $t('common.missingConfiguration', { id: node.data.commandId }) }}</option>
              <option v-for="command in commands" :key="command.id" :value="command.id">{{ command.name }}</option>
            </select>
          </div>
          <button class="workflow-inspector-delete" type="button" @click="emit('removeNode', node.id)"><i class="bi bi-trash" aria-hidden="true" />{{ $t('workflows.editor.removeCommand') }}</button>
        </template>
        <p v-else class="workflow-inspector-note">{{ $t('workflows.editor.fixedNode') }}</p>
      </template>
      <template v-else-if="edge">
        <div class="workflow-inspector-row"><label class="workflow-inspector-label" for="workflow-edge-type"><span>{{ $t('workflows.editor.edgeType') }}</span><span aria-hidden="true">:</span></label><select id="workflow-edge-type" class="form-select form-select-sm workflow-inspector-select" name="edge-type" :value="edge.data?.edgeType" @change="selectEdgeType"><option v-for="edgeType in edgeTypeOptions" :key="edgeType" :value="edgeType">{{ $t('workflows.editor.normalEdge') }}</option></select></div>
        <div class="workflow-inspector-row"><label class="workflow-inspector-label" for="workflow-edge-source-endpoint"><span>{{ $t('workflows.editor.source') }}</span><span aria-hidden="true">:</span></label><select id="workflow-edge-source-endpoint" class="form-select form-select-sm workflow-inspector-select" name="source-endpoint" :value="edge.sourceHandle" @change="selectEdgeSourceEndpoint"><option v-for="endpoint in edgeSourceOptions" :key="endpoint.id" :value="endpoint.id">{{ edge.source }} · {{ endpointLabel(endpoint) }}</option></select></div>
        <div class="workflow-inspector-row"><label class="workflow-inspector-label" for="workflow-edge-target-endpoint"><span>{{ $t('workflows.editor.target') }}</span><span aria-hidden="true">:</span></label><select id="workflow-edge-target-endpoint" class="form-select form-select-sm workflow-inspector-select" name="target-endpoint" :value="edge.targetHandle" @change="selectEdgeTargetEndpoint"><option v-for="endpoint in edgeTargetOptions" :key="endpoint.id" :value="endpoint.id">{{ edge.target }} · {{ endpointLabel(endpoint) }}</option></select></div>
        <button class="workflow-inspector-delete" type="button" @click="emit('removeEdge', edge.id)"><i class="bi bi-trash" aria-hidden="true" />{{ $t('workflows.editor.removeEdge') }}</button>
      </template>
      <template v-else>
        <div class="workflow-inspector-row"><span class="workflow-inspector-label"><span>{{ $t('workflows.fields.name') }}</span><span aria-hidden="true">:</span></span><span class="workflow-inspector-value">{{ workflowName }}</span></div>
        <div class="workflow-inspector-row"><span class="workflow-inspector-label"><span>{{ $t('workflows.editor.stateContract') }}</span><span aria-hidden="true">:</span></span><span class="workflow-inspector-value">{{ stateContract }}</span></div>
      </template>
    </div>
  </section>
</template>
