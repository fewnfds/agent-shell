<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import ReferenceCardsEditor from '@/components/ReferenceCardsEditor.vue'
import {
  type SubagentProfile,
  type SubagentReference,
} from '@/domain/agents'

const props = defineProps<{
  references: SubagentReference[]
  profiles: SubagentProfile[]
  pathPrefix?: string
}>()
const emit = defineEmits<{
  'update:references': [references: SubagentReference[]]
}>()

const { t } = useI18n()
const referenceIds = () => props.references.map((reference) => reference.subagent_id)
</script>

<template>
  <ReferenceCardsEditor
    :references="referenceIds()"
    :options="profiles.map((profile) => ({
      id: profile.id,
      label: `${profile.component_name}${t('common.itemSeparator')}${profile.name}`,
      description: profile.description,
    }))"
    kind="subagent"
    id-prefix="subagent-reference"
    :title="t('agents.mainAgent.referencesTitle')"
    :add-label="t('agents.mainAgent.addReference')"
    :empty-text="t('agents.mainAgent.noReferences')"
    :reference-label="t('agents.mainAgent.reference')"
    @update:references="emit('update:references', $event.map((subagent_id) => ({ subagent_id })))"
  />
</template>
