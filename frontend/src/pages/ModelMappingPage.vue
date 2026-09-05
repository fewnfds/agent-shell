<script setup lang="ts">
import { LteAlert, LteButton } from '@adminlte/vue'
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { managementApi, type ModelConnection, type ModelRequirementBinding } from '@/api'
import PageShell from '@/components/PageShell.vue'
import { useManagementError } from '@/composables/useManagementError'

const { t } = useI18n()
const managementError = useManagementError()
const requirements = ref<ModelRequirementBinding[]>([])
const connections = ref<ModelConnection[]>([])
const error = ref('')
const loading = ref(true)
const savingRequirementIds = ref<Set<string>>(new Set())
const bindingDrafts = ref<Record<string, string>>({})
let loadGeneration = 0
const unboundCount = computed(() => requirements.value.filter((item) => !item.binding || !item.connection).length)
const hasPendingChanges = computed(() => requirements.value.some(
  (item) => bindingDraft(item) !== (item.binding ?? ''),
))

function bindingDraft(item: ModelRequirementBinding): string {
  return bindingDrafts.value[item.id] ?? item.binding ?? ''
}

function setBindingDraft(item: ModelRequirementBinding, value: string): void {
  bindingDrafts.value = { ...bindingDrafts.value, [item.id]: value }
}

async function load(): Promise<void> {
  const generation = ++loadGeneration
  loading.value = true
  error.value = ''
  try {
    const [loadedRequirements, loadedConnections] = await Promise.all([
      managementApi.listModelRequirements(),
      managementApi.listModelConnections(),
    ])
    if (generation !== loadGeneration) return
    requirements.value = loadedRequirements
    connections.value = loadedConnections
    bindingDrafts.value = Object.fromEntries(
      loadedRequirements.map((item) => [item.id, item.binding ?? '']),
    )
  } catch (cause) {
    if (generation === loadGeneration) error.value = managementError.describe(cause).display
  } finally {
    if (generation === loadGeneration) loading.value = false
  }
}

async function confirmBindings(): Promise<void> {
  const changedRequirements = requirements.value.filter(
    (item) => bindingDraft(item) !== (item.binding ?? ''),
  )
  if (!changedRequirements.length || savingRequirementIds.value.size > 0) return
  const generation = loadGeneration
  savingRequirementIds.value = new Set(changedRequirements.map((item) => item.id))
  error.value = ''
  try {
    for (const item of changedRequirements) {
      const updated = await managementApi.bindModelRequirement(
        item.id,
        bindingDraft(item) || null,
      )
      if (generation !== loadGeneration) return
      Object.assign(item, updated)
      bindingDrafts.value = {
        ...bindingDrafts.value,
        [item.id]: updated.binding ?? '',
      }
    }
  } catch (cause) {
    if (generation === loadGeneration) error.value = managementError.describe(cause).display
  } finally {
    if (generation === loadGeneration) savingRequirementIds.value = new Set()
  }
}
onMounted(() => { void load() })
</script>

<template>
  <PageShell>
    <template #actions>
      <LteButton class="action-button" :disabled="loading || savingRequirementIds.size > 0" type="button" @click="load">
        <i class="bi bi-arrow-clockwise" aria-hidden="true" />
        {{ t('editors.common.refresh') }}
      </LteButton>
      <LteButton
        class="action-button"
        data-testid="model-mapping-confirm"
        :disabled="loading || savingRequirementIds.size > 0 || !hasPendingChanges"
        type="button"
        @click="confirmBindings"
      >
        <span v-if="savingRequirementIds.size > 0" class="spinner-border spinner-border-sm" aria-hidden="true" />
        <i v-else class="bi bi-check-lg" aria-hidden="true" />
        {{ t('models.mapping.confirm') }}
      </LteButton>
    </template>
    <template #status>
      <LteAlert v-if="error" theme="danger" :title="t('models.mapping.loadFailed')">{{ error }}</LteAlert>
      <LteAlert v-else-if="unboundCount" theme="warning" :title="t('models.mapping.warningTitle')">{{ t('models.mapping.warning', { count: unboundCount }) }}</LteAlert>
    </template>
    <div class="row g-3" data-testid="model-mapping-cards">
      <section v-for="item in requirements" :key="item.id" class="col-lg-6">
        <article class="card h-100">
          <header class="card-header"><h2 class="card-title">{{ item.name }}</h2></header>
          <div class="card-body">
            <details>
              <summary>{{ t('models.mapping.description') }}</summary>
              <p class="mt-2 mb-3 text-body-secondary text-break">{{ item.description }}</p>
            </details>
            <label class="form-label" :for="`binding-${item.id}`">{{ t('models.mapping.connection') }}</label>
            <select
              :id="`binding-${item.id}`"
              class="form-select"
              :disabled="savingRequirementIds.size > 0"
              :value="bindingDraft(item)"
              @change="setBindingDraft(item, ($event.target as HTMLSelectElement).value)"
            >
              <option value="">{{ t('models.mapping.unbound') }}</option>
              <option v-for="connection in connections" :key="connection.id" :value="connection.id">
                {{ t('models.mapping.connectionSummary', { configuration: connection.name, provider: connection.provider, model: connection.model }) }}
              </option>
            </select>
          </div>
        </article>
      </section>
      <p v-if="!requirements.length && !loading" class="text-body-secondary">{{ t('models.mapping.empty') }}</p>
    </div>
  </PageShell>
</template>
