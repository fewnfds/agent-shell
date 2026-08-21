import type {
  ManagedComponentType,
  CatalogResponse,
  ConfigurationBundleImportResult,
  ConfigurationBundlePreview,
  ConfigurationBundleResolutions,
  ConfigurationBundleRoot,
  ConfigurationRepository,
  ConfigurationRepositoryActivation,
  ConfigurationRepositoryList,
  MainAgent,
  NamedDownload,
  SavedBlock,
  Subagent,
  ValidationReport,
  Workflow,
  WorkflowRole,
} from '@/api'

export type LibraryCategoryId = ManagedComponentType | 'main-agent' | 'subagent-profile' | 'parent-workflow' | 'child-workflow'
export type LibraryItem = SavedBlock | MainAgent | Subagent | Workflow

export interface ConfigLibraryApi {
  getCatalog(): Promise<CatalogResponse>
  validateRepository(): Promise<ValidationReport>
  listBlocks(type: ManagedComponentType): Promise<SavedBlock[]>
  listMainAgents(): Promise<MainAgent[]>
  listSubagents(): Promise<Subagent[]>
  listWorkflows(role?: WorkflowRole): Promise<Workflow[]>
  copyBlock(type: ManagedComponentType, id: string, name: string): Promise<SavedBlock>
  copyMainAgent(id: string, name: string): Promise<MainAgent>
  copySubagent(id: string, componentName: string): Promise<Subagent>
  deleteBlock(type: ManagedComponentType, id: string): Promise<{ ok: boolean }>
  deleteUnsupportedBlock(id: string): Promise<{ ok: boolean }>
  deleteMainAgent(id: string): Promise<{ ok: boolean }>
  deleteSubagent(id: string): Promise<{ ok: boolean }>
  deleteWorkflow(id: string): Promise<{ ok: boolean }>
  deleteBlocks(type: ManagedComponentType, ids: string[]): Promise<{ deleted: number }>
  deleteMainAgents(ids: string[]): Promise<{ deleted: number }>
  deleteSubagents(ids: string[]): Promise<{ deleted: number }>
  deleteWorkflows(ids: string[]): Promise<{ deleted: number }>
  listConfigurationRepositories(): Promise<ConfigurationRepositoryList>
  createConfigurationRepository(name: string): Promise<ConfigurationRepository>
  activateConfigurationRepository(id: string): Promise<ConfigurationRepositoryActivation>
  exportConfigurationBundle(root: ConfigurationBundleRoot): Promise<NamedDownload>
  previewConfigurationBundle(bundle: File): Promise<ConfigurationBundlePreview>
  importConfigurationBundle(bundle: File, digest: string, planToken: string, resolutions: ConfigurationBundleResolutions): Promise<ConfigurationBundleImportResult>
}

export const agentLibraryCategories = [
  'main-agent',
  'subagent-profile',
] as const

export const workflowLibraryCategories = ['parent-workflow', 'child-workflow'] as const

export function routeCategory(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

export function editLocation(category: LibraryCategoryId, id: string): {
  path: string
  query: { id: string }
} {
  if (category === 'main-agent') return { path: '/agents/main', query: { id } }
  if (category === 'subagent-profile') return { path: '/agents/subagents', query: { id } }
  if (category === 'parent-workflow') return { path: '/workflows/parents', query: { id } }
  if (category === 'child-workflow') return { path: '/workflows/children', query: { id } }
  if (
    category === 'workflow-event-output'
    || category === 'command'
    || category === 'task-dispatcher'
  ) {
    return { path: `/workflow-components/${category}`, query: { id } }
  }
  return { path: `/agent-components/${category}`, query: { id } }
}

export function bundleRoot(category: LibraryCategoryId, id: string): ConfigurationBundleRoot {
  if (category === 'main-agent') return { kind: 'main_agent', source_id: id }
  if (category === 'subagent-profile') return { kind: 'subagent', source_id: id }
  if (category === 'parent-workflow' || category === 'child-workflow') return { kind: 'workflow', source_id: id }
  return { kind: 'component', type: category, source_id: id }
}
