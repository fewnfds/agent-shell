import {
  cleanName, editableText, identity, isRecord, overrideValue,
  type BlockDraftBase, type BlockPayloadBase,
} from './shared'

export interface FilesystemToolDraft { visible: boolean; description_override: string }
export interface FilesystemToolApiValue { visible: boolean; description_override: string | null }
export interface FilesystemToolDefault { name: string; kind?: string; configurable: boolean; visible: boolean; default_description: string }
export interface FilesystemToolsDefaults {
  tool_token_limit_before_evict: number | null
  human_message_token_limit_before_evict?: number | null
  grep_max_count?: number
  max_execute_timeout?: number
  tools: FilesystemToolDefault[]
}
export interface FilesystemToolsDraft extends BlockDraftBase {
  tool_token_limit_before_evict: number | string | null
  human_message_token_limit_before_evict: number | string | null
  grep_max_count: number | string
  max_execute_timeout: number | string
  tool_configs: Record<string, FilesystemToolDraft>
}
interface FilesystemToolsApiRecord extends BlockDraftBase {
  tool_token_limit_before_evict?: number | null
  human_message_token_limit_before_evict?: number | null
  grep_max_count?: number
  max_execute_timeout?: number
  tool_configs?: Record<string, FilesystemToolApiValue>
}
function normalizeLimit(value: unknown, fallback: number | null): number | string | null {
  if (value === undefined) return fallback
  if (value === null) return null
  if (typeof value === 'string') return value.trim() ? value : null
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}
function configs(value: unknown, defaults: FilesystemToolsDefaults): Record<string, FilesystemToolDraft> {
  const source = isRecord(value) ? value : {}
  return Object.fromEntries(defaults.tools.map((tool) => {
    const current = isRecord(source[tool.name]) ? source[tool.name] : {}
    return [tool.name, {
      visible: tool.configurable && typeof current.visible === 'boolean' ? current.visible : tool.visible,
      description_override: editableText(current.description_override, tool.default_description),
    }]
  }))
}
export const filesystemToolsAdapter = {
  blank(defaults: FilesystemToolsDefaults): FilesystemToolsDraft {
    return { id: '', name: '', tool_token_limit_before_evict: defaults.tool_token_limit_before_evict, human_message_token_limit_before_evict: defaults.human_message_token_limit_before_evict ?? 50_000, grep_max_count: defaults.grep_max_count ?? 1_000, max_execute_timeout: defaults.max_execute_timeout ?? 3_600, tool_configs: configs(undefined, defaults) }
  },
  fromApi(value: FilesystemToolsApiRecord, defaults: FilesystemToolsDefaults): FilesystemToolsDraft {
    return { ...identity(value), tool_token_limit_before_evict: normalizeLimit(value.tool_token_limit_before_evict, defaults.tool_token_limit_before_evict), human_message_token_limit_before_evict: normalizeLimit(value.human_message_token_limit_before_evict, defaults.human_message_token_limit_before_evict ?? 50_000), grep_max_count: normalizeLimit(value.grep_max_count, defaults.grep_max_count ?? 1_000) ?? 1_000, max_execute_timeout: normalizeLimit(value.max_execute_timeout, defaults.max_execute_timeout ?? 3_600) ?? 3_600, tool_configs: configs(value.tool_configs, defaults) }
  },
  toPayload(value: FilesystemToolsDraft, defaults: FilesystemToolsDefaults): BlockPayloadBase & Record<string, unknown> {
    const byName = new Map(defaults.tools.map((tool) => [tool.name, tool]))
    return {
      name: cleanName(value.name),
      tool_token_limit_before_evict: normalizeLimit(value.tool_token_limit_before_evict, defaults.tool_token_limit_before_evict),
      human_message_token_limit_before_evict: normalizeLimit(value.human_message_token_limit_before_evict, defaults.human_message_token_limit_before_evict ?? 50_000),
      grep_max_count: normalizeLimit(value.grep_max_count, defaults.grep_max_count ?? 1_000),
      max_execute_timeout: normalizeLimit(value.max_execute_timeout, defaults.max_execute_timeout ?? 3_600),
      tool_configs: Object.fromEntries(Object.entries(value.tool_configs).flatMap(([name, config]) => {
        const fallback = byName.get(name)
        return fallback ? [[name, { visible: fallback.configurable ? config.visible : fallback.visible, description_override: overrideValue(config.description_override, fallback.default_description) }]] : []
      })),
    }
  },
}
