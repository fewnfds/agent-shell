import type { PythonPackageTemplate } from '@/api'

import {
  blankPythonPackage,
  pythonPackageFromApi,
  pythonPackagePayload,
  type PythonPackageDraftState,
} from './pythonPackage'
import { cleanName, identity, isRecord, type BlockDraftBase, type BlockPayloadBase } from './shared'

export interface WorkflowEventOutputDraft extends BlockDraftBase, PythonPackageDraftState {}
export type WorkflowEventOutputCatalogItem = PythonPackageTemplate

interface WorkflowEventOutputPayload extends BlockPayloadBase {
  python_package: PythonPackageDraftState['python_package']
  python_package_template?: PythonPackageDraftState['python_package_template']
}

export const workflowEventOutputAdapter = {
  blank(): WorkflowEventOutputDraft {
    return { id: '', name: '', ...blankPythonPackage() }
  },
  fromApi(value: unknown): WorkflowEventOutputDraft {
    const source = isRecord(value) ? value : {}
    return {
      ...identity(source),
      ...pythonPackageFromApi(source),
    }
  },
  toPayload(value: WorkflowEventOutputDraft): WorkflowEventOutputPayload {
    return {
      name: cleanName(value.name),
      ...pythonPackagePayload(value),
    }
  },
}
