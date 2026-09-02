<script setup lang="ts">
import type { RuntimeMonitoringRun, RuntimeMonitoringSnapshot } from '@/api'

defineProps<{
  scope: RuntimeMonitoringSnapshot['selector']['scope']
  selectorId: string
  workflows: Array<{ id: string; name: string }>
  runs: RuntimeMonitoringRun[]
  disabled: boolean
}>()

const emit = defineEmits<{
  scopeChange: [scope: RuntimeMonitoringSnapshot['selector']['scope']]
  selectorChange: [id: string]
}>()

function scopeChanged(event: Event): void {
  const value = (event.target as HTMLSelectElement).value
  if (value === 'lifecycle' || value === 'workflow' || value === 'run') {
    emit('scopeChange', value)
  }
}

function selectorChanged(event: Event): void {
  emit('selectorChange', (event.target as HTMLSelectElement).value)
}
</script>

<template>
  <div class="runtime-monitoring-scope-controls">
    <div>
      <label class="form-label" for="runtime-monitoring-scope">
        {{ $t('runtimeMonitoring.scope.label') }}
      </label>
      <select
        id="runtime-monitoring-scope"
        class="form-select form-select-sm"
        :disabled="disabled"
        :value="scope"
        @change="scopeChanged"
      >
        <option value="lifecycle">{{ $t('runtimeMonitoring.scope.lifecycle') }}</option>
        <option value="workflow">{{ $t('runtimeMonitoring.scope.workflow') }}</option>
        <option value="run">{{ $t('runtimeMonitoring.scope.run') }}</option>
      </select>
    </div>

    <div v-if="scope === 'workflow'">
      <label class="form-label" for="runtime-monitoring-workflow-scope">
        {{ $t('runtimeMonitoring.scope.workflowLabel') }}
      </label>
      <select
        id="runtime-monitoring-workflow-scope"
        class="form-select form-select-sm"
        :disabled="disabled"
        :value="selectorId"
        @change="selectorChanged"
      >
        <option v-for="workflow in workflows" :key="workflow.id" :value="workflow.id">
          {{ workflow.name }} · {{ workflow.id }}
        </option>
      </select>
    </div>

    <div v-else-if="scope === 'run'">
      <label class="form-label" for="runtime-monitoring-run-scope">
        {{ $t('runtimeMonitoring.scope.runLabel') }}
      </label>
      <select
        id="runtime-monitoring-run-scope"
        class="form-select form-select-sm"
        :disabled="disabled"
        :value="selectorId"
        @change="selectorChanged"
      >
        <option v-for="run in runs" :key="run.run_id" :value="run.run_id">
          {{ run.workflow_name }} · {{ run.run_id }}
        </option>
      </select>
    </div>
  </div>
</template>
