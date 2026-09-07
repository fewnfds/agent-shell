<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'

import type {
  JsonValue,
  LangGraphLifecycleStore,
  LangGraphStateResponse,
  LangGraphStoreNamespace,
} from '@/api'

import StructuredValueTree from './StructuredValueTree.vue'

type InspectorTab = 'state' | 'store'

defineProps<{
  state: LangGraphStateResponse | null
  store: LangGraphLifecycleStore | null
  loading: boolean
}>()

const { t } = useI18n()
const selected = ref<InspectorTab>('state')

function namespaceName(namespace: LangGraphStoreNamespace): string {
  return namespace.namespace.slice(2).join('/') || namespace.namespace.join('/')
}

function namespaceItems(namespace: LangGraphStoreNamespace): Record<string, JsonValue> {
  return Object.fromEntries(namespace.items.map((item, index) => [
    typeof item.key === 'string' ? item.key : String(index),
    item,
  ]))
}
</script>

<template>
  <aside class="runtime-data-inspector">
    <nav class="runtime-inspector-tabs" :aria-label="t('runtimeMonitoring.data')">
      <button
        class="runtime-inspector-tab"
        :class="{ 'runtime-inspector-tab--selected': selected === 'state' }"
        type="button"
        :aria-current="selected === 'state' ? 'page' : undefined"
        @click="selected = 'state'"
      >
        {{ t('runtimeMonitoring.state.title') }}
      </button>
      <button
        class="runtime-inspector-tab"
        :class="{ 'runtime-inspector-tab--selected': selected === 'store' }"
        type="button"
        :aria-current="selected === 'store' ? 'page' : undefined"
        @click="selected = 'store'"
      >
        {{ t('runtimeMonitoring.store') }}
      </button>
    </nav>

    <div class="runtime-inspector-body">
      <div v-if="selected === 'state'">
        <div v-if="loading && !state" class="runtime-inspector-loading" aria-busy="true">
          <span class="spinner-border spinner-border-sm" aria-hidden="true" />
        </div>
        <StructuredValueTree v-else-if="state?.state" :value="state.state" />
        <div v-else-if="state?.error" class="runtime-inspector-error">
          {{ state.error.message }}
        </div>
      </div>
      <div v-else>
        <StructuredValueTree
          v-for="namespace in store?.namespaces ?? []"
          :key="namespace.namespace.join('/')"
          :name="namespaceName(namespace)"
          :value="namespaceItems(namespace)"
        />
      </div>
    </div>
  </aside>
</template>

<style scoped>
.runtime-data-inspector {
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  border-inline-start: 1px solid var(--bs-border-color);
}

.runtime-inspector-tabs {
  display: flex;
  gap: 1rem;
  min-height: 3rem;
  padding-inline: .75rem;
  border-block-end: 1px solid var(--bs-border-color);
}

.runtime-inspector-tab {
  padding: .6rem .15rem;
  border: 0;
  border-block-end: 2px solid transparent;
  background: transparent;
  color: var(--bs-secondary-color);
}

.runtime-inspector-tab--selected {
  border-block-end-color: var(--bs-primary);
  color: var(--bs-body-color);
}

.runtime-inspector-body {
  height: calc(100% - 3rem);
  overflow: auto;
  padding: .65rem;
}

.runtime-inspector-loading,
.runtime-inspector-error {
  display: flex;
  align-items: center;
  gap: .5rem;
  padding: 1rem;
  color: var(--bs-secondary-color);
}

.runtime-inspector-error {
  color: var(--bs-danger-text-emphasis);
}

@media (max-width: 991.98px) {
  .runtime-data-inspector {
    min-height: 24rem;
    border-inline-start: 0;
    border-block-start: 1px solid var(--bs-border-color);
  }
}
</style>
