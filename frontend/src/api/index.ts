import {
  buildQuery,
  managementAuth,
  managementDownload,
  managementNamedDownload,
  managementRequest,
  managementUpload,
  watchManagementEvents,
} from './transport'
import type {
  ApiServerSettings,
  ApiServerSettingsUpdate,
  BlockPayload,
  ManagedComponentType,
  CatalogResponse,
  ConfigurationValidationSettings,
  ConfigurationBundleImportResult,
  ConfigurationBundlePreview,
  ConfigurationBundleResolutions,
  ConfigurationBundleRoot,
  ConfigurationRepository,
  ConfigurationRepositoryActivation,
  ConfigurationRepositoryList,
  ConfigurationCollection,
  ConfigurationOptions,
  ConfigurationSummary,
  MainAgentSummary,
  RuntimeMonitoringGraphResponse,
  RuntimeMonitoringNodeSummaryPage,
  RuntimeMonitoringSnapshot,
  RuntimePolicySettings,
  RuntimePolicyUpdate,
  PythonPackageTemplate,
  DraftValidationRequest,
  EventFeedFilters,
  EventFeedResponse,
  EventSource,
  HealthResponse,
  ManagementEvent,
  NamedDownload,
  Workflow,
  WorkflowSummary,
  WorkflowLifecyclePage,
  WorkflowLifecycleBulkDeleteResult,
  WorkflowGraphDocument,
  WorkflowNodeCatalogItem,
  WorkflowPayload,
  WorkflowRole,
  ManagedArchivePreview,
  ManagedDirectory,
  ManagedFileUploadResult,
  ManagedTextFile,
  MessageInterception,
  ModelProviderCatalog,
  ModelConnection,
  ModelRequirementBinding,
  McpConnection,
  McpInstallationResult,
  McpImportPreview,
  McpImportValueSources,
  McpRequirementBinding,
  PythonPackageInspection,
  MainAgent,
  MainAgentPayload,
  ReadinessResponse,
  ResourceCatalog,
  RuntimeDiagnostics,
  SavedBlock,
  SkillResource,
  SkillPackageInspection,
  Subagent,
  SubagentSummary,
  SubagentPayload,
  SystemLogSettings,
  SystemSettings,
  SystemSettingsUpdate,
  ValidationReport,
} from './types'

export * from './transport'
export type * from './types'

function jsonBody(payload: unknown): Pick<RequestInit, 'body' | 'method'> {
  return { method: 'POST', body: JSON.stringify(payload) }
}

function withoutId<T extends object>(value: T): Omit<T, 'id'> {
  const copy = { ...value } as T & { id?: unknown }
  delete copy.id
  return copy
}

function recordPath(base: string, id: string): string {
  return `${base}/${encodeURIComponent(id)}`
}

export const managementApi = {
  clearManagementToken(): void {
    managementAuth.clear()
  },

  getHealth(): Promise<HealthResponse> {
    return managementRequest('/api/health')
  },

  getReadiness(): Promise<ReadinessResponse> {
    return managementRequest('/api/readiness')
  },

  getCatalog(): Promise<CatalogResponse> {
    return managementRequest('/api/catalog')
  },

  getConfigurationOptions(): Promise<ConfigurationOptions> {
    return managementRequest('/api/configuration-options')
  },

  fetchModels(
    provider: string,
    baseUrl: string,
    credential: string | null,
    blockId = '',
  ): Promise<string[]> {
    return managementRequest('/api/fetch-models', jsonBody({
      provider,
      base_url: baseUrl,
      credential,
      block_id: blockId,
    }))
  },

  listModelProviders(): Promise<ModelProviderCatalog> {
    return managementRequest('/api/model-providers')
  },

  listModelConnections(): Promise<ModelConnection[]> {
    return managementRequest('/api/model-connections')
  },

  getModelConnection(id: string): Promise<ModelConnection> {
    return managementRequest(recordPath('/api/model-connections', id))
  },

  saveModelConnection<T extends object>(data: T & { id?: string }): Promise<ModelConnection> {
    const id = typeof data.id === 'string' ? data.id : ''
    return managementRequest(id ? recordPath('/api/model-connections', id) : '/api/model-connections', {
      method: id ? 'PUT' : 'POST',
      body: JSON.stringify(withoutId(data)),
    })
  },

  copyModelConnection(id: string, name: string): Promise<ModelConnection> {
    return managementRequest(`${recordPath('/api/model-connections', id)}/copy`, jsonBody({ name }))
  },

  deleteModelConnection(id: string): Promise<{ ok: boolean }> {
    return managementRequest(recordPath('/api/model-connections', id), { method: 'DELETE' })
  },

  listModelRequirements(): Promise<ModelRequirementBinding[]> {
    return managementRequest('/api/model-requirements')
  },

  bindModelRequirement(id: string, connectionId: string | null): Promise<ModelRequirementBinding> {
    return managementRequest(`${recordPath('/api/model-requirements', id)}/binding`, {
      method: 'PUT',
      body: JSON.stringify({ connection_id: connectionId }),
    })
  },

  listMcpConnections(): Promise<McpConnection[]> {
    return managementRequest('/api/mcp-connections')
  },

  getMcpConnection(id: string): Promise<McpConnection> {
    return managementRequest(recordPath('/api/mcp-connections', id))
  },

  saveMcpConnection<T extends object>(data: T & { id?: string }): Promise<McpConnection> {
    const id = typeof data.id === 'string' ? data.id : ''
    return managementRequest(id ? recordPath('/api/mcp-connections', id) : '/api/mcp-connections', {
      method: id ? 'PUT' : 'POST',
      body: JSON.stringify(withoutId(data)),
    })
  },

  copyMcpConnection(id: string, name: string): Promise<McpConnection> {
    return managementRequest(`${recordPath('/api/mcp-connections', id)}/copy`, jsonBody({ name }))
  },

  installMcpConnection(id: string): Promise<McpInstallationResult> {
    return managementRequest(`${recordPath('/api/mcp-connections', id)}/install`, {
      method: 'POST',
    })
  },

  deleteMcpConnection(id: string): Promise<{ ok: boolean }> {
    return managementRequest(recordPath('/api/mcp-connections', id), { method: 'DELETE' })
  },

  previewMcpConnectionsImport(document: unknown): Promise<McpImportPreview> {
    return managementRequest('/api/mcp-connections/import/preview', jsonBody({ document }))
  },

  importMcpConnections(
    document: unknown,
    valueSources: McpImportValueSources,
  ): Promise<McpConnection[]> {
    return managementRequest('/api/mcp-connections/import', jsonBody({
      document,
      value_sources: valueSources,
    }))
  },

  listMcpRequirements(): Promise<McpRequirementBinding[]> {
    return managementRequest('/api/mcp-requirements')
  },

  bindMcpRequirement(id: string, connectionId: string | null): Promise<McpRequirementBinding> {
    return managementRequest(`${recordPath('/api/mcp-requirements', id)}/binding`, {
      method: 'PUT',
      body: JSON.stringify({ connection_id: connectionId }),
    })
  },

  listCustomToolTemplates(): Promise<ResourceCatalog<PythonPackageTemplate>> {
    return managementRequest('/api/python-package-templates/custom-tool')
  },

  listMiddlewareTemplates(): Promise<ResourceCatalog<PythonPackageTemplate>> {
    return managementRequest('/api/python-package-templates/middleware')
  },

  listAgentEventOutputTemplates(): Promise<ResourceCatalog<PythonPackageTemplate>> {
    return managementRequest('/api/python-package-templates/agent-event-output')
  },

  listWorkflowEventOutputTemplates(): Promise<ResourceCatalog<PythonPackageTemplate>> {
    return managementRequest('/api/python-package-templates/workflow-event-output')
  },

  listCommandTemplates(): Promise<ResourceCatalog<PythonPackageTemplate>> {
    return managementRequest('/api/python-package-templates/command')
  },

  listSkills(): Promise<ResourceCatalog<SkillResource>> {
    return managementRequest('/api/skills')
  },

  inspectPrivateSkills(blockId: string): Promise<SkillPackageInspection> {
    return managementRequest(`${recordPath('/api/blocks/skill', blockId)}/skills`)
  },

  addPrivateSkill(blockId: string, templatePath: string): Promise<SkillPackageInspection> {
    return managementRequest(
      `${recordPath('/api/blocks/skill', blockId)}/skills`,
      jsonBody({ template_path: templatePath }),
    )
  },

  deletePrivateSkill(blockId: string, folder: string): Promise<SkillPackageInspection> {
    return managementRequest(
      `${recordPath('/api/blocks/skill', blockId)}/skills/${encodeURIComponent(folder)}`,
      { method: 'DELETE' },
    )
  },

  listConfigurationRepositories(): Promise<ConfigurationRepositoryList> {
    return managementRequest('/api/configuration-repositories')
  },

  createConfigurationRepository(name: string): Promise<ConfigurationRepository> {
    return managementRequest('/api/configuration-repositories', jsonBody({ name }))
  },

  activateConfigurationRepository(id: string): Promise<ConfigurationRepositoryActivation> {
    return managementRequest(
      `${recordPath('/api/configuration-repositories', id)}/activate`,
      { method: 'POST' },
    )
  },

  copyConfigurationRepository(id: string, name: string): Promise<ConfigurationRepository> {
    return managementRequest(
      `${recordPath('/api/configuration-repositories', id)}/copy`,
      jsonBody({ name }),
    )
  },

  downloadConfigurationRepository(id: string): Promise<NamedDownload> {
    return managementNamedDownload(
      `${recordPath('/api/configuration-repositories', id)}/download`,
    )
  },

  deleteConfigurationRepository(id: string): Promise<{ ok: boolean }> {
    return managementRequest(recordPath('/api/configuration-repositories', id), {
      method: 'DELETE',
    })
  },

  exportConfigurationBundle(root: ConfigurationBundleRoot): Promise<NamedDownload> {
    return managementNamedDownload(
      '/api/configuration-bundles/export',
      jsonBody(root),
    )
  },

  previewConfigurationBundle(bundle: File): Promise<ConfigurationBundlePreview> {
    const body = new FormData()
    body.append('bundle', bundle, bundle.name)
    return managementRequest('/api/configuration-bundles/preview', {
      method: 'POST',
      body,
    })
  },

  importConfigurationBundle(
    bundle: File,
    bundleSha256: string,
    planToken: string,
    resolutions: ConfigurationBundleResolutions,
  ): Promise<ConfigurationBundleImportResult> {
    const body = new FormData()
    body.append('bundle', bundle, bundle.name)
    body.append('request', JSON.stringify({
      bundle_sha256: bundleSha256,
      plan_token: planToken,
      resolutions,
    }))
    return managementRequest('/api/configuration-bundles/import', {
      method: 'POST',
      body,
    })
  },

  listWorkflowSummaries(
    workflowRole?: WorkflowRole,
    request?: { q?: string, offset?: number, limit?: number },
  ): Promise<ConfigurationCollection<WorkflowSummary>> {
    return managementRequest(`/api/workflows${buildQuery({
      workflow_role: workflowRole,
      view: 'summary',
      q: request?.q,
      offset: request?.offset,
      limit: request?.limit,
    })}`)
  },

  listWorkflowNodeCatalog(): Promise<WorkflowNodeCatalogItem[]> {
    return managementRequest('/api/workflow-node-catalog')
  },

  getWorkflow(id: string): Promise<Workflow> {
    return managementRequest(`/api/workflows/${encodeURIComponent(id)}`)
  },

  createWorkflow(payload: WorkflowPayload): Promise<Workflow> {
    return managementRequest('/api/workflows', jsonBody(payload))
  },

  copyWorkflow(id: string, name: string): Promise<Workflow> {
    return managementRequest(`/api/workflows/${encodeURIComponent(id)}/copy`, jsonBody({ name }))
  },

  updateWorkflow(id: string, payload: WorkflowPayload): Promise<Workflow> {
    return managementRequest(`/api/workflows/${id}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    })
  },

  deleteWorkflow(id: string): Promise<{ ok: boolean }> {
    return managementRequest(`/api/workflows/${id}`, { method: 'DELETE' })
  },

  deleteWorkflows(ids: string[]): Promise<{ deleted: number }> {
    return managementRequest('/api/workflows/delete', jsonBody({ ids }))
  },

  deleteWorkflowsMatching(query: string, workflowRole?: WorkflowRole): Promise<{ deleted: number }> {
    return managementRequest('/api/workflows/delete', jsonBody({
      q: query,
      workflow_role: workflowRole,
    }))
  },

  listWorkflowLifecycles(
    request?: { page?: number; page_size?: number; query?: string },
  ): Promise<WorkflowLifecyclePage> {
    const params = new URLSearchParams()
    if (request?.page !== undefined) params.set('page', String(request.page))
    if (request?.page_size !== undefined) params.set('page_size', String(request.page_size))
    if (request?.query) params.set('query', request.query)
    const query = params.toString()
    return managementRequest(`/api/workflow-lifecycles${query ? `?${query}` : ''}`)
  },

  deleteWorkflowLifecycle(id: string): Promise<{ ok: boolean }> {
    return managementRequest(
      `/api/workflow-lifecycles/${encodeURIComponent(id)}`,
      { method: 'DELETE' },
    )
  },

  deleteWorkflowLifecyclesMatching(query: string): Promise<WorkflowLifecycleBulkDeleteResult> {
    return managementRequest('/api/workflow-lifecycles/delete', jsonBody({
      query,
    }))
  },

  getRuntimeMonitoringSnapshot(
    lifecycleId: string,
    signal?: AbortSignal,
  ): Promise<RuntimeMonitoringSnapshot> {
    return managementRequest(
      `/api/workflow-lifecycles/${encodeURIComponent(lifecycleId)}/monitoring/snapshot`,
      { signal },
    )
  },

  getRuntimeMonitoringGraph(
    lifecycleId: string,
    runId: string,
    signal?: AbortSignal,
  ): Promise<RuntimeMonitoringGraphResponse> {
    return managementRequest(
      `/api/workflow-lifecycles/${encodeURIComponent(lifecycleId)}`
        + `/monitoring/runs/${encodeURIComponent(runId)}/graph`,
      { signal },
    )
  },

  listRuntimeMonitoringNodes(
    lifecycleId: string,
    runId: string,
    request?: { page?: number; page_size?: number },
    signal?: AbortSignal,
  ): Promise<RuntimeMonitoringNodeSummaryPage> {
    return managementRequest(
      `/api/workflow-lifecycles/${encodeURIComponent(lifecycleId)}`
        + `/monitoring/runs/${encodeURIComponent(runId)}/nodes${buildQuery({
          page: request?.page,
          page_size: request?.page_size,
        })}`,
      { signal },
    )
  },

  getWorkflowGraph(id: string): Promise<WorkflowGraphDocument> {
    return managementRequest(`/api/workflows/${encodeURIComponent(id)}/graph`)
  },

  saveWorkflowDraft(
    id: string,
    document: WorkflowGraphDocument,
  ): Promise<WorkflowGraphDocument> {
    return managementRequest(`/api/workflows/${encodeURIComponent(id)}/draft`, {
      method: 'PUT',
      body: JSON.stringify(document),
    })
  },

  publishWorkflow(
    id: string,
    document: WorkflowGraphDocument,
  ): Promise<WorkflowGraphDocument> {
    return managementRequest(`/api/workflows/${encodeURIComponent(id)}/graph`, {
      method: 'PUT',
      body: JSON.stringify(document),
    })
  },

  validateWorkflow(
    id: string,
    document: WorkflowGraphDocument,
  ): Promise<ValidationReport> {
    return managementRequest(`/api/workflows/${encodeURIComponent(id)}/validate`, {
      method: 'POST',
      body: JSON.stringify(document),
    })
  },

  getSystemSettings(): Promise<SystemSettings> {
    return managementRequest('/api/system/settings')
  },

  updateSystemSettings(payload: SystemSettingsUpdate): Promise<SystemSettings> {
    return managementRequest('/api/system/settings', {
      method: 'PUT',
      body: JSON.stringify(payload),
    })
  },

  getRuntimePolicy(): Promise<RuntimePolicySettings> {
    return managementRequest('/api/system/runtime-policy')
  },

  updateRuntimePolicy(payload: RuntimePolicyUpdate): Promise<RuntimePolicySettings> {
    return managementRequest('/api/system/runtime-policy', {
      method: 'PUT',
      body: JSON.stringify(payload),
    })
  },

  listManagedFiles(path = 'data'): Promise<ManagedDirectory> {
    return managementRequest(`/api/file-manager${buildQuery({ path })}`)
  },

  createManagedDirectory(path: string): Promise<{ path: string }> {
    return managementRequest('/api/file-manager/directories', jsonBody({ path }))
  },

  createManagedTextFile(path: string): Promise<{ path: string }> {
    return managementRequest('/api/file-manager/text-files', jsonBody({ path }))
  },

  uploadManagedFile(
    path: string,
    file: Blob,
    overwrite: boolean,
    onProgress?: (loaded: number, total: number) => void,
  ): Promise<ManagedFileUploadResult> {
    return managementUpload(
      `/api/file-manager/upload${buildQuery({ path, overwrite })}`,
      file,
      { onProgress },
    )
  },

  downloadManagedEntry(path: string): Promise<Blob> {
    return managementDownload(
      `/api/file-manager/download${buildQuery({ path })}`,
    )
  },

  previewManagedArchive(
    paths: string[],
  ): Promise<ManagedArchivePreview> {
    return managementRequest('/api/file-manager/archive/preview', jsonBody({ paths }))
  },

  downloadManagedArchive(paths: string[]): Promise<Blob> {
    return managementDownload('/api/file-manager/archive', jsonBody({ paths }))
  },

  readManagedTextFile(path: string): Promise<ManagedTextFile> {
    return managementRequest(
      `/api/file-manager/text${buildQuery({ path })}`,
    )
  },

  saveManagedTextFile(
    path: string,
    content: string,
    revision: string,
  ): Promise<{ path: string; revision: string }> {
    return managementRequest('/api/file-manager/text', {
      method: 'PUT',
      body: JSON.stringify({ path, content, revision }),
    })
  },

  renameManagedEntry(
    path: string,
    name: string,
  ): Promise<{ path: string }> {
    return managementRequest('/api/file-manager', {
      method: 'PATCH',
      body: JSON.stringify({ path, name }),
    })
  },

  deleteManagedFile(path: string): Promise<{ deleted: boolean }> {
    return managementRequest(
      `/api/file-manager${buildQuery({ path })}`,
      { method: 'DELETE' },
    )
  },

  listBlockSummaries(
    type: ManagedComponentType,
    request?: { q?: string, offset?: number, limit?: number },
  ): Promise<ConfigurationCollection<ConfigurationSummary>> {
    return managementRequest(`/api/blocks/${type}${buildQuery({
      view: 'summary',
      q: request?.q,
      offset: request?.offset,
      limit: request?.limit,
    })}`)
  },

  getBlock<TPayload extends BlockPayload = BlockPayload>(
    type: ManagedComponentType,
    id: string,
  ): Promise<SavedBlock<TPayload>> {
    return managementRequest(recordPath(`/api/blocks/${type}`, id))
  },

  inspectPythonPackage(
    type: ManagedComponentType,
    id: string,
  ): Promise<PythonPackageInspection> {
    return managementRequest(
      `${recordPath(`/api/blocks/${type}`, id)}/python-package`,
    )
  },

  saveBlock<TPayload extends BlockPayload>(
    type: ManagedComponentType,
    data: TPayload | SavedBlock<TPayload>,
  ): Promise<SavedBlock<TPayload>> {
    const id = 'id' in data && typeof data.id === 'string' ? data.id : ''
    const path = id ? recordPath(`/api/blocks/${type}`, id) : `/api/blocks/${type}`
    return managementRequest(path, {
      method: id ? 'PUT' : 'POST',
      body: JSON.stringify(withoutId(data)),
    })
  },

  copyBlock<TPayload extends BlockPayload = BlockPayload>(
    type: ManagedComponentType,
    id: string,
    name: string,
  ): Promise<SavedBlock<TPayload>> {
    return managementRequest(`${recordPath(`/api/blocks/${type}`, id)}/copy`, jsonBody({ name }))
  },

  deleteBlock(type: ManagedComponentType, id: string): Promise<{ ok: boolean }> {
    return managementRequest(recordPath(`/api/blocks/${type}`, id), { method: 'DELETE' })
  },

  deleteUnsupportedBlock(id: string): Promise<{ ok: boolean }> {
    return managementRequest(recordPath('/api/unsupported-blocks', id), { method: 'DELETE' })
  },

  deleteBlocks(type: ManagedComponentType, ids: string[]): Promise<{ deleted: number }> {
    return managementRequest(`/api/blocks/${type}/delete`, jsonBody({ ids }))
  },

  deleteBlocksMatching(type: ManagedComponentType, query: string): Promise<{ deleted: number }> {
    return managementRequest(`/api/blocks/${type}/delete`, jsonBody({ q: query }))
  },

  validateRepository(): Promise<ValidationReport> {
    return managementRequest('/api/validation/repository')
  },

  validateDraft(request: DraftValidationRequest): Promise<ValidationReport> {
    return managementRequest('/api/validation/draft', jsonBody(request))
  },

  getValidationSettings(): Promise<ConfigurationValidationSettings> {
    return managementRequest('/api/validation/settings')
  },

  updateValidationSettings(debounceMs: number): Promise<ConfigurationValidationSettings> {
    return managementRequest('/api/validation/settings', {
      method: 'PUT',
      body: JSON.stringify({ debounce_ms: debounceMs }),
    })
  },

  listMainAgentSummaries(
    request?: { q?: string, offset?: number, limit?: number },
  ): Promise<ConfigurationCollection<MainAgentSummary>> {
    return managementRequest(`/api/main-agents${buildQuery({
      view: 'summary',
      q: request?.q,
      offset: request?.offset,
      limit: request?.limit,
    })}`)
  },

  getMainAgent(id: string): Promise<MainAgent> {
    return managementRequest(recordPath('/api/main-agents', id))
  },

  saveMainAgent(data: MainAgentPayload | MainAgent): Promise<MainAgent> {
    const id = 'id' in data ? data.id : ''
    return managementRequest(id ? recordPath('/api/main-agents', id) : '/api/main-agents', {
      method: id ? 'PUT' : 'POST',
      body: JSON.stringify(withoutId(data)),
    })
  },

  copyMainAgent(id: string, name: string): Promise<MainAgent> {
    return managementRequest(`${recordPath('/api/main-agents', id)}/copy`, jsonBody({ name }))
  },

  deleteMainAgent(id: string): Promise<{ ok: boolean }> {
    return managementRequest(recordPath('/api/main-agents', id), { method: 'DELETE' })
  },

  deleteMainAgents(ids: string[]): Promise<{ deleted: number }> {
    return managementRequest('/api/main-agents/delete', jsonBody({ ids }))
  },

  deleteMainAgentsMatching(query: string): Promise<{ deleted: number }> {
    return managementRequest('/api/main-agents/delete', jsonBody({ q: query }))
  },

  listSubagentSummaries(
    request?: { q?: string, offset?: number, limit?: number },
  ): Promise<ConfigurationCollection<SubagentSummary>> {
    return managementRequest(`/api/subagents${buildQuery({
      view: 'summary',
      q: request?.q,
      offset: request?.offset,
      limit: request?.limit,
    })}`)
  },

  getSubagent(id: string): Promise<Subagent> {
    return managementRequest(recordPath('/api/subagents', id))
  },

  saveSubagent(
    data: SubagentPayload | Subagent,
  ): Promise<Subagent> {
    const id = 'id' in data ? data.id : ''
    return managementRequest(
      id ? recordPath('/api/subagents', id) : '/api/subagents',
      {
        method: id ? 'PUT' : 'POST',
        body: JSON.stringify(withoutId(data)),
      },
    )
  },

  copySubagent(id: string, componentName: string): Promise<Subagent> {
    return managementRequest(
      `${recordPath('/api/subagents', id)}/copy`,
      jsonBody({ component_name: componentName }),
    )
  },

  deleteSubagent(id: string): Promise<{ ok: boolean }> {
    return managementRequest(recordPath('/api/subagents', id), { method: 'DELETE' })
  },

  deleteSubagents(ids: string[]): Promise<{ deleted: number }> {
    return managementRequest('/api/subagents/delete', jsonBody({ ids }))
  },

  deleteSubagentsMatching(query: string): Promise<{ deleted: number }> {
    return managementRequest('/api/subagents/delete', jsonBody({ q: query }))
  },

  getApiServer(): Promise<ApiServerSettings> {
    return managementRequest('/api/api-server')
  },

  saveApiServer(update: ApiServerSettingsUpdate): Promise<ApiServerSettings> {
    return managementRequest('/api/api-server', {
      method: 'PUT',
      body: JSON.stringify(update),
    })
  },

  startApiServer(): Promise<ApiServerSettings> {
    return managementRequest('/api/api-server/start', { method: 'POST' })
  },

  stopApiServer(): Promise<ApiServerSettings> {
    return managementRequest('/api/api-server/stop', { method: 'POST' })
  },

  getMessageInterception(): Promise<MessageInterception> {
    return managementRequest('/api/message-interception')
  },

  updateMessageInterception(enabled: boolean): Promise<MessageInterception> {
    return managementRequest('/api/message-interception', {
      method: 'PUT',
      body: JSON.stringify({ enabled }),
    })
  },

  watchApiServerEvents(
    onEvent: (event: ManagementEvent) => void,
    onError?: (error: unknown) => void,
  ): () => void {
    return watchManagementEvents(
      '/api/api-server/events',
      onEvent,
      onError ? { onError } : {},
    )
  },

  listEventFeed(filters: EventFeedFilters): Promise<EventFeedResponse> {
    return managementRequest(`/api/event-feed${buildQuery({
      started_at: filters.started_at,
      ended_at: filters.ended_at,
      page: filters.page,
      page_size: filters.page_size,
      source: filters.source,
      level: filters.level,
      query: filters.query,
    })}`)
  },

  downloadEvent(source: EventSource, id: string): Promise<Blob> {
    const path = `/api/event-feed/${source}/${encodeURIComponent(id)}/download`
    return managementDownload(path)
  },

  getSystemLogSettings(): Promise<SystemLogSettings> {
    return managementRequest('/api/event-feed/system/settings')
  },

  updateSystemLogSettings(maxSizeMib: number): Promise<SystemLogSettings> {
    return managementRequest('/api/event-feed/system/settings', {
      method: 'PUT',
      body: JSON.stringify({ max_size_mib: maxSizeMib }),
    })
  },

  deleteMatchingEventFeed(filters: EventFeedFilters): Promise<{ deleted: number }> {
    return managementRequest('/api/event-feed/delete', jsonBody({
      started_at: filters.started_at,
      ended_at: filters.ended_at,
      source: filters.source ?? [],
      level: filters.level ?? [],
      query: filters.query ?? '',
    }))
  },

  getRuntimeDiagnostics(): Promise<RuntimeDiagnostics> {
    return managementRequest('/api/runtime-diagnostics')
  },

  updateRuntimeDiagnosticRetention(retentionLimit: number): Promise<RuntimeDiagnostics> {
    return managementRequest('/api/runtime-diagnostics/retention', {
      method: 'PUT',
      body: JSON.stringify({ retention_limit: retentionLimit }),
    })
  },

}
