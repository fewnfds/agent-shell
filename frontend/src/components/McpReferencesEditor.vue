<script setup lang="ts">
import { LteButton } from '@adminlte/vue'
import { useI18n } from 'vue-i18n'

import type { ConfigurationSummary, McpReference } from '@/api'
import { blankMcpReference } from '@/domain/mcp'

export interface McpRequirementOption extends ConfigurationSummary {
  description?: string
  namespace?: string
}

const props = defineProps<{
  references: McpReference[]
  requirements: McpRequirementOption[]
  idPrefix: string
}>()
const emit = defineEmits<{
  'update:references': [references: McpReference[]]
}>()
const { t } = useI18n()

function update(mutator: (next: McpReference[]) => void): void {
  const next = props.references.map((reference) => ({
    requirement_id: reference.requirement_id,
    tool_selection: {
      mode: reference.tool_selection.mode,
      tools: [...reference.tool_selection.tools],
    },
  }))
  mutator(next)
  emit('update:references', next)
}

function addReference(): void {
  emit('update:references', [...props.references, blankMcpReference()])
}

function removeReference(index: number): void {
  update((next) => { next.splice(index, 1) })
}

function moveReference(index: number, offset: -1 | 1): void {
  const target = index + offset
  if (target < 0 || target >= props.references.length) return
  update((next) => {
    ;[next[index], next[target]] = [next[target]!, next[index]!]
  })
}

function setRequirement(index: number, requirementId: string): void {
  update((next) => { next[index]!.requirement_id = requirementId })
}

function setMode(index: number, mode: 'all' | 'include'): void {
  update((next) => {
    next[index]!.tool_selection = {
      mode,
      tools: mode === 'include' ? [''] : [],
    }
  })
}

function addTool(index: number): void {
  update((next) => { next[index]!.tool_selection.tools.push('') })
}

function setTool(index: number, toolIndex: number, value: string): void {
  update((next) => { next[index]!.tool_selection.tools[toolIndex] = value })
}

function removeTool(index: number, toolIndex: number): void {
  update((next) => { next[index]!.tool_selection.tools.splice(toolIndex, 1) })
}

function requirementFor(id: string): McpRequirementOption | undefined {
  return props.requirements.find((item) => item.id === id)
}

function requirementDisabled(id: string, index: number): boolean {
  return props.references.some((reference, itemIndex) => (
    itemIndex !== index && reference.requirement_id === id
  ))
}
</script>

<template>
  <section class="card mb-3" :aria-labelledby="`${idPrefix}-title`">
    <header class="card-header d-flex flex-wrap align-items-center gap-2">
      <h2 :id="`${idPrefix}-title`" class="card-title mb-0">{{ t('mcp.references.title') }}</h2>
      <LteButton class="icon-action-button ms-auto" data-action="add-mcp-reference" :aria-label="t('mcp.references.add')" :title="t('mcp.references.add')" size="sm" type="button" @click="addReference"><i class="bi bi-plus-lg" aria-hidden="true" /></LteButton>
    </header>
    <div v-if="!references.length" class="card-body text-body-secondary">{{ t('mcp.references.empty') }}</div>
    <div v-else class="card-body">
      <div class="row g-3">
        <div v-for="(reference, index) in references" :key="index" class="col-lg-6" data-testid="mcp-reference-row">
          <div class="border rounded p-3 h-100">
            <div class="d-flex align-items-center gap-2 mb-3">
              <span class="badge text-bg-secondary">{{ index + 1 }}</span>
              <div class="d-flex gap-1 ms-auto" role="group">
                <LteButton class="icon-action-button" :disabled="index === 0" :aria-label="t('common.moveUp')" :title="t('common.moveUp')" size="sm" type="button" @click="moveReference(index, -1)"><i class="bi bi-arrow-up" aria-hidden="true" /></LteButton>
                <LteButton class="icon-action-button" :disabled="index === references.length - 1" :aria-label="t('common.moveDown')" :title="t('common.moveDown')" size="sm" type="button" @click="moveReference(index, 1)"><i class="bi bi-arrow-down" aria-hidden="true" /></LteButton>
                <LteButton class="icon-action-button" :aria-label="t('common.remove')" :title="t('common.remove')" size="sm" type="button" @click="removeReference(index)"><i class="bi bi-trash" aria-hidden="true" /></LteButton>
              </div>
            </div>

            <label class="form-label" :for="`${idPrefix}-requirement-${index}`">{{ t('mcp.references.requirement') }}</label>
            <select :id="`${idPrefix}-requirement-${index}`" class="form-select mb-2" data-testid="mcp-requirement-reference" :value="reference.requirement_id" @change="setRequirement(index, ($event.target as HTMLSelectElement).value)">
              <option disabled value="">{{ t('common.chooseConfiguration') }}</option>
              <option v-if="reference.requirement_id && !requirementFor(reference.requirement_id)" disabled :value="reference.requirement_id">{{ t('common.missingConfiguration', { id: reference.requirement_id }) }}</option>
              <option v-for="requirement in requirements" :key="requirement.id" :disabled="requirementDisabled(requirement.id, index)" :value="requirement.id">{{ requirement.name }}<template v-if="requirement.namespace"> · {{ requirement.namespace }}</template></option>
            </select>
            <p v-if="requirementFor(reference.requirement_id)?.description" class="form-text">{{ requirementFor(reference.requirement_id)?.description }}</p>

            <label class="form-label" :for="`${idPrefix}-mode-${index}`">{{ t('mcp.references.toolSelection') }}</label>
            <select :id="`${idPrefix}-mode-${index}`" class="form-select" data-testid="mcp-tool-selection-mode" :value="reference.tool_selection.mode" @change="setMode(index, ($event.target as HTMLSelectElement).value as 'all' | 'include')">
              <option value="all">{{ t('mcp.references.allTools') }}</option>
              <option value="include">{{ t('mcp.references.selectedTools') }}</option>
            </select>

            <div v-if="reference.tool_selection.mode === 'include'" class="mt-3">
              <div class="d-flex align-items-center gap-2 mb-2">
                <span class="form-label mb-0">{{ t('mcp.references.rawToolNames') }}</span>
                <LteButton class="icon-action-button ms-auto" :aria-label="t('mcp.references.addTool')" :title="t('mcp.references.addTool')" size="sm" type="button" @click="addTool(index)"><i class="bi bi-plus-lg" aria-hidden="true" /></LteButton>
              </div>
              <div v-for="(tool, toolIndex) in reference.tool_selection.tools" :key="toolIndex" class="input-group mb-2">
                <input class="form-control font-monospace" data-testid="mcp-raw-tool-name" :value="tool" :placeholder="t('mcp.references.rawToolPlaceholder')" @input="setTool(index, toolIndex, ($event.target as HTMLInputElement).value)">
                <LteButton class="icon-action-button" :aria-label="t('common.remove')" :title="t('common.remove')" type="button" @click="removeTool(index, toolIndex)"><i class="bi bi-trash" aria-hidden="true" /></LteButton>
              </div>
              <p class="form-text mb-0">{{ t('mcp.references.toolNameHint', { namespace: requirementFor(reference.requirement_id)?.namespace || 'namespace' }) }}</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
