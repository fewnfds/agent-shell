<script setup lang="ts">
import { LteButton } from '@adminlte/vue'
import { useI18n } from 'vue-i18n'

import FormField from '@/components/FormField.vue'
import type { PiiDefaults, PiiDraft } from '@/domain/blocks'
import { useEditorModel } from './shared/useEditorModel'

const props = defineProps<{ modelValue: PiiDraft, defaults: PiiDefaults }>()
const emit = defineEmits<{ 'update:modelValue': [value: PiiDraft] }>()
const { t } = useI18n()
const draft = useEditorModel(() => props.modelValue, (value) => emit('update:modelValue', value))
const scopes = ['apply_to_input', 'apply_to_output', 'apply_to_tool_results'] as const

function addRule(): void {
  draft.rules.push({ ...props.defaults.default_value.rules[0]! })
}

function moveRule(index: number, offset: number): void {
  const rules = [...draft.rules]
  const [rule] = rules.splice(index, 1)
  rules.splice(index + offset, 0, rule!)
  draft.rules = rules
}

function setDetector(index: number, event: Event): void {
  draft.rules[index]!.detector = (event.target as HTMLInputElement).checked ? '' : null
}
</script>

<template>
  <div data-editor="pii">
    <div class="d-flex align-items-center mb-3">
      <LteButton class="action-button ms-auto" data-action="add-rule" type="button" @click="addRule">
        <i class="bi bi-plus-lg" aria-hidden="true" />
        {{ t('editors.pii.addRule') }}
      </LteButton>
    </div>
    <datalist id="pii-types">
      <option v-for="piiType in defaults.pii_types" :key="piiType" :value="piiType" />
    </datalist>
    <section v-for="(rule, index) in draft.rules" :key="index" class="card mb-3" data-testid="pii-rule">
      <header class="card-header d-flex align-items-center gap-2">
        <h3 class="card-title">{{ t('editors.pii.rule', { number: index + 1 }) }}</h3>
        <div class="d-flex gap-2 ms-auto">
          <LteButton class="icon-action-button" type="button" data-action="move-up" :disabled="index === 0" :aria-label="t('editors.pii.moveUp')" :title="t('editors.pii.moveUp')" @click="moveRule(index, -1)">
            <i class="bi bi-arrow-up" aria-hidden="true" />
          </LteButton>
          <LteButton class="icon-action-button" type="button" data-action="move-down" :disabled="index === draft.rules.length - 1" :aria-label="t('editors.pii.moveDown')" :title="t('editors.pii.moveDown')" @click="moveRule(index, 1)">
            <i class="bi bi-arrow-down" aria-hidden="true" />
          </LteButton>
          <LteButton class="icon-action-button" type="button" data-action="delete-rule" :aria-label="t('common.delete')" :title="t('common.delete')" @click="draft.rules.splice(index, 1)">
            <i class="bi bi-trash" aria-hidden="true" />
          </LteButton>
        </div>
      </header>
      <div class="card-body">
        <div class="row g-3">
          <div class="col-lg-6">
            <FormField :control-id="`pii-type-${index}`" :field-path="`rules.${index}.pii_type`" label-key="fields.pii_type">
              <input :id="`pii-type-${index}`" v-model="rule.pii_type" class="form-control" list="pii-types" type="text">
            </FormField>
          </div>
          <div class="col-lg-6">
            <FormField :control-id="`pii-strategy-${index}`" :field-path="`rules.${index}.strategy`" label-key="fields.pii_strategy">
              <select :id="`pii-strategy-${index}`" v-model="rule.strategy" class="form-select">
                <option v-for="strategy in defaults.strategies" :key="strategy" :value="strategy">{{ t(`editors.pii.strategies.${strategy}`) }}</option>
              </select>
            </FormField>
          </div>
          <div v-for="scope in scopes" :key="scope" class="col-lg-4">
            <FormField :control-id="`pii-${scope}-${index}`" :field-path="`rules.${index}.${scope}`" :label-key="`fields.${scope}`">
              <select :id="`pii-${scope}-${index}`" v-model="rule[scope]" class="form-select">
                <option :value="true">{{ t('common.yes') }}</option>
                <option :value="false">{{ t('common.no') }}</option>
              </select>
            </FormField>
          </div>
          <div class="col-12">
            <div class="form-check form-switch">
              <input :id="`pii-custom-detector-${index}`" class="form-check-input" type="checkbox" :checked="rule.detector !== null" @change="setDetector(index, $event)">
              <label class="form-check-label" :for="`pii-custom-detector-${index}`">{{ t('editors.pii.customDetector') }}</label>
            </div>
          </div>
          <div v-if="rule.detector !== null" class="col-12">
            <FormField :control-id="`pii-detector-${index}`" :field-path="`rules.${index}.detector`" label-key="fields.detector">
              <textarea :id="`pii-detector-${index}`" v-model="rule.detector" class="form-control font-monospace" rows="3" spellcheck="false" />
            </FormField>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>
