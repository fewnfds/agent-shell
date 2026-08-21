import type { PythonPackageTemplate } from '@/api'

import {
  blankPythonPackage,
  pythonPackageFromApi,
  pythonPackagePayload,
  type PythonPackageDraftState,
} from './pythonPackage'
import { cleanName, identity, isRecord, type BlockDraftBase, type BlockPayloadBase } from './shared'

export interface CommandDraft extends BlockDraftBase, PythonPackageDraftState {}

export type CommandDefaults = Record<string, never>
export type CommandCatalogItem = PythonPackageTemplate

interface CommandPayload extends BlockPayloadBase {
  python_package: PythonPackageDraftState['python_package']
  python_package_template?: PythonPackageDraftState['python_package_template']
}

export const commandAdapter = {
  blank(): CommandDraft {
    return { id: '', name: '', ...blankPythonPackage() }
  },
  fromApi(value: unknown): CommandDraft {
    const source = isRecord(value) ? value : {}
    return {
      ...identity(source),
      ...pythonPackageFromApi(source),
    }
  },
  toPayload(value: CommandDraft): CommandPayload {
    return {
      name: cleanName(value.name),
      ...pythonPackagePayload(value),
    }
  },
}
