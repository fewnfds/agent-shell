<script setup lang="ts">
import { LteAlert, LteButton } from '@adminlte/vue'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import {
  managementApi,
  type McpConnection,
  type McpImportPreview,
  type McpImportValueSources,
} from '@/api'
import ModalHost from '@/components/ModalHost.vue'
import { useManagementError } from '@/composables/useManagementError'
import { useToasts } from '@/composables/useToasts'

const emit = defineEmits<{ imported: [connections: McpConnection[]] }>()
const { t } = useI18n()
const managementError = useManagementError()
const { notify } = useToasts()
const open = ref(false)
const document = ref('')
const preview = ref<McpImportPreview | null>(null)
const valueSources = ref<McpImportValueSources>({})
const busy = ref(false)
const error = ref('')
const fileInput = ref<HTMLInputElement | null>(null)
const canImport = computed(() => Boolean(preview.value) && !busy.value)

function show(): void {
  open.value = true
  error.value = ''
}

function close(): void {
  if (busy.value) return
  open.value = false
  document.value = ''
  preview.value = null
  valueSources.value = {}
  error.value = ''
}

function openFile(): void {
  fileInput.value?.click()
}

async function selectFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  document.value = await file.text()
  await loadPreview()
}

function initialSources(result: McpImportPreview): McpImportValueSources {
  return Object.fromEntries(result.connections.map((connection) => [
    connection.name,
    {
      env: Object.fromEntries(connection.values.filter((item) => item.target === 'env').map((item) => [item.name, item.source])),
      headers: Object.fromEntries(connection.values.filter((item) => item.target === 'headers').map((item) => [item.name, item.source])),
    },
  ]))
}

async function loadPreview(): Promise<void> {
  if (!document.value.trim() || busy.value) return
  busy.value = true
  error.value = ''
  preview.value = null
  try {
    const result = await managementApi.previewMcpConnectionsImport(document.value)
    preview.value = result
    valueSources.value = initialSources(result)
  } catch (cause) {
    error.value = managementError.describe(cause).display
  } finally {
    busy.value = false
  }
}

function selectedSource(server: string, target: 'env' | 'headers', name: string): 'literal' | 'secret' {
  return valueSources.value[server]?.[target]?.[name] ?? 'secret'
}

function setSource(server: string, target: 'env' | 'headers', name: string, source: 'literal' | 'secret'): void {
  const current = valueSources.value[server] ?? {}
  valueSources.value = {
    ...valueSources.value,
    [server]: {
      ...current,
      [target]: { ...current[target], [name]: source },
    },
  }
}

function transportSummary(connection: McpImportPreview['connections'][number]): string {
  return connection.transport === 'stdio'
    ? t('mcp.import.localPackage', { source: connection.package_source === 'pypi' ? 'PyPI' : 'npm' })
    : t('mcp.connections.transportHttp')
}

async function commit(): Promise<void> {
  if (!canImport.value) return
  busy.value = true
  error.value = ''
  try {
    const connections = await managementApi.importMcpConnections(document.value, valueSources.value)
    closeAfterBusy()
    notify({ tone: 'success', title: t('mcp.import.imported', { count: connections.length }) })
    emit('imported', connections)
  } catch (cause) {
    error.value = managementError.describe(cause).display
  } finally {
    busy.value = false
  }
}

function closeAfterBusy(): void {
  open.value = false
  document.value = ''
  preview.value = null
  valueSources.value = {}
}
</script>

<template>
  <input ref="fileInput" accept=".json,application/json" class="visually-hidden" type="file" @change="selectFile">
  <LteButton class="action-button" type="button" @click="show"><i class="bi bi-upload" aria-hidden="true" />{{ t('mcp.import.action') }}</LteButton>

  <ModalHost :open="open" size="wide" :title="t('mcp.import.title')" :description="t('mcp.import.description')" @close="close">
    <LteAlert v-if="error" theme="danger">{{ error }}</LteAlert>
    <div class="d-flex flex-wrap gap-2 mb-2">
      <LteButton class="action-button" :disabled="busy" type="button" @click="openFile"><i class="bi bi-file-earmark-code" aria-hidden="true" />{{ t('mcp.import.chooseFile') }}</LteButton>
      <LteButton class="action-button" data-action="mcp-import-preview" :disabled="busy || !document.trim()" type="button" @click="loadPreview"><i class="bi bi-eye" aria-hidden="true" />{{ t('mcp.import.preview') }}</LteButton>
    </div>
    <label class="form-label" for="mcp-import-json">{{ t('mcp.import.json') }}</label>
    <textarea id="mcp-import-json" v-model="document" class="form-control font-monospace mb-3" rows="12" :placeholder="t('mcp.import.placeholder')" @input="preview = null" />

    <template v-if="preview">
      <h3 class="h5">{{ t('mcp.import.previewTitle') }}</h3>
      <div class="table-responsive">
        <table class="table table-striped align-middle">
          <thead><tr><th>{{ t('mcp.import.server') }}</th><th>{{ t('mcp.import.transport') }}</th><th>{{ t('mcp.import.valueName') }}</th><th>{{ t('mcp.import.valueSource') }}</th></tr></thead>
          <tbody>
            <template v-for="connection in preview.connections" :key="connection.name">
              <tr v-if="!connection.values.length"><td>{{ connection.name }}</td><td>{{ transportSummary(connection) }}</td><td class="text-body-secondary">{{ t('mcp.import.noValues') }}</td><td /></tr>
              <tr v-for="value in connection.values" :key="`${connection.name}:${value.target}:${value.name}`">
                <td>{{ connection.name }}</td>
                <td>{{ transportSummary(connection) }}</td>
                <td><span class="badge text-bg-secondary me-2">{{ value.target }}</span><code>{{ value.name }}</code></td>
                <td>
                  <select class="form-select" data-testid="mcp-import-value-source" :value="selectedSource(connection.name, value.target, value.name)" @change="setSource(connection.name, value.target, value.name, ($event.target as HTMLSelectElement).value as 'literal' | 'secret')">
                    <option value="secret">{{ t('mcp.connections.secret') }}</option>
                    <option value="literal">{{ t('mcp.connections.literal') }}</option>
                  </select>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </template>

    <template #footer>
      <LteButton class="action-button" :disabled="busy" type="button" @click="close"><i class="bi bi-x-lg" aria-hidden="true" />{{ t('common.cancel') }}</LteButton>
      <LteButton class="action-button" data-action="mcp-import-commit" :disabled="!canImport" type="button" @click="commit"><span v-if="busy" class="spinner-border spinner-border-sm" aria-hidden="true" /><i v-else class="bi bi-upload" aria-hidden="true" />{{ t('mcp.import.commit') }}</LteButton>
    </template>
  </ModalHost>
</template>
