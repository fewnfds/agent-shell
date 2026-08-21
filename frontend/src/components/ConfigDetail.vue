<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { fieldLabelKeys } from '@/locales/fieldLabels'

const props = withDefaults(defineProps<{
  value: Record<string, unknown>
  mode?: 'card' | 'json'
  hiddenKeys?: readonly string[]
}>(), {
  mode: 'card',
  hiddenKeys: () => [],
})

const { t, te } = useI18n()
const rows = computed(() => Object.entries(props.value)
  .filter(([key]) => !props.hiddenKeys.includes(key)))
const json = computed(() => JSON.stringify(props.value, null, 2))

function labelFor(path: string): string {
  const key = fieldLabelKeys(path).find((candidate) => te(candidate))
  return key ? t(key) : path
}

function displayValue(value: unknown): string {
  if (value === null) return 'null'
  if (value === undefined) return '—'
  if (typeof value === 'object') return JSON.stringify(value, null, 2)
  return String(value)
}
</script>

<template>
  <pre
    v-if="mode === 'json'"
    class="border rounded overflow-auto p-3"
    data-testid="config-detail-json"
  ><code>{{ json }}</code></pre>
  <dl
    v-else
    data-testid="config-detail-list"
  >
    <div
      v-for="([key, item]) in rows"
      :key="key"
      class="row g-3 mb-3"
    >
      <dt class="col-md-6 text-end">
        <strong class="d-block">{{ labelFor(key) }}</strong>
        <span class="d-block font-monospace text-body-secondary">{{ key }}</span>
      </dt>
      <dd class="col-md-6 text-break text-start">
        <pre v-if="typeof item === 'object'" class="border rounded overflow-auto p-3"><code>{{ displayValue(item) }}</code></pre>
        <span v-else>{{ displayValue(item) }}</span>
      </dd>
    </div>
  </dl>
</template>
