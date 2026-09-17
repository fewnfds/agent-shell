<script setup lang="ts">
import { LteTextarea } from '@adminlte/vue'
import { useI18n } from 'vue-i18n'

import type { PythonSchemaDraft } from '@/domain/blocks'

import { useEditorModel } from './shared/useEditorModel'

const props = defineProps<{ modelValue: PythonSchemaDraft }>()
const emit = defineEmits<{ 'update:modelValue': [value: PythonSchemaDraft] }>()
const { t } = useI18n()
const draft = useEditorModel(
  () => props.modelValue,
  (value) => emit('update:modelValue', value),
)
</script>

<template>
  <div data-editor="python-schema">
    <section class="card mb-3">
      <header class="card-header">
        <h3 class="card-title">
          {{ t('capabilities.python-schema.label') }}
        </h3>
      </header>
      <div class="card-body">
        <label class="form-label" for="python-schema-source">
          {{ t('editors.pythonSchema.source') }}
        </label>
        <LteTextarea
          id="python-schema-source"
          v-model="draft.source"
          :aria-label="t('editors.pythonSchema.source')"
          :placeholder="t('editors.pythonSchema.placeholder')"
          class="font-monospace"
          :rows="22"
          spellcheck="false"
        />
      </div>
    </section>
  </div>
</template>
