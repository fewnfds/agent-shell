<script setup lang="ts">
import type { CapabilityManifest, ResourceComponentManifest, WorkflowComponentManifest } from '@/api'

import ConfigurationLibraryNav from '@/components/ConfigurationLibraryNav.vue'

withDefaults(defineProps<{
  manifests: readonly (CapabilityManifest | ResourceComponentManifest | WorkflowComponentManifest)[]
  layoutTestId?: string
  contentTestId?: string
  asideTestId?: string
}>(), {
  layoutTestId: 'configuration-library-layout',
  contentTestId: 'configuration-library-content-region',
  asideTestId: 'configuration-library-validation-region',
})
</script>

<template>
  <ConfigurationLibraryNav :manifests="manifests" />
  <div class="row g-3 align-items-start" :data-testid="layoutTestId">
    <section class="col" :data-testid="contentTestId">
      <slot />
    </section>
    <aside class="col-lg-3 validation-sidebar" :data-testid="asideTestId">
      <slot name="aside" />
    </aside>
  </div>
</template>
