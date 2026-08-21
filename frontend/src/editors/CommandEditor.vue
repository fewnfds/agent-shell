<script setup lang="ts">
import type { LocalizedMessagePayload } from '@/api'
import PythonPackageEditor from '@/components/PythonPackageEditor.vue'
import {
  type CommandCatalogItem,
  type CommandDefaults,
  type CommandDraft,
} from '@/domain/blocks'
import type { PythonPackageDraftState } from '@/domain/blocks/pythonPackage'
import { useEditorModel } from './shared/useEditorModel'

const props = withDefaults(defineProps<{
  modelValue: CommandDraft
  defaults?: CommandDefaults
  catalog?: CommandCatalogItem[]
  errors?: Record<string, LocalizedMessagePayload>
  loading?: boolean
}>(), {
  catalog: () => [],
  errors: () => ({}),
  loading: false,
})
const emit = defineEmits<{
  'update:modelValue': [value: CommandDraft]
  refresh: []
}>()
const draft = useEditorModel(() => props.modelValue, (value) => emit('update:modelValue', value))

function updatePackage(value: PythonPackageDraftState): void {
  draft.python_package = value.python_package
  draft.python_package_template = value.python_package_template
  draft.python_package_inspection = value.python_package_inspection
}
</script>

<template>
  <div data-editor="command">
    <PythonPackageEditor
      :catalog="catalog"
      :errors="errors"
      id-prefix="command"
      :loading="loading"
      :model-value="draft"
      :saved="Boolean(draft.id)"
      @refresh="emit('refresh')"
      @update:model-value="updatePackage"
    />
  </div>
</template>
