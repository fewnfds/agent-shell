import type { PythonPackageTemplate } from '@/api'

import {
  blankPythonPackage,
  pythonPackageFromApi,
  pythonPackagePayload,
  type PythonPackageDraftState,
} from './pythonPackage'
import { cleanName, identity, isRecord, type BlockDraftBase, type BlockPayloadBase } from './shared'

export interface AgentEventOutputDraft extends BlockDraftBase, PythonPackageDraftState {}
export type AgentEventOutputCatalogItem = PythonPackageTemplate

interface AgentEventOutputPayload extends BlockPayloadBase {
  python_package: PythonPackageDraftState['python_package']
  python_package_template?: PythonPackageDraftState['python_package_template']
}

export const agentEventOutputAdapter = {
  blank(): AgentEventOutputDraft {
    return { id: '', name: '', ...blankPythonPackage() }
  },
  fromApi(value: unknown): AgentEventOutputDraft {
    const source = isRecord(value) ? value : {}
    return {
      ...identity(source),
      ...pythonPackageFromApi(source),
    }
  },
  toPayload(value: AgentEventOutputDraft): AgentEventOutputPayload {
    return {
      name: cleanName(value.name),
      ...pythonPackagePayload(value),
    }
  },
}
