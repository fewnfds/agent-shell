<script setup lang="ts">
import { computed, inject } from 'vue'
import { useI18n } from 'vue-i18n'
import { routeLocationKey, routerKey } from 'vue-router'

import SectionNav from '@/components/SectionNav.vue'
import type { SectionNavItem } from '@/components/sectionNav'
import { sectionNavigationForPath } from '@/navigation'

const { t } = useI18n()
const route = inject(routeLocationKey, null)
const router = inject(routerKey, null)

const activeSectionPath = computed(() => route?.path ?? '')
const sectionItems = computed<SectionNavItem[]>(() => (
  sectionNavigationForPath(activeSectionPath.value).map((item) => ({
    id: item.path,
    label: t(item.labelKey),
  }))
))

function selectSection(path: string): void {
  void router?.push(path)
}
</script>

<template>
  <div class="app-content">
    <div class="container-fluid pt-3">
      <slot v-if="$slots.status" name="status" />
      <SectionNav
        v-if="sectionItems.length"
        :active-id="activeSectionPath"
        :aria-label="t('navigation.sectionAriaLabel')"
        class="mb-3"
        :items="sectionItems"
        layout="inline"
        @select="selectSection"
      />
      <slot />
      <div v-if="$slots.footer" class="mt-2">
        <slot name="footer" />
      </div>
      <div v-if="$slots.actions" class="page-action-reserve" aria-hidden="true" />
    </div>
  </div>
  <div v-if="$slots.actions" class="page-action-dock">
    <slot name="actions" />
  </div>
</template>
