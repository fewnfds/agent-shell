<script setup lang="ts">
import { LteAlert, LteButton } from '@adminlte/vue'
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { managementApi } from '@/api'
import PageShell from '@/components/PageShell.vue'
import RuntimeMonitoringScopeSelector from '@/components/runtime-monitoring/RuntimeMonitoringScopeSelector.vue'
import RuntimeNodeDetailsPanel from '@/components/runtime-monitoring/RuntimeNodeDetailsPanel.vue'
import RuntimeRunDetailsPanel from '@/components/runtime-monitoring/RuntimeRunDetailsPanel.vue'
import RuntimeRunIndex from '@/components/runtime-monitoring/RuntimeRunIndex.vue'
import RuntimeWorkflowCanvas from '@/components/runtime-monitoring/RuntimeWorkflowCanvas.vue'
import { useManagementError } from '@/composables/useManagementError'
import { useRuntimeMonitoringPage } from '@/composables/useRuntimeMonitoringPage'
import { useToasts } from '@/composables/useToasts'
import { triggerBrowserDownload } from '@/utils/download'

const { t } = useI18n()
const managementError = useManagementError()
const { notify } = useToasts()
const downloadingRunId = ref('')
const {
  lifecycleId,
  lifecycleSnapshot,
  snapshot,
  nodeCatalog,
  selectedRunId,
  graphResponse,
  nodeSummaryPage,
  nodeSummaryError,
  nodeSummaryRetrying,
  lifecycleLoading,
  runLoading,
  lifecycleError,
  catalogError,
  runError,
  pollRefreshing,
  pollError,
  nodeDetails,
  runDetails,
  selectedNodeId,
  selectedInvocationId,
  nodeAttemptPage,
  nodeAttemptLoading,
  nodeAttemptError,
  agentArtifact,
  agentArtifactLoading,
  agentArtifactError,
  agentProtocol,
  agentProtocolLoading,
  agentProtocolError,
  commandObservations,
  commandLoading,
  commandError,
  runDetailKind,
  runProtocol,
  runProtocolLoading,
  runProtocolError,
  runModels,
  runModelsLoading,
  runModelsError,
  runState,
  runStateLoading,
  runStateError,
  runRoots,
  selectedRun,
  graphDocument,
  selectedNode,
  selectedNodeSummary,
  lifecycleIsActive,
  displayedScope,
  scopeSelectorId,
  scopeWorkflows,
  localTime,
  availabilityLabel,
  graphEmptyMessage,
  selectScope,
  selectScopeTarget,
  pollOnce,
  loadLifecycle,
  selectRun,
  selectNode,
  closeNodeAttempts,
  openRunDetails,
  closeRunDetails,
  retryRun,
  retryNodeSummaries,
} = useRuntimeMonitoringPage()

async function downloadSelectedRun(): Promise<void> {
  const run = selectedRun.value
  if (!run || downloadingRunId.value) return
  const requestedLifecycleId = lifecycleId.value
  const requestedRunId = run.run_id
  downloadingRunId.value = requestedRunId
  try {
    const download = await managementApi.downloadWorkflowRun(
      requestedLifecycleId,
      requestedRunId,
    )
    triggerBrowserDownload(download.blob, download.filename)
  } catch (error) {
    notify({
      tone: 'danger',
      title: t('runtimeMonitoring.downloadRunFailed'),
      message: managementError.describe(error).display,
    })
  } finally {
    if (downloadingRunId.value === requestedRunId) downloadingRunId.value = ''
  }
}
</script>

<template>
  <PageShell>
    <div class="d-flex flex-wrap align-items-start justify-content-between gap-3 mb-3">
      <div class="runtime-monitoring-heading">
        <h1 class="h4 mb-1">{{ snapshot?.lifecycle.workflow_name || t('runtimeMonitoring.title') }}</h1>
        <p class="mb-0 text-body-secondary text-break">
          {{ t('runtimeMonitoring.lifecycleId') }}: {{ lifecycleId }}
        </p>
      </div>
      <div class="d-flex flex-wrap align-items-center gap-2">
        <span
          v-if="snapshot"
          class="badge"
          :class="lifecycleIsActive ? 'text-bg-success' : 'text-bg-secondary'"
          :title="lifecycleIsActive ? t('runtimeMonitoring.polling.activeHelp') : undefined"
        >
          <span
            v-if="pollRefreshing"
            class="spinner-border spinner-border-sm me-1"
            aria-hidden="true"
          />
          {{ lifecycleIsActive
            ? t('runtimeMonitoring.polling.active')
            : t('runtimeMonitoring.polling.terminal') }}
        </span>
        <LteButton
          v-if="snapshot"
          class="action-button"
          :disabled="pollRefreshing || lifecycleLoading"
          type="button"
          @click="pollOnce(true)"
        >
          <i class="bi bi-arrow-clockwise" aria-hidden="true" />
          {{ t('common.refresh') }}
        </LteButton>
        <RouterLink class="btn btn-outline-secondary action-button" to="/system/workflow-lifecycles">
          <i class="bi bi-arrow-left" aria-hidden="true" />
          {{ t('runtimeMonitoring.backToCatalog') }}
        </RouterLink>
      </div>
    </div>

    <RuntimeMonitoringScopeSelector
      v-if="lifecycleSnapshot"
      class="mb-3"
      :disabled="lifecycleLoading"
      :runs="lifecycleSnapshot.runs"
      :scope="displayedScope.scope"
      :selector-id="scopeSelectorId"
      :workflows="scopeWorkflows"
      @scope-change="selectScope"
      @selector-change="selectScopeTarget"
    />

    <div
      v-if="lifecycleLoading"
      class="d-flex align-items-center gap-2 p-3"
      aria-busy="true"
      role="status"
    >
      <span class="spinner-border" aria-hidden="true" />
      <span>{{ t('runtimeMonitoring.snapshot.loading') }}</span>
    </div>

    <LteAlert
      v-else-if="lifecycleError"
      :title="t('runtimeMonitoring.snapshot.loadFailed')"
      theme="danger"
    >
      <p class="runtime-monitoring-error mb-3 text-break">{{ lifecycleError }}</p>
      <LteButton class="action-button" type="button" @click="loadLifecycle">
        <i class="bi bi-arrow-clockwise" aria-hidden="true" />
        {{ t('common.retry') }}
      </LteButton>
    </LteAlert>

    <div v-else-if="pollError && snapshot" class="alert alert-warning" role="status">
      <p class="runtime-monitoring-error mb-0">{{ pollError }}</p>
    </div>

    <div
      v-if="snapshot && !lifecycleLoading && !lifecycleError"
      class="runtime-monitoring-layout"
      :data-detail-open="Boolean(selectedNode || runDetailKind)"
    >
      <aside class="card runtime-monitoring-run-panel">
        <header class="card-header">
          <div class="d-flex align-items-center justify-content-between gap-2">
            <h2 class="card-title mb-0">{{ t('runtimeMonitoring.runIndex.title') }}</h2>
            <span class="badge text-bg-secondary">
              {{ t('runtimeMonitoring.runIndex.count', { count: snapshot.summary.run_count }) }}
            </span>
          </div>
          <p class="mb-0 mt-2 small text-body-secondary">
            {{ t('runtimeMonitoring.runIndex.activeCount', {
              count: snapshot.summary.active_run_count,
            }) }}
          </p>
        </header>
        <div
          v-if="snapshot.forest.relationship_availability === 'partial'"
          class="alert alert-warning rounded-0 border-start-0 border-end-0 mb-0"
          role="status"
        >
          {{ t('runtimeMonitoring.runIndex.partial') }}
        </div>
        <div class="runtime-monitoring-run-scroll">
          <RuntimeRunIndex
            :orphan-run-ids="snapshot.forest.orphan_run_ids"
            :roots="runRoots"
            :selected-run-id="selectedRunId"
            @select="selectRun"
          />
        </div>
      </aside>

      <section class="card runtime-monitoring-graph-panel" aria-live="polite">
        <header class="card-header d-flex flex-wrap align-items-start justify-content-between gap-2">
          <div class="runtime-monitoring-heading">
            <h2 class="card-title mb-1">
              {{ selectedRun?.workflow_name || t('runtimeMonitoring.graph.title') }}
            </h2>
            <p v-if="selectedRun" class="mb-0 small text-body-secondary text-break">
              {{ selectedRun.run_id }} · {{ localTime(selectedRun.created_at) }}
            </p>
          </div>
          <div v-if="selectedRun" class="d-flex flex-wrap gap-2">
            <span class="badge text-bg-secondary">
              {{ t(`workflowLifecycles.runStatuses.${selectedRun.status}`) }}
            </span>
            <span v-if="graphResponse" class="badge text-bg-light border">
              {{ t('runtimeMonitoring.graph.availability', {
                value: availabilityLabel(graphResponse.availability),
              }) }}
            </span>
            <LteButton
              class="action-button"
              data-action="download-run"
              :aria-busy="Boolean(downloadingRunId)"
              :disabled="Boolean(downloadingRunId)"
              type="button"
              @click="downloadSelectedRun"
            >
              <span
                v-if="downloadingRunId"
                class="spinner-border spinner-border-sm"
                aria-hidden="true"
              />
              <i v-else class="bi bi-download" aria-hidden="true" />
              {{ t('runtimeMonitoring.downloadRun') }}
            </LteButton>
            <div class="btn-group btn-group-sm" role="group" :aria-label="t('runtimeMonitoring.runDetails.tabs')">
              <button class="btn btn-outline-secondary" type="button" @click="openRunDetails('protocol')">
                {{ t('runtimeMonitoring.runDetails.kinds.protocol') }}
              </button>
              <button class="btn btn-outline-secondary" type="button" @click="openRunDetails('models')">
                {{ t('runtimeMonitoring.runDetails.kinds.models') }}
              </button>
              <button class="btn btn-outline-secondary" type="button" @click="openRunDetails('state')">
                {{ t('runtimeMonitoring.runDetails.kinds.state') }}
              </button>
            </div>
          </div>
        </header>

        <div class="runtime-monitoring-graph-body">
          <div
            v-if="runLoading"
            class="d-flex align-items-center justify-content-center gap-2 h-100 p-3"
            aria-busy="true"
            role="status"
          >
            <span class="spinner-border" aria-hidden="true" />
            <span>{{ t('runtimeMonitoring.graph.loading') }}</span>
          </div>

          <div v-else-if="runError" class="p-3">
            <div class="alert alert-danger mb-0" role="alert">
              <p class="runtime-monitoring-error mb-3 text-break">{{ runError }}</p>
              <LteButton class="action-button" type="button" @click="retryRun">
                <i class="bi bi-arrow-clockwise" aria-hidden="true" />
                {{ t('common.retry') }}
              </LteButton>
            </div>
          </div>

          <div v-else-if="catalogError" class="p-3">
            <div class="alert alert-danger mb-0" role="alert">
              <p class="runtime-monitoring-error mb-3 text-break">{{ catalogError }}</p>
              <LteButton class="action-button" type="button" @click="loadLifecycle">
                <i class="bi bi-arrow-clockwise" aria-hidden="true" />
                {{ t('common.retry') }}
              </LteButton>
            </div>
          </div>

          <template v-else-if="graphDocument">
            <div
              v-if="graphResponse?.availability !== 'available'"
              class="alert alert-info rounded-0 border-start-0 border-end-0 mb-0"
              role="status"
            >
              {{ t('runtimeMonitoring.graph.partial', {
                availability: availabilityLabel(graphResponse?.availability ?? 'unavailable'),
              }) }}
            </div>
            <div
              v-if="nodeSummaryError"
              class="alert alert-warning rounded-0 border-start-0 border-end-0 mb-0"
              role="alert"
            >
              <p class="runtime-monitoring-error mb-2">{{ nodeSummaryError }}</p>
              <LteButton
                class="btn btn-sm btn-outline-secondary"
                :disabled="nodeSummaryRetrying"
                type="button"
                @click="retryNodeSummaries"
              >
                <span
                  v-if="nodeSummaryRetrying"
                  class="spinner-border spinner-border-sm"
                  aria-hidden="true"
                />
                <i v-else class="bi bi-arrow-clockwise" aria-hidden="true" />
                {{ t('common.retry') }}
              </LteButton>
            </div>
            <div
              v-if="nodeSummaryPage && nodeSummaryPage.availability !== 'available'"
              class="alert alert-warning rounded-0 border-start-0 border-end-0 mb-0"
              role="status"
            >
              {{ t('runtimeMonitoring.graph.nodeSummaryPartial', {
                availability: availabilityLabel(nodeSummaryPage.availability),
              }) }}
            </div>
            <RuntimeWorkflowCanvas
              :key="selectedRunId"
              :document="graphDocument"
              :node-catalog="nodeCatalog"
              :node-summaries="nodeSummaryPage?.items ?? []"
              :selected-node-id="selectedNodeId"
              @select-node="selectNode"
            />
          </template>

          <p v-else class="m-0 p-4 text-center text-body-secondary" role="status">
            {{ graphEmptyMessage() }}
          </p>
        </div>
      </section>

      <RuntimeNodeDetailsPanel
        v-if="selectedNode"
        :agent-artifact="agentArtifact"
        :agent-artifact-error="agentArtifactError"
        :agent-artifact-loading="agentArtifactLoading"
        :agent-protocol="agentProtocol"
        :agent-protocol-error="agentProtocolError"
        :agent-protocol-loading="agentProtocolLoading"
        :command-error="commandError"
        :command-loading="commandLoading"
        :command-observations="commandObservations"
        :error="nodeAttemptError"
        :loading="nodeAttemptLoading"
        :node-id="selectedNode.id"
        :node-type="selectedNode.type"
        :page="nodeAttemptPage"
        :selected-invocation-id="selectedInvocationId"
        :summary="selectedNodeSummary"
        @close="closeNodeAttempts"
        @page-change="nodeDetails.changePage"
        @page-size-change="nodeDetails.changePageSize"
        @retry="nodeDetails.retryAttempts"
        @retry-agent-artifact="nodeDetails.retryAgentArtifact"
        @retry-agent-protocol="nodeDetails.retryAgentProtocol"
        @retry-command="nodeDetails.retryCommand"
        @select-invocation="nodeDetails.selectInvocation"
        @view-latest="nodeDetails.viewLatest"
      />
      <RuntimeRunDetailsPanel
        v-else-if="runDetailKind && selectedRun"
        :active-kind="runDetailKind"
        :model-page="runModels"
        :models-error="runModelsError"
        :models-loading="runModelsLoading"
        :protocol="runProtocol"
        :protocol-error="runProtocolError"
        :protocol-loading="runProtocolLoading"
        :run-id="selectedRun.run_id"
        :run-name="selectedRun.workflow_name"
        :state="runState"
        :state-error="runStateError"
        :state-loading="runStateLoading"
        @close="closeRunDetails"
        @model-page-change="runDetails.changeModelPage"
        @model-page-size-change="runDetails.changeModelPageSize"
        @retry-models="runDetails.retryModels"
        @retry-protocol="runDetails.retryProtocol"
        @retry-state="runDetails.retryState"
        @select-kind="openRunDetails"
      />
    </div>
  </PageShell>
</template>
