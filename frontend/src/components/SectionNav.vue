<script setup lang="ts">
import { LteButton } from '@adminlte/vue'

import type { SectionNavItem } from '@/components/sectionNav'

withDefaults(defineProps<{
  items: readonly SectionNavItem[]
  activeId: string
  ariaLabel: string
  layout?: 'inline' | 'stacked'
}>(), {
  layout: 'stacked',
})

const emit = defineEmits<{
  select: [id: string]
}>()
</script>

<template>
  <nav
    v-if="layout === 'inline'"
    :aria-label="ariaLabel"
    class="d-flex flex-wrap gap-2"
    data-testid="section-nav"
  >
    <template v-for="item in items" :key="item.id">
      <LteButton
        v-if="item.id === activeId"
        aria-current="page"
        theme="primary"
        @click="emit('select', item.id)"
      >
        {{ item.label }}
      </LteButton>
      <LteButton
        v-else
        theme="secondary"
        @click="emit('select', item.id)"
      >
        {{ item.label }}
      </LteButton>
    </template>
  </nav>
  <nav
    v-else
    :aria-label="ariaLabel"
    class="d-flex flex-wrap gap-2"
    data-testid="section-nav"
  >
    <template v-for="item in items" :key="item.id">
      <LteButton
        v-if="item.id === activeId"
        class="w-100"
        aria-current="page"
        theme="primary"
        @click="emit('select', item.id)"
      >
        {{ item.label }}
      </LteButton>
      <LteButton
        v-else
        class="w-100"
        theme="secondary"
        @click="emit('select', item.id)"
      >
        {{ item.label }}
      </LteButton>
    </template>
  </nav>
</template>
