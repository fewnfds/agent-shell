<script setup lang="ts">
import { LteButton, LteInput } from '@adminlte/vue'
import { useI18n } from 'vue-i18n'

import type { McpConfiguredValueDraft, McpConnectionDraft } from '@/domain/blocks'

import { useEditorModel } from './shared/useEditorModel'

const props = defineProps<{ modelValue: McpConnectionDraft }>()
const emit = defineEmits<{ 'update:modelValue': [value: McpConnectionDraft] }>()
const { t } = useI18n()
const draft = useEditorModel(() => props.modelValue, (value) => emit('update:modelValue', value))

function setTransport(event: Event): void {
  const transport = (event.target as HTMLSelectElement).value as 'stdio' | 'http'
  if (transport === draft.transport) return
  const common = { id: draft.id, name: draft.name, values: [] }
  if (transport === 'http') {
    Object.keys(draft).forEach((key) => delete (draft as unknown as Record<string, unknown>)[key])
    Object.assign(draft, { ...common, transport: 'http', url: '' })
  } else {
    Object.keys(draft).forEach((key) => delete (draft as unknown as Record<string, unknown>)[key])
    Object.assign(draft, { ...common, transport: 'stdio', command: '', args: [], cwd: '' })
  }
}

function addArgument(): void {
  if (draft.transport === 'stdio') draft.args.push('')
}

function removeArgument(index: number): void {
  if (draft.transport === 'stdio') draft.args.splice(index, 1)
}

function addValue(): void {
  draft.values.push({ name: '', source: 'secret', value: '', status: 'missing' })
}

function removeValue(index: number): void {
  draft.values.splice(index, 1)
}

function updateValueName(item: McpConfiguredValueDraft, event: Event): void {
  const name = (event.target as HTMLInputElement).value
  if (name !== item.name) {
    item.name = name
    item.value = ''
    item.status = 'missing'
  }
}

function updateValueSource(item: McpConfiguredValueDraft, event: Event): void {
  item.source = (event.target as HTMLSelectElement).value as 'literal' | 'secret'
  item.value = ''
  item.status = 'missing'
}
</script>

<template>
  <div data-editor="mcp-connection">
    <section class="card mb-3">
      <header class="card-header"><h3 class="card-title">{{ t('mcp.connections.transportTitle') }}</h3></header>
      <div class="card-body">
        <label class="form-label" for="mcp-transport">{{ t('mcp.connections.transport') }}</label>
        <select id="mcp-transport" class="form-select" :value="draft.transport" @change="setTransport">
          <option value="stdio">{{ t('mcp.connections.transportStdio') }}</option>
          <option value="http">{{ t('mcp.connections.transportHttp') }}</option>
        </select>
      </div>
    </section>

    <section class="card mb-3">
      <header class="card-header"><h3 class="card-title">{{ t('mcp.connections.connectionTitle') }}</h3></header>
      <div class="card-body">
        <template v-if="draft.transport === 'stdio'">
          <div class="mb-3">
            <label class="form-label" for="mcp-command">{{ t('mcp.connections.command') }}</label>
            <LteInput id="mcp-command" v-model="draft.command" autocomplete="off" class="font-monospace" />
          </div>
          <div class="mb-3">
            <div class="d-flex align-items-center gap-2 mb-2">
              <span class="form-label mb-0">{{ t('mcp.connections.arguments') }}</span>
              <LteButton class="icon-action-button ms-auto" :aria-label="t('mcp.connections.addArgument')" :title="t('mcp.connections.addArgument')" size="sm" type="button" @click="addArgument"><i class="bi bi-plus-lg" aria-hidden="true" /></LteButton>
            </div>
            <div v-for="(_, index) in draft.args" :key="index" class="input-group mb-2">
              <span class="input-group-text">{{ index + 1 }}</span>
              <input v-model="draft.args[index]" class="form-control font-monospace" autocomplete="off">
              <LteButton class="icon-action-button" :aria-label="t('common.remove')" :title="t('common.remove')" type="button" @click="removeArgument(index)"><i class="bi bi-trash" aria-hidden="true" /></LteButton>
            </div>
            <p v-if="!draft.args.length" class="text-body-secondary mb-0">{{ t('mcp.connections.noArguments') }}</p>
          </div>
          <div>
            <label class="form-label" for="mcp-cwd">{{ t('mcp.connections.cwd') }}</label>
            <LteInput id="mcp-cwd" v-model="draft.cwd" autocomplete="off" class="font-monospace" :placeholder="t('mcp.connections.cwdPlaceholder')" />
          </div>
        </template>
        <template v-else>
          <label class="form-label" for="mcp-url">{{ t('mcp.connections.url') }}</label>
          <LteInput id="mcp-url" v-model="draft.url" autocomplete="off" inputmode="url" class="font-monospace" placeholder="https://example.com/mcp" />
        </template>
      </div>
    </section>

    <section class="card mb-3">
      <header class="card-header d-flex align-items-center gap-2">
        <h3 class="card-title mb-0">{{ draft.transport === 'stdio' ? t('mcp.connections.environment') : t('mcp.connections.headers') }}</h3>
        <LteButton class="icon-action-button ms-auto" :aria-label="t('mcp.connections.addValue')" :title="t('mcp.connections.addValue')" size="sm" type="button" @click="addValue"><i class="bi bi-plus-lg" aria-hidden="true" /></LteButton>
      </header>
      <div class="card-body">
        <p class="text-body-secondary">{{ t('mcp.connections.valueHint') }}</p>
        <div v-for="(item, index) in draft.values" :key="index" class="row g-2 align-items-end mb-3" data-testid="mcp-configured-value">
          <div class="col-lg-3">
            <label class="form-label" :for="`mcp-value-name-${index}`">{{ t('mcp.connections.valueName') }}</label>
            <input :id="`mcp-value-name-${index}`" :value="item.name" class="form-control font-monospace" autocomplete="off" @input="updateValueName(item, $event)">
          </div>
          <div class="col-lg-2">
            <label class="form-label" :for="`mcp-value-source-${index}`">{{ t('mcp.connections.valueSource') }}</label>
            <select :id="`mcp-value-source-${index}`" class="form-select" :value="item.source" @change="updateValueSource(item, $event)">
              <option value="secret">{{ t('mcp.connections.secret') }}</option>
              <option value="literal">{{ t('mcp.connections.literal') }}</option>
            </select>
          </div>
          <div class="col">
            <label class="form-label" :for="`mcp-value-${index}`">{{ t('mcp.connections.value') }}</label>
            <input
              :id="`mcp-value-${index}`"
              v-model="item.value"
              :autocomplete="item.source === 'secret' ? 'new-password' : 'off'"
              class="form-control font-monospace"
              :placeholder="item.source === 'secret' && item.status === 'masked' ? t('common.configuredSecretPlaceholder') : ''"
              :type="item.source === 'secret' ? 'password' : 'text'"
            >
          </div>
          <div class="col-auto">
            <LteButton class="icon-action-button" :aria-label="t('common.remove')" :title="t('common.remove')" type="button" @click="removeValue(index)"><i class="bi bi-trash" aria-hidden="true" /></LteButton>
          </div>
        </div>
        <p v-if="!draft.values.length" class="text-body-secondary mb-0">{{ t('mcp.connections.noValues') }}</p>
      </div>
    </section>
  </div>
</template>
