<script setup lang="ts">
import { LteButton } from '@adminlte/vue'
import { useI18n } from 'vue-i18n'

import type {
  AsyncSubagentReference,
  MainAgentProfile,
} from '@/domain/agents'

const props = defineProps<{
  references: AsyncSubagentReference[]
  mainAgents: MainAgentProfile[]
  currentAgentId: string
}>()
const emit = defineEmits<{
  'update:references': [references: AsyncSubagentReference[]]
}>()

const { t } = useI18n()

function addReference(): void {
  emit('update:references', [
    ...props.references,
    { main_agent_id: '', name: '', description: '' },
  ])
}

function updateReference(
  index: number,
  field: keyof AsyncSubagentReference,
  value: string,
): void {
  emit('update:references', props.references.map((reference, itemIndex) => (
    itemIndex === index ? { ...reference, [field]: value } : reference
  )))
}

function removeReference(index: number): void {
  emit('update:references', props.references.filter((_, itemIndex) => itemIndex !== index))
}

function moveReference(index: number, offset: -1 | 1): void {
  const target = index + offset
  if (target < 0 || target >= props.references.length) return
  const next = [...props.references]
  ;[next[index], next[target]] = [next[target]!, next[index]!]
  emit('update:references', next)
}

function targetFor(id: string): MainAgentProfile | undefined {
  return props.mainAgents.find((agent) => agent.id === id)
}
</script>

<template>
  <section class="card mb-3" aria-labelledby="async-subagent-references-title">
    <header class="card-header d-flex flex-wrap align-items-center justify-content-between gap-2">
      <h2 id="async-subagent-references-title" class="card-title mb-0">
        {{ t('agents.asyncSubagent.referencesTitle') }}
      </h2>
      <LteButton
        class="icon-action-button ms-auto"
        data-action="add-async-subagent-reference"
        :aria-label="t('agents.asyncSubagent.addReference')"
        :title="t('agents.asyncSubagent.addReference')"
        size="sm"
        type="button"
        @click="addReference"
      >
        <i class="bi bi-plus-lg" aria-hidden="true" />
      </LteButton>
    </header>
    <div v-if="references.length === 0" class="card-body text-body-secondary">
      {{ t('agents.asyncSubagent.noReferences') }}
    </div>
    <div v-else class="list-group list-group-flush">
      <div
        v-for="(reference, index) in references"
        :key="index"
        class="list-group-item"
        data-testid="async-subagent-reference-row"
      >
        <div class="d-flex align-items-center gap-2 mb-3">
          <span class="font-monospace text-body-secondary">
            {{ t('common.numberedItem', { index: index + 1 }) }}
          </span>
          <div class="d-flex gap-1 ms-auto" role="group">
            <LteButton
              class="icon-action-button"
              data-action="move-async-subagent-reference-up"
              :aria-label="t('common.moveUp')"
              :title="t('common.moveUp')"
              :disabled="index === 0"
              size="sm"
              type="button"
              @click="moveReference(index, -1)"
            >
              <i class="bi bi-arrow-up" aria-hidden="true" />
            </LteButton>
            <LteButton
              class="icon-action-button"
              data-action="move-async-subagent-reference-down"
              :aria-label="t('common.moveDown')"
              :title="t('common.moveDown')"
              :disabled="index === references.length - 1"
              size="sm"
              type="button"
              @click="moveReference(index, 1)"
            >
              <i class="bi bi-arrow-down" aria-hidden="true" />
            </LteButton>
            <LteButton
              class="icon-action-button"
              data-action="remove-async-subagent-reference"
              :aria-label="t('common.remove')"
              :title="t('common.remove')"
              size="sm"
              type="button"
              @click="removeReference(index)"
            >
              <i class="bi bi-trash" aria-hidden="true" />
            </LteButton>
          </div>
        </div>
        <div class="row g-3">
          <div class="col-lg-4">
            <label class="form-label" :for="`async-subagent-target-${index}`">
              {{ t('agents.asyncSubagent.target') }}
            </label>
            <select
              :id="`async-subagent-target-${index}`"
              class="form-select"
              data-testid="async-subagent-target"
              :value="reference.main_agent_id"
              @change="updateReference(index, 'main_agent_id', ($event.target as HTMLSelectElement).value)"
            >
              <option disabled value="">{{ t('common.chooseConfiguration') }}</option>
              <option
                v-if="reference.main_agent_id && !targetFor(reference.main_agent_id)"
                disabled
                :value="reference.main_agent_id"
              >
                {{ t('common.missingConfiguration', { id: reference.main_agent_id }) }}
              </option>
              <option
                v-for="agent in mainAgents"
                :key="agent.id"
                :disabled="agent.id === currentAgentId"
                :value="agent.id"
              >
                {{ agent.name }}
              </option>
            </select>
          </div>
          <div class="col-lg-4">
            <label class="form-label" :for="`async-subagent-name-${index}`">
              {{ t('agents.asyncSubagent.name') }}
            </label>
            <input
              :id="`async-subagent-name-${index}`"
              class="form-control"
              data-testid="async-subagent-name"
              required
              type="text"
              :value="reference.name"
              @input="updateReference(index, 'name', ($event.target as HTMLInputElement).value)"
            >
          </div>
          <div class="col-lg-4">
            <label class="form-label" :for="`async-subagent-description-${index}`">
              {{ t('agents.asyncSubagent.description') }}
            </label>
            <textarea
              :id="`async-subagent-description-${index}`"
              class="form-control"
              data-testid="async-subagent-description"
              required
              rows="2"
              :value="reference.description"
              @input="updateReference(index, 'description', ($event.target as HTMLTextAreaElement).value)"
            />
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
