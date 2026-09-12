<script setup lang="ts">
import { computed, ref } from 'vue'

defineOptions({ name: 'StructuredValueTree' })

const props = withDefaults(defineProps<{
  name?: string
  value: unknown
  depth?: number
  // `| undefined` is required so the explicit `defaultOpen: undefined` below
  // type-checks under `exactOptionalPropertyTypes`.
  defaultOpen?: boolean | undefined
}>(), {
  name: '',
  depth: 0,
  // Vue casts an absent Boolean prop to `false`. Defaulting to `undefined`
  // instead is what keeps "not provided" distinguishable from "false" so the
  // top level of the tree opens by default; removing this changes behaviour.
  defaultOpen: undefined,
})

const open = ref(props.defaultOpen ?? props.depth === 0)
const longTextOpen = ref(false)
const composite = computed(() => props.value !== null && typeof props.value === 'object')
const entries = computed<Array<[string, unknown]>>(() => {
  if (Array.isArray(props.value)) return props.value.map((value, index) => [String(index), value])
  if (props.value !== null && typeof props.value === 'object') return Object.entries(props.value)
  return []
})
const emptyComposite = computed(() => composite.value && entries.value.length === 0)
const stringValue = computed(() => typeof props.value === 'string' ? props.value : '')
const longText = computed(() => stringValue.value.length > 280)
const visibleString = computed(() => (
  longText.value && !longTextOpen.value
    ? `${stringValue.value.slice(0, 280)}…`
    : stringValue.value
))

function scalarType(value: unknown): string {
  if (value === null) return 'null'
  if (value === undefined) return 'undefined'
  return typeof value
}

function scalarValue(value: unknown): string {
  if (value === null) return 'null'
  if (value === undefined) return 'undefined'
  return String(value)
}
</script>

<template>
  <div class="structured-value" :data-depth="depth">
    <template v-if="composite">
      <button
        v-if="name"
        class="structured-value-toggle"
        type="button"
        :aria-expanded="open"
        @click="open = !open"
      >
        <i class="bi" :class="open ? 'bi-chevron-down' : 'bi-chevron-right'" aria-hidden="true" />
        <span class="structured-value-key">{{ name }}</span>
        <span v-if="Array.isArray(value)" class="structured-value-count">{{ entries.length }}</span>
      </button>
      <div v-if="!name || open" class="structured-value-children">
        <span v-if="emptyComposite" class="structured-value-empty">
          {{ Array.isArray(value) ? '[]' : '{}' }}
        </span>
        <StructuredValueTree
          v-for="([key, child]) in entries"
          :key="key"
          :name="key"
          :value="child"
          :depth="depth + 1"
          :default-open="depth === 0 && key !== 'messages'"
        />
      </div>
    </template>
    <div v-else class="structured-value-scalar">
      <span v-if="name" class="structured-value-key">{{ name }}</span>
      <span v-if="name" class="structured-value-separator">:</span>
      <span
        v-if="typeof value === 'string'"
        class="structured-value-string"
      >{{ visibleString }}</span>
      <span v-else class="structured-value-literal" :data-value-type="scalarType(value)">
        {{ scalarValue(value) }}
      </span>
      <button
        v-if="longText"
        class="icon-action-button structured-value-text-toggle"
        type="button"
        :aria-expanded="longTextOpen"
        @click="longTextOpen = !longTextOpen"
      >
        <i class="bi" :class="longTextOpen ? 'bi-chevron-up' : 'bi-chevron-down'" aria-hidden="true" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.structured-value {
  min-width: 0;
  font-size: .8125rem;
}

.structured-value-toggle,
.structured-value-scalar {
  display: flex;
  align-items: flex-start;
  gap: .35rem;
  width: 100%;
  min-height: 1.75rem;
  padding: .2rem .35rem;
  border: 0;
  background: transparent;
  color: var(--bs-body-color);
  text-align: start;
}

.structured-value-toggle:hover,
.structured-value-scalar:hover {
  background: var(--bs-tertiary-bg);
}

.structured-value-toggle .bi {
  margin-top: .1rem;
  color: var(--bs-secondary-color);
}

.structured-value-children {
  margin-inline-start: .65rem;
  padding-inline-start: .55rem;
  border-inline-start: 1px solid var(--bs-border-color);
}

.structured-value-key {
  flex: 0 0 auto;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.structured-value-count,
.structured-value-separator,
.structured-value-empty {
  color: var(--bs-secondary-color);
}

.structured-value-string,
.structured-value-literal {
  min-width: 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.structured-value-literal {
  font-family: var(--bs-font-monospace);
}

.structured-value-literal[data-value-type='boolean'],
.structured-value-literal[data-value-type='number'] {
  color: var(--bs-primary-text-emphasis);
}

.structured-value-literal[data-value-type='null'],
.structured-value-literal[data-value-type='undefined'] {
  color: var(--bs-secondary-color);
}

.structured-value-text-toggle {
  flex: 0 0 auto;
  width: 1.5rem;
  height: 1.5rem;
}
</style>
