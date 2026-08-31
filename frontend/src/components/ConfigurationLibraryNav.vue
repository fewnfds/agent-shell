<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import type { CapabilityManifest, ResourceComponentManifest, WorkflowComponentManifest } from '@/api'
import SectionNav from '@/components/SectionNav.vue'
import type { SectionNavItem } from '@/components/sectionNav'
import { agentLibraryCategories, globalLibraryCategories, routeCategory, workflowLibraryCategories } from '@/pages/configLibrary'

const props = defineProps<{
  manifests: readonly (CapabilityManifest | ResourceComponentManifest | WorkflowComponentManifest)[]
}>()

const { t } = useI18n()
const route = useRoute()
const router = useRouter()

const activeCategoryId = computed(() => (
  route.path === '/library/configuration-repositories'
    ? 'configuration-repositories'
    : routeCategory(route.params.type)
))
const agentComponentItems = computed<SectionNavItem[]>(() => props.manifests
  .filter((manifest): manifest is CapabilityManifest | ResourceComponentManifest => (
    'subagent_policy' in manifest || 'resource_component' in manifest
  ))
  .map((manifest) => ({
  id: manifest.type,
  label: t(`capabilities.${manifest.type}.label`),
})))
const workflowComponentItems = computed<SectionNavItem[]>(() => props.manifests
  .filter((manifest): manifest is WorkflowComponentManifest => (
    !('subagent_policy' in manifest) && !('resource_component' in manifest)
  ))
  .map((manifest) => ({
    id: manifest.type,
    label: t(`capabilities.${manifest.type}.label`),
  })))
const agentItems = computed<SectionNavItem[]>(() => agentLibraryCategories.map((id) => ({
  id,
  label: t(`capabilities.${id}.label`),
})))
const workflowItems = computed<SectionNavItem[]>(() => workflowLibraryCategories.map((id) => ({
  id,
  label: t(`capabilities.${id}.label`),
})))
const globalItems = computed<SectionNavItem[]>(() => globalLibraryCategories.map((id) => ({
  id,
  label: id === 'configuration-repositories'
    ? t('navigation.sections.configurationRepositories')
    : t(`capabilities.${id}.label`),
})))

function selectCategory(id: string): void {
  if (id === activeCategoryId.value) return
  void router.push(`/library/${encodeURIComponent(id)}`)
}
</script>

<template>
  <div
    class="configuration-library-nav-group d-flex flex-wrap align-items-center gap-2 mb-2"
    data-testid="library-global-group"
  >
    <span class="fw-semibold">{{ t('library.groups.global') }}</span>
    <SectionNav
      :active-id="activeCategoryId"
      :aria-label="t('library.groups.global')"
      :items="globalItems"
      layout="inline"
      @select="selectCategory"
    />
  </div>
  <div
    class="configuration-library-nav-group d-flex flex-wrap align-items-center gap-2 mb-2"
    data-testid="library-workflow-group"
  >
    <span class="fw-semibold">{{ t('library.groups.workflows') }}</span>
    <SectionNav
      :active-id="activeCategoryId"
      :aria-label="t('library.groups.workflows')"
      :items="workflowItems"
      layout="inline"
      @select="selectCategory"
    />
  </div>
  <div class="configuration-library-nav-group d-flex flex-wrap align-items-center gap-2 mb-2" data-testid="library-workflow-component-group">
    <span class="fw-semibold">{{ t('library.groups.workflowComponents') }}</span>
    <SectionNav
      :active-id="activeCategoryId"
      :aria-label="t('library.groups.workflowComponents')"
      :items="workflowComponentItems"
      layout="inline"
      @select="selectCategory"
    />
  </div>
  <div
    class="configuration-library-nav-group d-flex flex-wrap align-items-center gap-2 mb-2"
    data-testid="library-agent-group"
  >
    <span class="fw-semibold">{{ t('library.groups.agents') }}</span>
    <SectionNav
      :active-id="activeCategoryId"
      :aria-label="t('library.groups.agents')"
      :items="agentItems"
      layout="inline"
      @select="selectCategory"
    />
  </div>
  <div class="configuration-library-nav-group d-flex flex-wrap align-items-center gap-2 mb-2" data-testid="library-component-group">
    <span class="fw-semibold">{{ t('library.groups.agentComponents') }}</span>
    <SectionNav
      :active-id="activeCategoryId"
      :aria-label="t('library.groups.agentComponents')"
      :items="agentComponentItems"
      layout="inline"
      @select="selectCategory"
    />
  </div>
</template>
