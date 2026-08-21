<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import ReferenceCardsEditor from '@/components/ReferenceCardsEditor.vue'
import {
  type MiddlewareReference,
  type StoredBlock,
} from '@/domain/agents'

const props = defineProps<{
  references: MiddlewareReference[]
  middlewares: StoredBlock[]
  idPrefix: string
}>()
const emit = defineEmits<{
  'update:references': [references: MiddlewareReference[]]
}>()

const { t } = useI18n()
const referenceIds = () => props.references.map((reference) => reference.middleware_id)
</script>

<template>
  <ReferenceCardsEditor
    :references="referenceIds()"
    :options="middlewares.map((middleware) => ({ id: middleware.id, label: middleware.name }))"
    kind="middleware"
    :id-prefix="idPrefix"
    :title="t('agents.middleware.referencesTitle')"
    :add-label="t('agents.middleware.addReference')"
    :empty-text="t('agents.middleware.noReferences')"
    :reference-label="t('agents.middleware.reference')"
    @update:references="emit('update:references', $event.map((middleware_id) => ({ middleware_id })))"
  />
</template>
