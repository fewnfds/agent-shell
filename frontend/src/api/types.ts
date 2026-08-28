export type JsonPrimitive = boolean | number | string | null
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue }

export interface NamedDownload {
  blob: Blob
  filename: string
}

export type BlockType =
  | 'model-requirement'
  | 'system-prompt'
  | 'filesystem'
  | 'filesystem-tools'
  | 'todo-list'
  | 'custom-tool'
  | 'skill'
  | 'custom-middleware'
  | 'agent-event-output'
  | 'exception-retry'
  | 'subagent'
  | 'summarization'
  | 'prompt-caching'

export type WorkflowComponentType =
  | 'checkpointer'
  | 'workflow-event-output'
  | 'response-stream-scheduling'
  | 'command'
  | 'task-dispatcher'
export type ManagedComponentType = BlockType | WorkflowComponentType

export interface CapabilityManifest {
  type: BlockType
  terminology_key: string
  label: string
  order: number
  icon_key: string
  editor_key: string
  subagent_overrideable: boolean
  required: boolean
  subagent_policy: 'force-remove' | 'inherit' | 'top-level-only'
  agent_selectable: boolean
  tool_names: string[]
}

export interface WorkflowComponentManifest {
  type: WorkflowComponentType
  terminology_key: string
  label: string
  order: number
  icon_key: string
  editor_key: string
}

export interface CatalogResponse {
  block_types: CapabilityManifest[]
  workflow_component_types: WorkflowComponentManifest[]
  editor_defaults: Record<string, unknown>
}

export interface BlockPayload {
  name: string
  [key: string]: unknown
}

export type SavedBlock<TPayload extends BlockPayload = BlockPayload> = TPayload & {
  id: string
  requirements_fingerprint?: string
  dependency_status?: 'ready' | 'restart_required' | 'failed'
  dependency_error_code?: string
}

export interface ConfigurationSummary {
  id: string
  name: string
}

export type MainAgentSummary = ConfigurationSummary

export interface SubagentSummary {
  id: string
  component_name: string
  name: string
  description: string
}

export interface WorkflowSummary extends ConfigurationSummary {
  workflow_role: WorkflowRole
  description: string
  enabled: boolean
}

export interface ConfigurationCollection<T> {
  items: T[]
  total: number
  repository_id: string
  repository_revision: number
}

export interface ConfigurationOptions {
  repository_id: string
  repository_revision: number
  components: Partial<Record<ManagedComponentType, ConfigurationSummary[]>>
  main_agents: MainAgentSummary[]
  subagents: SubagentSummary[]
  workflows: WorkflowSummary[]
}

export interface ModelProviderCatalogItem {
  provider: string
  package: string
  class_name: string
  installed: boolean
  version: string | null
  documentation_url: string
}

export interface ModelProviderCatalog {
  langchain_version: string
  providers: ModelProviderCatalogItem[]
}

export interface ModelConnection {
  id: string
  name: string
  provider: string
  base_url: string
  credential: { status: 'masked' | 'missing' }
  model: string
  provider_settings: Record<string, unknown>
  tool_choice: unknown
  response_format: Record<string, unknown> | null
  model_settings: Record<string, unknown>
}

export interface ModelRequirementBinding {
  id: string
  name: string
  description: string
  binding: string | null
  connection: ModelConnection | null
}

type ManagedFileKind = 'directory' | 'file' | 'unsupported'

export interface ManagedFileCapabilities {
  list: boolean
  read: boolean
  create: boolean
  upload: boolean
  write: boolean
  download: boolean
  archive: boolean
  rename: boolean
  delete: boolean
}

export interface ManagedFileItem {
  name: string
  path: string
  kind: ManagedFileKind
  size: number | null
  modified_at: string
  revision: string
  capabilities: ManagedFileCapabilities
}

export interface ManagedDirectory {
  path: string
  capabilities: ManagedFileCapabilities
  items: ManagedFileItem[]
}

export interface ManagedTextFile {
  path: string
  content: string
  revision: string
  capabilities: ManagedFileCapabilities
}

export interface ManagedFileUploadResult {
  path: string
  kind: 'file'
  size: number
}

export interface ManagedArchivePreview {
  total_size: number
  file_count: number
  directory_count: number
}

type SystemSecretUpdate =
  | { operation: 'preserve' }
  | { operation: 'replace'; value: string }

type OptionalSecretUpdate =
  | { operation: 'keep' }
  | { operation: 'replace'; value: string }
  | { operation: 'clear' }

export interface SystemSettings {
  host: string
  port: number
  allow_remote: boolean
  langsmith_tracing_enabled: boolean
  langsmith_endpoint: string
  langsmith_project: string
  langsmith_workspace_id: string | null
  langsmith_api_key: { configured: boolean }
  management_token: { configured: boolean }
  cors_origins: string[]
  trusted_proxy_cidrs: string[]
  restart_required: boolean
  active_management_url: string
}

export interface SystemSettingsUpdate {
  host: string
  port: number
  allow_remote: boolean
  langsmith_tracing_enabled: boolean
  langsmith_endpoint: string
  langsmith_project: string
  langsmith_workspace_id: string | null
  langsmith_api_key: OptionalSecretUpdate
  management_token: SystemSecretUpdate
  cors_origins: string[]
  trusted_proxy_cidrs: string[]
}

export interface ConfigurationValidationSettings {
  debounce_ms: number
  min_debounce_ms: number
}

export interface RuntimePolicyValues {
  workflow_debug_capture_enabled: boolean
  chat_completion_body_bytes: number
  content_blocks: number
  decoded_block_bytes: number
  decoded_total_bytes: number
  media_output_bytes: number
  text_edit_bytes: number
  provider_timeout_seconds: number
  provider_connect_timeout_seconds: number
  provider_catalog_timeout_seconds: number
}

export interface RuntimePolicySettings extends RuntimePolicyValues {
  defaults: RuntimePolicyValues
  minimums: RuntimePolicyValues
  configurable: boolean
}

export type RuntimePolicyUpdate = RuntimePolicyValues

export interface SkillResource {
  name: string
  folder: string
  description: string
  template_path: string
}

export interface PrivateSkillResource {
  name: string
  folder: string
  description: string
}

export interface SkillPackageInspection {
  folder: string
  path: string
  catalog: PrivateSkillResource[]
  warnings: Record<string, LocalizedMessagePayload>
}

export interface ConfigurationRepository {
  id: string
  name: string
  schema_version: 1
  active: boolean
}

export interface ConfigurationRepositoryList {
  active_id: string
  repositories: ConfigurationRepository[]
}

export interface ConfigurationRepositoryActivation extends ConfigurationRepository {
  restart_required: boolean
  validation: ValidationReport
}

export type ConfigurationEntityKind = 'component' | 'main_agent' | 'subagent' | 'workflow'

export interface ConfigurationBundleRoot {
  kind: ConfigurationEntityKind
  source_id: string
  type?: ManagedComponentType
}

export interface ConfigurationBundleRecordPlan {
  source_id: string
  target_id: string
  kind: ConfigurationEntityKind
  type: ManagedComponentType | null
  original_name: string
  suggested_name: string
  selected_name: string
  requires_confirmation: boolean
}

export interface ConfigurationBundleFilesystemBinding {
  binding_id: string
  source_id: string
  configuration_name: string
  path: string
  kind: 'mapped-directory' | 'local-shell-workspace' | 'virtual-directory' | 'virtual-file'
  source_value: string
  source_path_origin: 'absolute' | 'data-root-relative' | null
  required: boolean
  status: 'ready' | 'target-missing' | 'binding-required'
  target_value: string | null
}

export interface ConfigurationBundleIssue {
  code: string
  message: string
  message_key?: string
  message_args?: Record<string, JsonPrimitive>
  source_id?: string
  path?: string
}

export interface ConfigurationBundlePreview {
  bundle_sha256: string
  manifest_sha256: string
  plan_token: string
  root: {
    kind: ConfigurationEntityKind
    type: ManagedComponentType | null
    source_id: string
    target_id: string
    workflow_role: WorkflowRole | null
  }
  target_ids: Record<string, string>
  records: ConfigurationBundleRecordPlan[]
  filesystem_bindings: ConfigurationBundleFilesystemBinding[]
  skill_packages: Array<{ source_id: string; target_id: string; sha256: string }>
  errors: ConfigurationBundleIssue[]
  warnings: ConfigurationBundleIssue[]
  ready: boolean
}

export interface ConfigurationBundleResolutions {
  target_ids: Record<string, string>
  names: Record<string, string>
  filesystem_bindings: Record<string, {
    value: string
    path_origin?: 'absolute' | 'data-root-relative'
  }>
}

export interface ConfigurationBundleImportResult {
  bundle_sha256: string
  root: ConfigurationBundlePreview['root']
  target_ids: Record<string, string>
  records: ConfigurationBundleRecordPlan[]
  skill_packages: Array<{ source_id: string; target_id: string; sha256: string }>
  warnings: ConfigurationBundleIssue[]
}

export interface LocalizedMessagePayload {
  message_key: string
  message_args: Record<string, JsonPrimitive>
}

export interface ResourceCatalog<TItem> {
  catalog: TItem[]
  errors: Record<string, LocalizedMessagePayload>
}

export interface CapabilityReference {
  type: string
  block_id: string
}

export interface PythonPackageReference {
  folder: string
}

export interface PythonPackageManifest {
  format_version: 1
  id: string
  family: 'workflow-node' | 'middleware' | 'event-output' | 'tool'
  adapter: 'command' | 'task-dispatcher' | 'agent-middleware' | 'agent-event-output' | 'workflow-event-output' | 'agent-tool'
  folder: string
}

export interface PythonPackageFile {
  path: string
  content: string
  exists?: boolean
  readable?: boolean
}

export interface PythonPackageTemplate {
  format_version: 1
  key: string
  family: 'workflow-node' | 'middleware' | 'event-output' | 'tool'
  adapter: 'command' | 'task-dispatcher' | 'agent-middleware' | 'agent-event-output' | 'workflow-event-output' | 'agent-tool'
  name: string
  files: PythonPackageFile[]
  revision: string
}

export interface PythonPackageFileProjection {
  path: string
  file_manager_path: string
  size: number
  modified_at: string
}

export interface PythonPackageInspection {
  repository_id: string
  owner_id: string
  revision: string
  files: PythonPackageFileProjection[]
  python_package_manifest: PythonPackageManifest | null
  python_package_error: LocalizedMessagePayload | null
  requirements_fingerprint: string
  dependency_status: 'ready' | 'restart_required' | 'failed'
  dependency_error_code: string
}

export type WorkflowRole = 'parent' | 'child'

export type ResponseQueueStrategy = 'request' | 'node_invocation'

export interface ResponseStreamPolicy {
  queue: {
    strategy: ResponseQueueStrategy
    idle_timeout_seconds: number
    max_batch_kb: number
    send_interval_seconds: number
  }
}

export interface WorkflowPayload {
  name: string
  workflow_role: WorkflowRole
  description: string
  checkpointer_id: string | null
  workflow_event_output_id: string | null
  response_stream_scheduling_id?: string | null
  cancel_on_upstream_termination: boolean
  recursion_limit: number
  execution_timeout_seconds: number
  max_concurrency: number
}

export interface Workflow extends WorkflowPayload {
  id: string
  enabled: boolean
}

export interface WorkflowLifecycleSummary {
  lifecycle_id: string
  lifecycle_status: 'active' | 'deleting'
  request_id: string
  parent_run_id: string
  parent_status: 'running' | 'completed' | 'failed' | 'cancelled'
  workflow_id: string
  workflow_name: string
  created_at: string
  messages_sha: string
  message_count: number
  task_count: number
  invalid_task_count: number
  active_task_count: number
  task_status_counts: Record<string, number>
  checkpoint_count: number
  store_item_count: number
  filesystem_count: number
  route_count: number
  dynamic_directory_count: number
  run_count: number
  active_run_count: number
  failed_run_count: number
  run_status_counts: Record<string, number>
  usage: { input_tokens: number; output_tokens: number; total_tokens: number }
  observation_status: 'available' | 'partial' | 'unavailable'
}

export type WorkflowLifecyclePage = PaginationResponse<WorkflowLifecycleSummary>

export interface WorkflowLifecycleBulkDeleteResult {
  matched: number
  deleted: number
  skipped_active: number
  deleted_checkpoint_thread_count: number
  deleted_dynamic_directories: boolean
}

export interface WorkflowRunRecord {
  run_id: string
  lifecycle_id: string
  request_id: string
  checkpoint_thread_id: string | null
  run_kind: 'workflow'
  target_id: string
  target_name: string
  parent_run_id: string | null
  launcher_id: string | null
  background_task_id: string | null
  run_depth: number
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled' | 'interrupted'
  created_at: string
  started_at: string | null
  finished_at: string | null
  finish_reason: string
  error_code: string
  usage: { input_tokens: number; output_tokens: number; total_tokens: number }
  observation_status: 'available' | 'partial'
}

export interface WorkflowRunEvent {
  sequence: number
  lifecycle_id: string
  run_id: string
  occurred_at: string
  event_type: string
  phase: 'created' | 'started' | 'completed' | 'failed' | 'cancelled'
  span_id: string | null
  parent_span_id: string | null
  subject_kind: 'run' | 'workflow_node' | 'agent' | 'model' | 'tool'
  subject_id: string | null
  subject_name: string | null
  workflow_node_id: string | null
  node_invocation_id: string | null
  status: string
  error_code: string
  usage: { input_tokens: number; output_tokens: number; total_tokens: number }
  metadata: Record<string, unknown>
}

export interface WorkflowLifecycleDetail extends WorkflowLifecycleSummary {
  runs: WorkflowRunRecord[]
  events: WorkflowRunEvent[]
  checkpoints: Record<string, Array<Record<string, unknown>>>
  artifacts: Record<string, unknown>
  diagnostics: RuntimeDiagnosticEntry[]
  next_event_sequence: number
  event_has_more: boolean
}

export interface WorkflowRunDetail extends WorkflowRunRecord {
  event_count: number
  checkpoint_count: number
  diagnostic_count: number
}

export interface WorkflowRunEventPage {
  items: WorkflowRunEvent[]
  next_after_sequence: number
  has_more: boolean
}

export type WorkflowNodeType =
  | 'start'
  | 'agent'
  | 'command'
  | 'task-dispatcher'
  | 'end'

export interface WorkflowNodeHandleSpec {
  id: string
  kind: 'control'
  edge_type: string
  accepted_edge_types?: string[]
  max_connections: number | null
}

export interface WorkflowNodeCatalogItem {
  type: WorkflowNodeType
  type_version: 1
  runtime_kind:
    | 'graph_entry'
    | 'graph_exit'
    | 'agent_wrapper'
    | 'command_node'
    | 'send_dispatcher'
  title_key: string
  description_key: string
  config_schema: Record<string, unknown>
  input_handles: WorkflowNodeHandleSpec[]
  output_handles: WorkflowNodeHandleSpec[]
  workflow_roles: WorkflowRole[]
}

export interface WorkflowGraphNode {
  id: string
  type: WorkflowNodeType
  type_version: 1
  config: {
    main_agent_id?: string
    command_id?: string
    task_dispatcher_id?: string
    defer?: boolean
  }
}

export interface WorkflowGraphEdge {
  id: string
  source: string
  source_handle: string
  target: string
  target_handle: string
  branch_key?: string | null
  dispatch_key?: string | null
}

export interface WorkflowGraphDocument {
  definition: {
    schema_version: 1
    state_contract: 'agent-shell.workflow.agent-invocations.v1'
    nodes: WorkflowGraphNode[]
    edges: WorkflowGraphEdge[]
  }
  layout: {
    nodes: Record<string, { x: number; y: number }>
    viewport: { x: number; y: number; zoom: number }
  }
}

export interface SubagentReference {
  subagent_id: string
}

export interface MiddlewareReference {
  middleware_id: string
}

export interface ToolReference {
  tool_id: string
}

export interface MainAgentPayload {
  name: string
  capability_refs: CapabilityReference[]
  tool_refs: ToolReference[]
  middleware_refs: MiddlewareReference[]
  subagents: SubagentReference[]
}

export type MainAgent = MainAgentPayload & { id: string }

export interface CapabilityOverride {
  type: string
  mode: 'disabled' | 'replace'
  block_id: string
}

export interface SubagentSettings {
  capability_overrides: CapabilityOverride[]
  tool_refs: ToolReference[]
  middleware_refs: MiddlewareReference[]
}

export interface SubagentPayload {
  component_name: string
  name: string
  description: string
  settings: SubagentSettings
}

export type Subagent = SubagentPayload & { id: string }

type ValidationTarget =
  | { kind: 'block'; type: BlockType; id?: string }
  | { kind: 'main_agent'; type?: ''; id?: string }
  | { kind: 'model_connection'; type?: ''; id?: string }
  | { kind: 'subagent'; type?: ''; id?: string }

export interface DraftValidationRequest {
  target: ValidationTarget
  payload: Record<string, unknown>
}

export interface ValidationIssue {
  code: string
  scope: string
  owner_id: string
  owner_name: string
  owner_type?: string
  path: string
  message: string
  message_key: string
  message_args: Record<string, JsonPrimitive>
  severity: 'error' | 'warning'
}

export interface ValidationReport {
  valid: boolean
  stage: string
  issues: ValidationIssue[]
}

export interface HealthResponse {
  status: string
  runtime: string
}

export interface ReadinessResponse {
  status: string
  sections: Record<string, unknown>
}

export interface ApiServerSettings {
  enabled: boolean
  status: 'running' | 'stopped'
  api_key: {
    configured: boolean
  }
  max_initial_messages: number
  message_interception_enabled: boolean
  api_base_url: string
  models_endpoint: string
  chat_completions_endpoint: string
  runtime: string
}

type ApiKeyCommand =
  | { operation: 'keep' }
  | { operation: 'clear' }
  | { operation: 'replace'; value: string }

export interface ApiServerSettingsUpdate {
  api_key: ApiKeyCommand
  max_initial_messages?: number
}

export interface InterceptedMessageRequest {
  sequence: number
  intercepted_at: string
  request_id: string
  request_raw_json: string
}

export interface MessageInterception {
  enabled: boolean
  latest: InterceptedMessageRequest | null
}

export interface PaginationResponse<TItem> {
  items: TItem[]
  page: number
  page_size: number
  total: number
  total_pages: number
}

export type EventSource = 'system' | 'runtime'
export type EventLevel = 'debug' | 'info' | 'warning' | 'error'

export interface EventFeedItem {
  id: string
  source: EventSource
  occurred_at: string
  level: EventLevel
  request_id: string
  summary: string
  inline_content: string | null
  matched_in_content: boolean
  download_kind: 'entry' | 'diagnostic_detail' | null
}

export type EventFeedResponse = PaginationResponse<EventFeedItem>

export interface EventFeedFilters {
  started_at: string
  ended_at: string
  page?: number
  page_size?: number
  source?: EventSource[]
  level?: EventLevel[]
  query?: string
}

export interface SystemLogSettings {
  max_size_mib: number
  min_size_mib: number
}

export interface RuntimeDiagnosticEntry {
  sequence: number
  diagnostic_id: string
  occurred_at: string
  severity: 'warning' | 'error'
  code: string
  summary: string
  component: string
  detail_available: boolean
  request_id?: string
  lifecycle_id?: string
  run_id?: string
  thread_id?: string
  parent_workflow_id?: string
  parent_workflow_name?: string
  subject_kind?: string
  subject_id?: string
  subject_name?: string
  workflow_node_id?: string
  node_invocation_id?: string
  exception_type?: string
}

export interface RuntimeDiagnostics {
  retention_limit: number
}

export type ManagementEvent =
  | { type: 'event_stream_connected' }
  | { type: 'settings_changed' }
  | { type: 'history_changed' }
  | { type: 'message_interception_changed' }
  | { type: 'message_intercepted'; sequence: number }
  | { type: 'runtime_diagnostic'; entry: RuntimeDiagnosticEntry }
  | { type: 'system_log'; entry: Record<string, unknown> }
  | ({ type: string } & Record<string, unknown>)
