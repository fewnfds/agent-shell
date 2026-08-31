<script setup lang="ts">
import { LteInput, LteTextarea } from '@adminlte/vue'
import { useI18n } from 'vue-i18n'

import type { McpRequirementDraft } from '@/domain/blocks'

import { useEditorModel } from './shared/useEditorModel'

const props = defineProps<{ modelValue: McpRequirementDraft }>()
const emit = defineEmits<{ 'update:modelValue': [value: McpRequirementDraft] }>()
const { t } = useI18n()
const draft = useEditorModel(() => props.modelValue, (value) => emit('update:modelValue', value))
</script>

<template>
  <div data-editor="mcp-requirement">
    <section class="card mb-3">
      <header class="card-header"><h3 class="card-title">{{ t('capabilities.mcp-requirement.label') }}</h3></header>
      <div class="card-body">
        <div class="mb-3">
          <label class="form-label" for="mcp-requirement-namespace">{{ t('editors.mcpRequirement.namespace') }}</label>
          <LteInput
            id="mcp-requirement-namespace"
            v-model="draft.namespace"
            autocomplete="off"
            class="font-monospace"
            :placeholder="t('editors.mcpRequirement.namespacePlaceholder')"
          />
          <p class="form-text">{{ t('editors.mcpRequirement.namespaceHint') }}</p>
        </div>
        <label class="form-label" for="mcp-requirement-description">{{ t('editors.mcpRequirement.description') }}</label>
        <LteTextarea
          id="mcp-requirement-description"
          v-model="draft.description"
          :rows="8"
          :placeholder="t('editors.mcpRequirement.descriptionPlaceholder')"
        />
      </div>
    </section>
  </div>
</template>
