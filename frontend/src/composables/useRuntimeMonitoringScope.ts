import { computed, type Ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import type { RuntimeMonitoringSnapshot } from '@/api'
import { resolveRuntimeMonitoringScope } from '@/domain/runtimeMonitoring'

export function runtimeMonitoringScopeRequest(
  selection: RuntimeMonitoringSnapshot['selector'],
) {
  if (selection.scope === 'workflow' && selection.id) {
    return { workflow_id: selection.id }
  }
  if (selection.scope === 'run' && selection.id) {
    return { run_id: selection.id }
  }
  return undefined
}

export function runtimeMonitoringSelectorKey(
  selection: RuntimeMonitoringSnapshot['selector'],
): string {
  return `${selection.scope}:${selection.id ?? ''}`
}

export function useRuntimeMonitoringScope(
  lifecycleSnapshot: Readonly<Ref<RuntimeMonitoringSnapshot | null>>,
  snapshot: Readonly<Ref<RuntimeMonitoringSnapshot | null>>,
  selectedRunId: Readonly<Ref<string>>,
) {
  const route = useRoute()
  const router = useRouter()
  const requestedRunId = computed(() => (
    typeof route.query.run_id === 'string' ? route.query.run_id : ''
  ))
  const requestedScope = computed(() => (
    typeof route.query.scope === 'string' ? route.query.scope : ''
  ))
  const requestedWorkflowId = computed(() => (
    typeof route.query.workflow_id === 'string' ? route.query.workflow_id : ''
  ))
  const requestedScopeRouteKey = computed(() => [
    requestedScope.value,
    requestedScope.value === 'workflow' ? requestedWorkflowId.value : '',
    requestedScope.value === 'run' ? requestedRunId.value : '',
  ].join(':'))
  const displayedScope = computed(() => lifecycleSnapshot.value
    ? resolveRuntimeMonitoringScope(
        lifecycleSnapshot.value,
        requestedScope.value,
        requestedWorkflowId.value,
        requestedRunId.value,
      )
    : { scope: 'lifecycle' as const, id: null })
  const scopeSelectorId = computed(() => displayedScope.value.id ?? '')
  const scopeWorkflows = computed(() => {
    const workflows = new Map<string, string>()
    for (const run of lifecycleSnapshot.value?.runs ?? []) {
      if (!workflows.has(run.workflow_id)) workflows.set(run.workflow_id, run.workflow_name)
    }
    return [...workflows].map(([id, name]) => ({ id, name }))
  })

  function baseRunQuery(runId = selectedRunId.value) {
    const query = { ...route.query }
    delete query.node_id
    delete query.view
    if (runId) query.run_id = runId
    return query
  }

  function replaceCanonicalScopeQuery(selection: RuntimeMonitoringSnapshot['selector']): void {
    const query = { ...route.query }
    let changed = false
    if (selection.scope === 'lifecycle') {
      if ('scope' in query) {
        delete query.scope
        changed = true
      }
      if ('workflow_id' in query) {
        delete query.workflow_id
        changed = true
      }
    } else if (selection.scope === 'workflow') {
      if (query.scope !== 'workflow') {
        query.scope = 'workflow'
        changed = true
      }
      if (query.workflow_id !== selection.id) {
        query.workflow_id = selection.id ?? undefined
        changed = true
      }
    } else {
      if (query.scope !== 'run') {
        query.scope = 'run'
        changed = true
      }
      if ('workflow_id' in query) {
        delete query.workflow_id
        changed = true
      }
      if (query.run_id !== selection.id) {
        query.run_id = selection.id ?? undefined
        changed = true
      }
    }
    if (changed) void router.replace({ query })
  }

  function selectScope(scope: RuntimeMonitoringSnapshot['selector']['scope']): void {
    const full = lifecycleSnapshot.value
    if (!full || scope === snapshot.value?.selector.scope) return
    const currentRun = full.runs.find((run) => run.run_id === selectedRunId.value)
      ?? full.runs.find((run) => run.run_id === full.lifecycle.root_run_id)
      ?? full.runs[0]
    if (!currentRun) return

    const query = baseRunQuery(currentRun.run_id)
    delete query.node_id
    delete query.view
    if (scope === 'lifecycle') {
      delete query.scope
      delete query.workflow_id
    } else if (scope === 'workflow') {
      query.scope = 'workflow'
      query.workflow_id = currentRun.workflow_id
    } else {
      query.scope = 'run'
      delete query.workflow_id
      query.run_id = currentRun.run_id
    }
    void router.push({ query })
  }

  function selectScopeTarget(id: string): void {
    const full = lifecycleSnapshot.value
    const scope = displayedScope.value.scope
    if (!full || !id || (scope !== 'workflow' && scope !== 'run')) return
    const query = baseRunQuery()
    delete query.node_id
    delete query.view
    if (scope === 'workflow') {
      const firstRun = full.runs.find((run) => run.workflow_id === id)
      if (!firstRun) return
      query.scope = 'workflow'
      query.workflow_id = id
      query.run_id = firstRun.run_id
    } else {
      if (!full.runs.some((run) => run.run_id === id)) return
      query.scope = 'run'
      delete query.workflow_id
      query.run_id = id
    }
    void router.push({ query })
  }

  return {
    requestedRunId,
    requestedScope,
    requestedScopeRouteKey,
    displayedScope,
    scopeSelectorId,
    scopeWorkflows,
    baseRunQuery,
    replaceCanonicalScopeQuery,
    selectScope,
    selectScopeTarget,
  }
}
