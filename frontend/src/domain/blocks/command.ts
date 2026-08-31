import type { McpReference, PythonPackageTemplate } from '@/api'

import {
  blankPythonPackage,
  pythonPackageFromApi,
  pythonPackagePayload,
  type PythonPackageDraftState,
} from './pythonPackage'
import { cleanName, identity, isRecord, type BlockDraftBase, type BlockPayloadBase } from './shared'
import { mcpReferencePayload, normalizeMcpReference } from '@/domain/mcp'

export interface CommandDraft extends BlockDraftBase, PythonPackageDraftState {
  mcp_refs: McpReference[]
}

export type CommandDefaults = Record<string, never>
export type CommandCatalogItem = PythonPackageTemplate

interface CommandPayload extends BlockPayloadBase {
  python_package: PythonPackageDraftState['python_package']
  python_package_template?: PythonPackageDraftState['python_package_template']
  mcp_refs: McpReference[]
}

export const commandAdapter = {
  blank(): CommandDraft {
    return { id: '', name: '', ...blankPythonPackage(), mcp_refs: [] }
  },
  fromApi(value: unknown): CommandDraft {
    const source = isRecord(value) ? value : {}
    return {
      ...identity(source),
      ...pythonPackageFromApi(source),
      mcp_refs: Array.isArray(source.mcp_refs) ? source.mcp_refs.map(normalizeMcpReference) : [],
    }
  },
  toPayload(value: CommandDraft): CommandPayload {
    return {
      name: cleanName(value.name),
      ...pythonPackagePayload(value),
      mcp_refs: value.mcp_refs.map(mcpReferencePayload),
    }
  },
}
