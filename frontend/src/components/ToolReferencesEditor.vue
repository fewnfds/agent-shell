<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import ReferenceCardsEditor from '@/components/ReferenceCardsEditor.vue'
import {
  type StoredBlock,
  type ToolReference,
} from '@/domain/agents'

const props = defineProps<{
  references: ToolReference[]
  tools: StoredBlock[]
  idPrefix: string
}>()
const emit = defineEmits<{
  'update:references': [references: ToolReference[]]
}>()

const { t } = useI18n()
const referenceIds = () => props.references.map((reference) => reference.tool_id)
</script>

<template>
  <ReferenceCardsEditor
    :references="referenceIds()"
    :options="tools.map((tool) => ({ id: tool.id, label: tool.name }))"
    kind="tool"
    :id-prefix="idPrefix"
    :title="t('agents.tool.referencesTitle')"
    :add-label="t('agents.tool.addReference')"
    :empty-text="t('agents.tool.noReferences')"
    :reference-label="t('agents.tool.reference')"
    @update:references="emit('update:references', $event.map((tool_id) => ({ tool_id })))"
  />
</template>
