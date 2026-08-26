import {
  cleanName, editableText, identity, isRecord, overrideValue, stringValue,
  type BlockDraftBase, type BlockPayloadBase,
} from './shared'

export type FilesystemBackendType = 'composite' | 'local-shell'
export type FilesystemPermissionValue = 'read-write' | 'read-only' | 'no-access'

export interface MappedDirectory {
  virtual_path: string
  local_path: string
  path_origin: 'absolute' | 'data-root-relative'
  lifecycle_mode: 'fixed' | 'dynamic'
  permission: FilesystemPermissionValue
}
export interface VirtualSource {
  virtual_path: string
  source_path: string
  permission: FilesystemPermissionValue
}
export interface FilesystemWorkspace {
  local_path: string
  path_origin: 'absolute' | 'data-root-relative'
}
export interface SkillPackageSummary { id: string; name: string }

export interface FilesystemDraft extends BlockDraftBase {
  backend_type: FilesystemBackendType
  mapped_directories: MappedDirectory[]
  virtual_directories: VirtualSource[]
  virtual_files: VirtualSource[]
  workspace: FilesystemWorkspace | null
  skill_package_id: string
  system_prompt_override: string
}
interface FilesystemApiRecord extends BlockDraftBase {
  backend_type?: FilesystemBackendType
  mapped_directories?: unknown
  virtual_directories?: unknown
  virtual_files?: unknown
  workspace?: unknown
  skill_package_id?: string | null
  system_prompt_override?: string | null
}
interface FilesystemPayload extends BlockPayloadBase {
  backend_type: FilesystemBackendType
  mapped_directories: MappedDirectory[]
  virtual_directories: VirtualSource[]
  virtual_files: VirtualSource[]
  workspace: FilesystemWorkspace | null
  skill_package_id: string | null
  system_prompt_override: string | null
}
export interface FilesystemDefaults { system_prompt: string }
export interface FilesystemImportSource extends BlockDraftBase {
  mapped_directories?: MappedDirectory[]
  virtual_directories?: VirtualSource[]
  virtual_files?: VirtualSource[]
}

function permission(value: unknown): FilesystemPermissionValue {
  return value === 'read-only' || value === 'no-access' ? value : 'read-write'
}
function mappedDirectoryRows(value: unknown): MappedDirectory[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((item) => isRecord(item) ? [{
    virtual_path: stringValue(item.virtual_path), local_path: stringValue(item.local_path),
    path_origin: item.path_origin === 'data-root-relative' ? 'data-root-relative' as const : 'absolute' as const,
    lifecycle_mode: item.lifecycle_mode === 'dynamic' ? 'dynamic' as const : 'fixed' as const,
    permission: permission(item.permission),
  }] : [])
}
function virtualRows(value: unknown): VirtualSource[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((item) => isRecord(item) ? [{
    virtual_path: stringValue(item.virtual_path), source_path: stringValue(item.source_path),
    permission: permission(item.permission),
  }] : [])
}
function workspace(value: unknown): FilesystemWorkspace | null {
  if (!isRecord(value)) return null
  return {
    local_path: stringValue(value.local_path),
    path_origin: value.path_origin === 'data-root-relative' ? 'data-root-relative' : 'absolute',
  }
}
const blankWorkspace = (): FilesystemWorkspace => ({ local_path: '', path_origin: 'absolute' })
function configuredRows<T extends { virtual_path: string }>(rows: T[], source: keyof T): T[] {
  return rows.filter((row) => Boolean(row.virtual_path.trim() || String(row[source] ?? '').trim()))
    .map((row) => ({ ...row, virtual_path: row.virtual_path.trim(), [source]: String(row[source]).trim() }))
}

export const filesystemAdapter = {
  blank(defaults: FilesystemDefaults): FilesystemDraft {
    return { id: '', name: '', backend_type: 'composite', mapped_directories: [], virtual_directories: [], virtual_files: [], workspace: null, skill_package_id: '', system_prompt_override: defaults.system_prompt }
  },
  fromApi(value: FilesystemApiRecord, defaults: FilesystemDefaults): FilesystemDraft {
    const backendType = value.backend_type === 'local-shell' ? 'local-shell' : 'composite'
    return {
      ...identity(value), backend_type: backendType,
      mapped_directories: mappedDirectoryRows(value.mapped_directories),
      virtual_directories: virtualRows(value.virtual_directories),
      virtual_files: virtualRows(value.virtual_files),
      workspace: backendType === 'local-shell' ? (workspace(value.workspace) ?? blankWorkspace()) : null,
      skill_package_id: stringValue(value.skill_package_id),
      system_prompt_override: editableText(value.system_prompt_override, defaults.system_prompt),
    }
  },
  toPayload(value: FilesystemDraft, defaults: FilesystemDefaults): FilesystemPayload {
    const composite = value.backend_type === 'composite'
    return {
      name: cleanName(value.name), backend_type: value.backend_type,
      mapped_directories: composite ? configuredRows(value.mapped_directories, 'local_path') : [],
      virtual_directories: composite ? configuredRows(value.virtual_directories, 'source_path') : [],
      virtual_files: composite ? configuredRows(value.virtual_files, 'source_path') : [],
      workspace: composite ? null : { ...(value.workspace ?? blankWorkspace()), local_path: (value.workspace?.local_path ?? '').trim() },
      skill_package_id: composite && value.skill_package_id ? value.skill_package_id : null,
      system_prompt_override: overrideValue(value.system_prompt_override, defaults.system_prompt),
    }
  },
}
