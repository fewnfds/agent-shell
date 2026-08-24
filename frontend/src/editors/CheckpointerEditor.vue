<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import FormField from '@/components/FormField.vue'
import type { CheckpointDurability, CheckpointerDraft } from '@/domain/blocks'

import { useEditorModel } from './shared/useEditorModel'

const props = defineProps<{ modelValue: CheckpointerDraft }>()
const emit = defineEmits<{ 'update:modelValue': [value: CheckpointerDraft] }>()
const { t } = useI18n()
const draft = useEditorModel(() => props.modelValue, (value) => emit('update:modelValue', value))
const durabilityValues: CheckpointDurability[] = ['exit', 'async', 'sync']
</script>

<template>
  <div data-editor="checkpointer">
    <FormField
      control-id="checkpointer-durability"
      field-path="durability"
      :hint="t(`editors.checkpointer.durability.${draft.durability}.hint`)"
    >
      <select id="checkpointer-durability" v-model="draft.durability" class="form-select">
        <option v-for="durability in durabilityValues" :key="durability" :value="durability">
          {{ t(`editors.checkpointer.durability.${durability}.label`) }}
        </option>
      </select>
    </FormField>
  </div>
</template>
