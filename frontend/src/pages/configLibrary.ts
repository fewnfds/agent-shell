import type {
  ManagedComponentType,
  CatalogResponse,
  ConfigurationCollection,
  ConfigurationBundleImportResult,
  ConfigurationBundlePreview,
  ConfigurationBundleResolutions,
  ConfigurationBundleRoot,
  ConfigurationSummary,
  MainAgent,
  MainAgentSummary,
  McpTool,
  McpToolSummary,
  ModelConnection,
  McpConnection,
  NamedDownload,
  SavedBlock,
  Subagent,
  SubagentSummary,
  ValidationReport,
  Workflow,
  WorkflowSummary,
} from '@/api'

export type LibraryCategoryId = ManagedComponentType | 'main-agent' | 'subagent-profile' | 'workflow' | 'mcp-tool' | 'model-connection' | 'mcp-connection'
export type LibraryItem = ConfigurationSummary | MainAgentSummary | McpConnection | McpToolSummary | ModelConnection | SubagentSummary | WorkflowSummary
export type LibraryDetailItem = SavedBlock | MainAgent | McpConnection | McpTool | ModelConnection | Subagent | Workflow
type BundleCategoryId = Exclude<LibraryCategoryId, 'model-connection' | 'mcp-connection'>
type SummaryRequest = { q?: string, offset?: number, limit?: number }

export interface ConfigLibraryApi {
  getCatalog(): Promise<CatalogResponse>
  validateRepository(): Promise<ValidationReport>
  listBlockSummaries(type: ManagedComponentType, request?: SummaryRequest): Promise<ConfigurationCollection<ConfigurationSummary>>
  listMainAgentSummaries(request?: SummaryRequest): Promise<ConfigurationCollection<MainAgentSummary>>
  listSubagentSummaries(request?: SummaryRequest): Promise<ConfigurationCollection<SubagentSummary>>
  listWorkflowSummaries(request?: SummaryRequest): Promise<ConfigurationCollection<WorkflowSummary>>
  listMcpToolSummaries(request?: SummaryRequest): Promise<ConfigurationCollection<McpToolSummary>>
  listModelConnections(): Promise<ModelConnection[]>
  listMcpConnections(): Promise<McpConnection[]>
  getBlock(type: ManagedComponentType, id: string): Promise<SavedBlock>
  getMainAgent(id: string): Promise<MainAgent>
  getSubagent(id: string): Promise<Subagent>
  getWorkflow(id: string): Promise<Workflow>
  getMcpTool(id: string): Promise<McpTool>
  getModelConnection(id: string): Promise<ModelConnection>
  getMcpConnection(id: string): Promise<McpConnection>
  copyBlock(type: ManagedComponentType, id: string, name: string): Promise<SavedBlock>
  copyMainAgent(id: string, name: string): Promise<MainAgent>
  copySubagent(id: string, componentName: string): Promise<Subagent>
  copyWorkflow(id: string, name: string): Promise<Workflow>
  copyMcpTool(id: string, name: string): Promise<McpTool>
  copyModelConnection(id: string, name: string): Promise<ModelConnection>
  copyMcpConnection(id: string, name: string): Promise<McpConnection>
  deleteBlock(type: ManagedComponentType, id: string): Promise<{ ok: boolean }>
  deleteUnsupportedBlock(id: string): Promise<{ ok: boolean }>
  deleteMainAgent(id: string): Promise<{ ok: boolean }>
  deleteSubagent(id: string): Promise<{ ok: boolean }>
  deleteWorkflow(id: string): Promise<{ ok: boolean }>
  deleteMcpTool(id: string): Promise<{ ok: boolean }>
  deleteModelConnection(id: string): Promise<{ ok: boolean }>
  deleteMcpConnection(id: string): Promise<{ ok: boolean }>
  deleteBlocks(type: ManagedComponentType, ids: string[]): Promise<{ deleted: number }>
  deleteBlocksMatching(type: ManagedComponentType, query: string): Promise<{ deleted: number }>
  deleteMainAgents(ids: string[]): Promise<{ deleted: number }>
  deleteMainAgentsMatching(query: string): Promise<{ deleted: number }>
  deleteSubagents(ids: string[]): Promise<{ deleted: number }>
  deleteSubagentsMatching(query: string): Promise<{ deleted: number }>
  deleteWorkflows(ids: string[]): Promise<{ deleted: number }>
  deleteWorkflowsMatching(query: string): Promise<{ deleted: number }>
  deleteMcpTools(ids: string[]): Promise<{ deleted: number }>
  deleteMcpToolsMatching(query: string): Promise<{ deleted: number }>
  exportConfigurationBundle(root: ConfigurationBundleRoot): Promise<NamedDownload>
  previewConfigurationBundle(bundle: File): Promise<ConfigurationBundlePreview>
  importConfigurationBundle(bundle: File, digest: string, planToken: string, resolutions: ConfigurationBundleResolutions): Promise<ConfigurationBundleImportResult>
}

export const agentLibraryCategories = [
  'main-agent',
  'subagent-profile',
] as const

export const workflowLibraryCategories = ['workflow', 'mcp-tool'] as const
export const globalLibraryCategories = ['configuration-repositories', 'model-connection', 'mcp-connection'] as const

export function routeCategory(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

export function editLocation(category: LibraryCategoryId, id: string): {
  path: string
  query: { id: string }
} {
  if (category === 'main-agent') return { path: '/agents/main', query: { id } }
  if (category === 'subagent-profile') return { path: '/agents/subagents', query: { id } }
  if (category === 'workflow') return { path: '/workflows', query: { id } }
  if (category === 'mcp-tool') return { path: '/workflows/mcp-tools', query: { id } }
  if (category === 'model-connection') return { path: '/models/connections', query: { id } }
  if (category === 'mcp-connection') return { path: '/mcp/connections', query: { id } }
  if (
    category === 'workflow-event-output'
    || category === 'command'
    || category === 'python-schema'
  ) {
    return { path: `/workflow-components/${category}`, query: { id } }
  }
  return { path: `/agent-components/${category}`, query: { id } }
}

export function bundleRoot(category: BundleCategoryId, id: string): ConfigurationBundleRoot {
  if (category === 'main-agent') return { kind: 'main_agent', source_id: id }
  if (category === 'subagent-profile') return { kind: 'subagent', source_id: id }
  if (category === 'workflow') return { kind: 'workflow', source_id: id }
  if (category === 'mcp-tool') return { kind: 'mcp_tool', source_id: id }
  return { kind: 'component', type: category, source_id: id }
}
