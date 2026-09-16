import type { InjectionKey } from 'vue'
import { managementApi } from '@/api'
import type {
  ConfigurationCollection,
  DraftValidationRequest,
  ExternalAgent,
  ExternalAgentConversation,
  ExternalAgentEffort,
  ExternalAgentOutputFormat,
  ExternalAgentPayload,
  ExternalAgentProvider,
  ExternalAgentSummary,
  ExternalAgentTool,
  ExternalAgentToolPermission,
  ValidationReport,
} from '@/api'

/** Providers the management console can author. Only Antigravity CLI ships today. */
export const DEFAULT_EXTERNAL_AGENT_PROVIDER: ExternalAgentProvider = 'antigravity-cli'
export const externalAgentProviders: ExternalAgentProvider[] = [
  DEFAULT_EXTERNAL_AGENT_PROVIDER,
]

export const externalAgentEfforts: ExternalAgentEffort[] = ['low', 'medium', 'high']
export const externalAgentConversations: ExternalAgentConversation[] = [
  'new',
  'continue-latest',
]
export const externalAgentOutputFormats: ExternalAgentOutputFormat[] = [
  'text',
  'json',
  'stream-json',
]
export const externalAgentToolPermissions: ExternalAgentToolPermission[] = [
  'request-review',
  'proceed-in-sandbox',
  'always-proceed',
  'strict',
]
export const externalAgentTools: ExternalAgentTool[] = [
  'view_file',
  'run_command',
  'manage_task',
  'send_message',
  'schedule',
  'invoke_subagent',
  'define_subagent',
  'manage_subagents',
  'write_to_file',
  'replace_file_content',
  'generate_image',
  'read_url_content',
  'search_web',
  'find_by_name',
  'grep_search',
  'list_dir',
  'ask_question',
]

export const DEFAULT_EXTERNAL_AGENT_PRINT_TIMEOUT = '5m'

export interface ExternalAgentAuthoringService {
  listExternalAgents(): Promise<ConfigurationCollection<ExternalAgentSummary>>
  getExternalAgent(id: string): Promise<ExternalAgent>
  createExternalAgent(payload: ExternalAgentPayload): Promise<ExternalAgent>
  updateExternalAgent(id: string, payload: ExternalAgentPayload): Promise<ExternalAgent>
  copyExternalAgent(id: string, name: string): Promise<ExternalAgent>
  deleteExternalAgent(id: string): Promise<{ ok: boolean }>
  validateDraft(request: DraftValidationRequest): Promise<ValidationReport>
}

export const externalAgentAuthoringServiceKey: InjectionKey<ExternalAgentAuthoringService> = Symbol(
  'external-agent-authoring-service',
)

export const managementExternalAgentService: ExternalAgentAuthoringService = {
  listExternalAgents: () => managementApi.listExternalAgentSummaries(),
  getExternalAgent: (id) => managementApi.getExternalAgent(id),
  createExternalAgent: (payload) => managementApi.createExternalAgent(payload),
  updateExternalAgent: (id, payload) => managementApi.updateExternalAgent(id, payload),
  copyExternalAgent: (id, name) => managementApi.copyExternalAgent(id, name),
  deleteExternalAgent: (id) => managementApi.deleteExternalAgent(id),
  validateDraft: (request) => managementApi.validateDraft(request),
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null
    ? value as Record<string, unknown>
    : {}
}

function provider(value: unknown): ExternalAgentProvider {
  const candidate = text(value)
  return externalAgentProviders.includes(candidate as ExternalAgentProvider)
    ? candidate as ExternalAgentProvider
    : DEFAULT_EXTERNAL_AGENT_PROVIDER
}

function effort(value: unknown): ExternalAgentEffort | null {
  const candidate = text(value)
  return externalAgentEfforts.includes(candidate as ExternalAgentEffort)
    ? candidate as ExternalAgentEffort
    : null
}

function conversation(value: unknown): ExternalAgentConversation {
  const candidate = text(value)
  return externalAgentConversations.includes(
    candidate as ExternalAgentConversation,
  )
    ? candidate as ExternalAgentConversation
    : 'new'
}

function outputFormat(value: unknown): ExternalAgentOutputFormat {
  const candidate = text(value)
  return externalAgentOutputFormats.includes(candidate as ExternalAgentOutputFormat)
    ? candidate as ExternalAgentOutputFormat
    : 'stream-json'
}

function toolPermission(value: unknown): ExternalAgentToolPermission {
  const candidate = text(value)
  return externalAgentToolPermissions.includes(candidate as ExternalAgentToolPermission)
    ? candidate as ExternalAgentToolPermission
    : 'request-review'
}

function textList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string')
    : []
}

function toolList(value: unknown): ExternalAgentTool[] {
  return textList(value).filter(
    (item): item is ExternalAgentTool => externalAgentTools.includes(item as ExternalAgentTool),
  )
}

function envRecord(value: unknown): Record<string, string> {
  const source = record(value)
  return Object.fromEntries(
    Object.entries(source).filter((entry): entry is [string, string] => typeof entry[1] === 'string'),
  )
}

export function blankExternalAgent(): ExternalAgent {
  return {
    id: '',
    name: '',
    description: '',
    provider: DEFAULT_EXTERNAL_AGENT_PROVIDER,
    agent_name: '',
    system_prompt: '',
    model: null,
    effort: null,
    print_timeout: DEFAULT_EXTERNAL_AGENT_PRINT_TIMEOUT,
    output_format: 'stream-json',
    conversation: 'new',
    exclude_default_components: true,
    tools: [],
    tool_guidance: '',
    tool_permission: 'request-review',
    permission_allow: [],
    env: {},
  }
}

export function normalizeExternalAgent(value: unknown): ExternalAgent {
  const source = record(value)
  const model = text(source.model)
  return {
    id: text(source.id),
    name: text(source.name),
    description: text(source.description),
    provider: provider(source.provider),
    agent_name: text(source.agent_name),
    system_prompt: text(source.system_prompt),
    model: model || null,
    effort: effort(source.effort),
    print_timeout: text(source.print_timeout) || DEFAULT_EXTERNAL_AGENT_PRINT_TIMEOUT,
    output_format: outputFormat(source.output_format),
    conversation: conversation(source.conversation),
    exclude_default_components: source.exclude_default_components !== false,
    tools: toolList(source.tools),
    tool_guidance: text(source.tool_guidance),
    tool_permission: toolPermission(source.tool_permission),
    permission_allow: textList(source.permission_allow),
    env: envRecord(source.env),
  }
}

export function externalAgentPayload(resource: ExternalAgent): ExternalAgentPayload {
  const model = resource.model?.trim() ?? ''
  return {
    name: resource.name.trim(),
    description: resource.description.trim(),
    provider: resource.provider,
    agent_name: resource.agent_name.trim(),
    system_prompt: resource.system_prompt,
    model: model || null,
    effort: resource.effort,
    print_timeout: resource.print_timeout.trim(),
    output_format: resource.output_format,
    conversation: resource.conversation,
    exclude_default_components: resource.exclude_default_components,
    tools: [...resource.tools],
    tool_guidance: resource.tool_guidance,
    tool_permission: resource.tool_permission,
    permission_allow: [...resource.permission_allow],
    env: { ...resource.env },
  }
}
