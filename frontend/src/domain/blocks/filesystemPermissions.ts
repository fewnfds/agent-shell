import type {
  FilesystemToolApiValue,
  FilesystemToolDefault,
  FilesystemToolDraft,
} from './filesystem'
import {
  cleanName,
  editableText,
  identity,
  isRecord,
  overrideValue,
  type BlockDraftBase,
  type BlockPayloadBase,
} from './shared'

export type FilesystemPermissionValue = 'read-write' | 'read-only' | 'no-access'

export interface FilesystemPermissionEntryDraft {
  path: string
  permission: FilesystemPermissionValue
}

type FilesystemPermissionEntryApi = FilesystemPermissionEntryDraft

interface FilesystemPermissionToolOverrideDraft extends FilesystemToolDraft {
  override: boolean
}

export interface FilesystemPermissionsDraft extends BlockDraftBase {
  permissions: FilesystemPermissionEntryDraft[]
  system_prompt_override_enabled: boolean
  system_prompt_use_default: boolean
  system_prompt_value: string
  tool_overrides: Record<string, FilesystemPermissionToolOverrideDraft>
}

interface FilesystemPermissionsApiRecord extends BlockDraftBase {
  permissions: FilesystemPermissionEntryApi[]
  system_prompt_override: { value: string | null } | null
  tool_overrides: Record<string, FilesystemToolApiValue | null>
}

interface FilesystemPermissionsPayload extends BlockPayloadBase {
  permissions: FilesystemPermissionEntryApi[]
  system_prompt_override: { value: string | null } | null
  tool_overrides: Record<string, FilesystemToolApiValue>
}

export interface FilesystemPermissionsDefaults {
  system_prompt: string
  tools: FilesystemToolDefault[]
}

function filesystemPermissionToolOverrides(
  value: unknown,
  defaults: FilesystemPermissionsDefaults,
): Record<string, FilesystemPermissionToolOverrideDraft> {
  const source = isRecord(value) ? value : {}
  return Object.fromEntries(defaults.tools.map((tool) => {
    const configured = isRecord(source[tool.name]) ? source[tool.name] : null
    return [tool.name, {
      override: configured !== null,
      visible: configured && typeof configured.visible === 'boolean'
        ? configured.visible
        : tool.visible,
      description_override: configured
        ? editableText(configured.description_override, tool.default_description)
        : tool.default_description,
    }]
  }))
}

export const filesystemPermissionsAdapter = {
  blank(defaults: FilesystemPermissionsDefaults): FilesystemPermissionsDraft {
    return {
      id: '',
      name: '',
      permissions: [],
      system_prompt_override_enabled: false,
      system_prompt_use_default: true,
      system_prompt_value: defaults.system_prompt,
      tool_overrides: filesystemPermissionToolOverrides(undefined, defaults),
    }
  },
  fromApi(
    value: FilesystemPermissionsApiRecord,
    defaults: FilesystemPermissionsDefaults,
  ): FilesystemPermissionsDraft {
    const prompt = isRecord(value.system_prompt_override)
      ? value.system_prompt_override
      : null
    return {
      ...identity(value),
      permissions: Array.isArray(value.permissions)
        ? value.permissions.flatMap((entry) => isRecord(entry)
          && typeof entry.path === 'string'
          && ['read-write', 'read-only', 'no-access'].includes(String(entry.permission))
          ? [{
              path: entry.path,
              permission: entry.permission as FilesystemPermissionValue,
            }]
          : [])
        : [],
      system_prompt_override_enabled: prompt !== null,
      system_prompt_use_default: prompt?.value === null,
      system_prompt_value: typeof prompt?.value === 'string'
        ? prompt.value
        : defaults.system_prompt,
      tool_overrides: filesystemPermissionToolOverrides(value.tool_overrides, defaults),
    }
  },
  toPayload(
    value: FilesystemPermissionsDraft,
    defaults: FilesystemPermissionsDefaults,
  ): FilesystemPermissionsPayload {
    const toolDefaults = new Map(defaults.tools.map((tool) => [tool.name, tool]))
    const tool_overrides = Object.fromEntries(
      Object.entries(value.tool_overrides).flatMap(([name, override]) => {
        const fallback = toolDefaults.get(name)
        if (!fallback || !override.override) return []
        return [[name, {
          visible: fallback.configurable ? override.visible : fallback.visible,
          description_override: overrideValue(
            override.description_override,
            fallback.default_description,
          ),
        }]]
      }),
    )
    return {
      name: cleanName(value.name),
      permissions: value.permissions
        .filter((entry) => entry.path.trim())
        .map((entry) => ({
          path: entry.path.trim(),
          permission: entry.permission,
        })),
      system_prompt_override: value.system_prompt_override_enabled
        ? {
            value: value.system_prompt_use_default
              ? null
              : value.system_prompt_value,
          }
        : null,
      tool_overrides,
    }
  },
}
