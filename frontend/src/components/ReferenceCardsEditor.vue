<script setup lang="ts">
import { LteButton } from '@adminlte/vue'
import { useI18n } from 'vue-i18n'

export interface ReferenceCardOption {
  id: string
  label: string
  description?: string
}

const props = defineProps<{
  references: string[]
  options: ReferenceCardOption[]
  kind: 'tool' | 'middleware' | 'subagent'
  idPrefix: string
  title: string
  addLabel: string
  emptyText: string
  referenceLabel: string
}>()
const emit = defineEmits<{
  'update:references': [references: string[]]
}>()

const { t } = useI18n()

function addReference(): void {
  emit('update:references', [...props.references, ''])
}

function updateReference(index: number, value: string): void {
  emit('update:references', props.references.map((reference, itemIndex) => (
    itemIndex === index ? value : reference
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

function optionDisabled(optionId: string, index: number): boolean {
  return props.references.some((reference, itemIndex) => (
    itemIndex !== index && reference === optionId
  ))
}

function optionFor(referenceId: string): ReferenceCardOption | undefined {
  return props.options.find((option) => option.id === referenceId)
}
</script>

<template>
  <section class="card mb-3" :aria-labelledby="`${idPrefix}-title`">
    <header class="card-header d-flex flex-wrap align-items-center justify-content-between gap-2">
      <h2 :id="`${idPrefix}-title`" class="card-title mb-0">{{ title }}</h2>
      <LteButton
        class="icon-action-button ms-auto"
        :data-action="`add-${kind}-reference`"
        :aria-label="addLabel"
        :title="addLabel"
        size="sm"
        theme="success"
        type="button"
        @click="addReference"
      >
        <i class="bi bi-plus-lg" aria-hidden="true" />
      </LteButton>
    </header>
    <div v-if="references.length === 0" class="card-body text-body-secondary">
      {{ emptyText }}
    </div>
    <div v-else class="card-body">
      <div class="row g-3">
        <div
          v-for="(reference, index) in references"
          :key="index"
          class="col-md-6 col-lg-4"
          :data-testid="`${kind}-reference-row`"
        >
          <div class="border rounded p-3 h-100">
            <div class="d-flex align-items-center gap-2 mb-2">
              <span class="badge text-bg-secondary">{{ index + 1 }}</span>
              <div class="d-flex gap-1 ms-auto" role="group">
                <LteButton
                  class="icon-action-button"
                  :data-action="`move-${kind}-reference-up`"
                  :aria-label="t('common.moveUp')"
                  :title="t('common.moveUp')"
                  :disabled="index === 0"
                  size="sm"
                  theme="secondary"
                  type="button"
                  @click="moveReference(index, -1)"
                >
                  <i class="bi bi-arrow-up" aria-hidden="true" />
                </LteButton>
                <LteButton
                  class="icon-action-button"
                  :data-action="`move-${kind}-reference-down`"
                  :aria-label="t('common.moveDown')"
                  :title="t('common.moveDown')"
                  :disabled="index === references.length - 1"
                  size="sm"
                  theme="secondary"
                  type="button"
                  @click="moveReference(index, 1)"
                >
                  <i class="bi bi-arrow-down" aria-hidden="true" />
                </LteButton>
                <LteButton
                  class="icon-action-button"
                  :data-action="`remove-${kind}-reference`"
                  :aria-label="t('common.remove')"
                  :title="t('common.remove')"
                  size="sm"
                  theme="danger"
                  type="button"
                  @click="removeReference(index)"
                >
                  <i class="bi bi-trash" aria-hidden="true" />
                </LteButton>
              </div>
            </div>
            <label class="visually-hidden" :for="`${idPrefix}-${index}`">
              {{ referenceLabel }}
            </label>
            <select
              :id="`${idPrefix}-${index}`"
              class="form-select"
              :data-testid="`${kind}-reference`"
              :value="reference"
              @change="updateReference(index, ($event.target as HTMLSelectElement).value)"
            >
              <option disabled value="">{{ t('common.chooseConfiguration') }}</option>
              <option
                v-for="option in options"
                :key="option.id"
                :disabled="optionDisabled(option.id, index)"
                :value="option.id"
              >
                {{ option.label }}
              </option>
            </select>
            <p v-if="optionFor(reference)?.description" class="form-text mb-0">
              {{ optionFor(reference)?.description }}
            </p>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
