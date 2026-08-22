<script setup lang="ts">
import { LteButton, LteTextarea } from '@adminlte/vue'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { LocalizedMessagePayload, SkillPackageInspection } from '@/api'
import type { SkillCatalogItem, SkillDefaults, SkillDraft } from '@/domain/blocks'
import { useEditorModel } from './shared/useEditorModel'

const props = withDefaults(defineProps<{
  modelValue: SkillDraft
  defaults: SkillDefaults
  catalog?: SkillCatalogItem[]
  errors?: Record<string, LocalizedMessagePayload>
  loading?: boolean
  privatePackage?: SkillPackageInspection | null
  privateLoading?: boolean
  mutating?: boolean
}>(), {
  catalog: () => [], errors: () => ({}), loading: false, privatePackage: null,
  privateLoading: false, mutating: false,
})
const emit = defineEmits<{
  'update:modelValue': [value: SkillDraft]
  refresh: []
  'add-skill': [templatePath: string]
  'remove-skill': [folder: string]
}>()
const { t } = useI18n()
const draft = useEditorModel(() => props.modelValue, (value) => emit('update:modelValue', value))
const pendingTemplates = computed(() => {
  const selected = new Set(draft.skill_template_paths)
  return props.catalog.filter((skill) => selected.has(skill.template_path))
})
const privateNames = computed(() => new Set(
  props.privatePackage?.catalog.map((skill) => skill.name) ?? pendingTemplates.value.map((skill) => skill.name),
))
function resourceError(error: LocalizedMessagePayload): string { return t(error.message_key, error.message_args ?? {}) }
function addSkill(skill: SkillCatalogItem): void {
  if (draft.id) emit('add-skill', skill.template_path)
  else if (!privateNames.value.has(skill.name)) draft.skill_template_paths = [...draft.skill_template_paths, skill.template_path]
}
function removeSkill(folder: string): void {
  if (draft.id) emit('remove-skill', folder)
  else draft.skill_template_paths = draft.skill_template_paths.filter((path) => path !== folder)
}
function removalKey(skill: { folder: string; template_path?: string }): string {
  return draft.id ? skill.folder : (skill.template_path ?? skill.folder)
}
</script>

<template>
  <div data-editor="skill">
    <section class="card mb-3">
      <header class="card-header"><h3 class="card-title">{{ t('editors.skill.instructionTitle') }}</h3></header>
      <div class="card-body">
        <div class="form-check form-switch mb-3">
          <input id="skill-system-prompt-enabled" v-model="draft.system_prompt_enabled" class="form-check-input" data-testid="skill-system-prompt-enabled" type="checkbox">
          <label class="form-check-label" for="skill-system-prompt-enabled">{{ t('editors.skill.systemPromptEnabled') }}</label>
        </div>
        <div class="d-flex justify-content-end mb-3"><LteButton class="action-button" data-action="restore-default" :disabled="!draft.system_prompt_enabled" @click="draft.instruction_override = defaults.system_prompt"><i class="bi bi-arrow-clockwise" aria-hidden="true" />{{ t('editors.common.restoreDefault') }}</LteButton></div>
        <LteTextarea v-model="draft.instruction_override" :aria-label="t('editors.skill.instructionTitle')" :disabled="!draft.system_prompt_enabled" :rows="16" />
        <p v-if="draft.system_prompt_enabled && defaults.required_placeholders?.length" class="form-text" data-testid="skill-required-placeholders">{{ t('editors.skill.requiredPlaceholdersHint', { placeholders: defaults.required_placeholders.join(' ') }) }}</p>
      </div>
    </section>
    <div class="row g-3 align-items-start">
      <section class="col-lg-6">
        <div class="card h-100">
          <header class="card-header d-flex align-items-center gap-2"><h3 class="card-title">{{ t('editors.skill.templateTitle') }}</h3><LteButton class="icon-action-button ms-auto" :aria-label="t('editors.common.refresh')" :disabled="loading" :title="t('editors.common.refresh')" type="button" @click="emit('refresh')"><span v-if="loading" class="spinner-border spinner-border-sm" aria-hidden="true" /><i v-else class="bi bi-arrow-clockwise" aria-hidden="true" /><span class="visually-hidden">{{ t('editors.common.refresh') }}</span></LteButton></header>
          <div v-if="catalog.length" class="list-group list-group-flush"><article v-for="skill in catalog" :key="skill.template_path" class="list-group-item" data-testid="skill-template-item"><div class="d-flex align-items-start gap-2"><div class="w-100 text-break"><strong class="d-block">{{ skill.name }}</strong><span class="small font-monospace text-body-secondary">{{ skill.template_path }}</span><details v-if="skill.description" class="mt-2"><summary>{{ t('editors.skill.description') }}</summary><p class="mb-0 mt-2 text-body-secondary">{{ skill.description }}</p></details></div><LteButton class="icon-action-button" :aria-label="privateNames.has(skill.name) ? t('editors.skill.duplicateName') : t('editors.skill.add')" :disabled="loading || mutating || privateNames.has(skill.name)" :title="privateNames.has(skill.name) ? t('editors.skill.duplicateName') : t('editors.skill.add')" type="button" @click="addSkill(skill)"><i class="bi bi-plus-lg" aria-hidden="true" /></LteButton></div></article></div>
          <p v-else class="card-body text-body-secondary mb-0">{{ t('editors.skill.emptyTemplateCatalog') }}</p>
          <div v-if="Object.keys(errors).length" class="card-body"><div class="alert alert-danger mb-0" role="alert"><p v-for="(error, folder) in errors" :key="folder" class="mb-1"><strong>{{ folder }}</strong> {{ resourceError(error) }}</p></div></div>
        </div>
      </section>
      <section class="col-lg-6">
        <div class="card h-100">
          <header class="card-header d-flex align-items-center gap-2"><h3 class="card-title">{{ t('editors.skill.privateTitle') }}</h3><LteButton class="icon-action-button ms-auto" :aria-label="t('editors.common.refresh')" :disabled="privateLoading || !draft.id" :title="t('editors.common.refresh')" type="button" @click="emit('refresh')"><span v-if="privateLoading" class="spinner-border spinner-border-sm" aria-hidden="true" /><i v-else class="bi bi-arrow-clockwise" aria-hidden="true" /><span class="visually-hidden">{{ t('editors.common.refresh') }}</span></LteButton></header>
          <div v-if="(privatePackage?.catalog.length ?? pendingTemplates.length)" class="list-group list-group-flush"><article v-for="skill in (privatePackage?.catalog ?? pendingTemplates)" :key="skill.folder" class="list-group-item" data-testid="private-skill-item"><div class="d-flex align-items-start gap-2"><div class="w-100 text-break"><strong class="d-block">{{ skill.name }}</strong><details v-if="skill.description" class="mt-2"><summary>{{ t('editors.skill.description') }}</summary><p class="mb-0 mt-2 text-body-secondary">{{ skill.description }}</p></details></div><LteButton class="icon-action-button" :aria-label="t('editors.skill.remove')" :disabled="mutating" :title="t('editors.skill.remove')" type="button" @click="removeSkill(removalKey(skill))"><i class="bi bi-trash" aria-hidden="true" /></LteButton></div></article></div>
          <p v-else class="card-body text-body-secondary mb-0">{{ t('editors.skill.emptyPrivatePackage') }}</p>
          <div v-if="Object.keys(privatePackage?.warnings ?? {}).length" class="card-body"><div class="alert alert-warning mb-0" role="alert" data-testid="private-skill-warning"><p v-for="(warning, folder) in privatePackage?.warnings" :key="folder" class="mb-1"><strong>{{ folder }}</strong> {{ resourceError(warning) }}</p></div></div>
        </div>
      </section>
    </div>
  </div>
</template>
