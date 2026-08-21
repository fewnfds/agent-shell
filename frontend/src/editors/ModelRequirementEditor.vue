<script setup lang="ts">
import { LteTextarea } from '@adminlte/vue'
import { useI18n } from 'vue-i18n'
import type { ModelRequirementDraft } from '@/domain/blocks'
import { useEditorModel } from './shared/useEditorModel'

const props = defineProps<{ modelValue: ModelRequirementDraft }>()
const emit = defineEmits<{ 'update:modelValue': [value: ModelRequirementDraft] }>()
const { t } = useI18n()
const draft = useEditorModel(() => props.modelValue, (value) => emit('update:modelValue', value))
</script>

<template>
  <div data-editor="model-requirement">
    <section class="card mb-3">
      <header class="card-header"><h3 class="card-title">{{ t('capabilities.model-requirement.label') }}</h3></header>
      <div class="card-body">
        <label class="form-label" for="model-requirement-description">{{ t('editors.modelRequirement.description') }}</label>
        <LteTextarea id="model-requirement-description" v-model="draft.description" :rows="10" :placeholder="t('editors.modelRequirement.placeholder')" />
      </div>
    </section>
  </div>
</template>
