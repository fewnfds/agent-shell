import {
  cleanName,
  editableText,
  identity,
  isRecord,
  overrideValue,
  stringValue,
  type BlockDraftBase,
  type BlockPayloadBase,
} from './shared'

export interface MappedDirectory {
  virtual_path: string
  local_path: string
  path_origin: 'absolute' | 'data-root-relative'
  lifecycle_mode: 'fixed' | 'dynamic'
}

export interface VirtualSource {
  virtual_path: string
  source_path: string
}

export interface FilesystemToolDraft {
  visible: boolean
  description_override: string
}

export interface FilesystemToolApiValue {
  visible: boolean
  description_override: string | null
}

export interface FilesystemDraft extends BlockDraftBase {
  mapped_directories: MappedDirectory[]
  virtual_directories: VirtualSource[]
  virtual_files: VirtualSource[]
  system_prompt_override: string
  tool_token_limit_before_evict: number | string | null
  human_message_token_limit_before_evict: number | string | null
  grep_max_count: number | string
  max_execute_timeout: number | string
  tool_configs: Record<string, FilesystemToolDraft>
}

interface FilesystemApiRecord extends BlockDraftBase {
  mapped_directories: MappedDirectory[]
  virtual_directories: VirtualSource[]
  virtual_files: VirtualSource[]
  system_prompt_override: string | null
  tool_token_limit_before_evict: number | null
  human_message_token_limit_before_evict?: number | null
  grep_max_count?: number
  max_execute_timeout?: number
  tool_configs: Record<string, FilesystemToolApiValue>
}

interface FilesystemPayload extends BlockPayloadBase {
  mapped_directories: MappedDirectory[]
  virtual_directories: VirtualSource[]
  virtual_files: VirtualSource[]
  system_prompt_override: string | null
  tool_token_limit_before_evict: number | string | null
  human_message_token_limit_before_evict: number | string | null
  grep_max_count: number | string
  max_execute_timeout: number | string
  tool_configs: Record<string, FilesystemToolApiValue>
}

export interface FilesystemToolDefault {
  name: string
  kind?: string
  configurable: boolean
  visible: boolean
  default_description: string
}

export interface FilesystemDefaults {
  system_prompt: string
  tool_token_limit_before_evict: number | null
  human_message_token_limit_before_evict?: number | null
  grep_max_count?: number
  max_execute_timeout?: number
  tools: FilesystemToolDefault[]
}

export interface FilesystemImportSource extends BlockDraftBase {
  mapped_directories?: MappedDirectory[]
  virtual_directories?: VirtualSource[]
  virtual_files?: VirtualSource[]
}

function filesystemToolDraft(
  source: unknown,
  fallback: FilesystemToolDefault,
): FilesystemToolDraft {
  const current = isRecord(source) ? source : {}
  return {
    visible: fallback.configurable && typeof current.visible === 'boolean'
      ? current.visible
      : fallback.visible,
    description_override: editableText(
      current.description_override,
      fallback.default_description,
    ),
  }
}

function filesystemToolConfigs(
  source: unknown,
  defaults: FilesystemDefaults,
): Record<string, FilesystemToolDraft> {
  const current = isRecord(source) ? source : {}
  return Object.fromEntries(defaults.tools.map((tool) => [
    tool.name,
    filesystemToolDraft(current[tool.name], tool),
  ]))
}

function mappingRows<T>(
  value: unknown,
  keys: readonly (keyof T)[],
): T[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((item) => {
    if (!isRecord(item) || !keys.some((key) => typeof item[String(key)] === 'string')) {
      return []
    }
    return [Object.fromEntries(
      keys.map((key) => [key, stringValue(item[String(key)])]),
    ) as T]
  })
}

function mappedDirectoryRows(value: unknown): MappedDirectory[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((item) => {
    if (!isRecord(item) || (
      typeof item.virtual_path !== 'string'
      && typeof item.local_path !== 'string'
    )) return []
    return [{
      virtual_path: stringValue(item.virtual_path),
      local_path: stringValue(item.local_path),
      path_origin: item.path_origin === 'data-root-relative'
        ? 'data-root-relative'
        : 'absolute',
      lifecycle_mode: item.lifecycle_mode === 'dynamic' ? 'dynamic' : 'fixed',
    }]
  })
}

function normalizeTokenLimit(value: unknown, fallback: number | null): number | string | null {
  if (value === undefined) return fallback
  if (value === null) return null
  if (typeof value === 'string') {
    if (!value.trim()) return null
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : value
  }
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function nonBlankMapping<T extends { virtual_path: string }>(item: T, sourceKey: keyof T): boolean {
  return Boolean(item.virtual_path.trim() || String(item[sourceKey] ?? '').trim())
}

export const filesystemAdapter = {
  blank(defaults: FilesystemDefaults): FilesystemDraft {
    return {
      id: '', name: '', mapped_directories: [], virtual_directories: [], virtual_files: [],
      system_prompt_override: defaults.system_prompt,
      tool_token_limit_before_evict: defaults.tool_token_limit_before_evict,
      human_message_token_limit_before_evict: defaults.human_message_token_limit_before_evict ?? 50_000,
      grep_max_count: defaults.grep_max_count ?? 1_000,
      max_execute_timeout: defaults.max_execute_timeout ?? 3_600,
      tool_configs: filesystemToolConfigs(undefined, defaults),
    }
  },
  fromApi(value: FilesystemApiRecord, defaults: FilesystemDefaults): FilesystemDraft {
    return {
      ...identity(value),
      mapped_directories: mappedDirectoryRows(value.mapped_directories),
      virtual_directories: mappingRows<VirtualSource>(
        value.virtual_directories,
        ['virtual_path', 'source_path'],
      ),
      virtual_files: mappingRows<VirtualSource>(
        value.virtual_files,
        ['virtual_path', 'source_path'],
      ),
      system_prompt_override: editableText(value.system_prompt_override, defaults.system_prompt),
      tool_token_limit_before_evict: normalizeTokenLimit(
        value.tool_token_limit_before_evict,
        defaults.tool_token_limit_before_evict,
      ),
      human_message_token_limit_before_evict: normalizeTokenLimit(
        value.human_message_token_limit_before_evict,
        defaults.human_message_token_limit_before_evict ?? 50_000,
      ),
      grep_max_count: normalizeTokenLimit(value.grep_max_count, defaults.grep_max_count ?? 1_000) ?? 1_000,
      max_execute_timeout: normalizeTokenLimit(value.max_execute_timeout, defaults.max_execute_timeout ?? 3_600) ?? 3_600,
      tool_configs: filesystemToolConfigs(value.tool_configs, defaults),
    }
  },
  toPayload(value: FilesystemDraft, defaults: FilesystemDefaults): FilesystemPayload {
    const toolDefaults = new Map(defaults.tools.map((tool) => [tool.name, tool]))
    const tool_configs = Object.fromEntries(Object.entries(value.tool_configs).flatMap(([name, config]) => {
      const fallback = toolDefaults.get(name)
      if (!fallback) return []
      return [[name, {
        visible: fallback.configurable ? config.visible : fallback.visible,
        description_override: overrideValue(config.description_override, fallback.default_description),
      }]]
    }))
    return {
      name: cleanName(value.name),
      mapped_directories: value.mapped_directories
        .filter((item) => nonBlankMapping(item, 'local_path'))
        .map((item) => ({
          virtual_path: item.virtual_path.trim(),
          local_path: item.local_path.trim(),
          path_origin: item.path_origin,
          lifecycle_mode: item.lifecycle_mode,
        })),
      virtual_directories: value.virtual_directories
        .filter((item) => nonBlankMapping(item, 'source_path'))
        .map((item) => ({ virtual_path: item.virtual_path.trim(), source_path: item.source_path.trim() })),
      virtual_files: value.virtual_files
        .filter((item) => nonBlankMapping(item, 'source_path'))
        .map((item) => ({ virtual_path: item.virtual_path.trim(), source_path: item.source_path.trim() })),
      system_prompt_override: overrideValue(value.system_prompt_override, defaults.system_prompt),
      tool_token_limit_before_evict: normalizeTokenLimit(
        value.tool_token_limit_before_evict,
        defaults.tool_token_limit_before_evict,
      ),
      human_message_token_limit_before_evict: normalizeTokenLimit(
        value.human_message_token_limit_before_evict,
        defaults.human_message_token_limit_before_evict ?? 50_000,
      ),
      grep_max_count: normalizeTokenLimit(value.grep_max_count, defaults.grep_max_count ?? 1_000) ?? 1_000,
      max_execute_timeout: normalizeTokenLimit(value.max_execute_timeout, defaults.max_execute_timeout ?? 3_600) ?? 3_600,
      tool_configs,
    }
  },
}
