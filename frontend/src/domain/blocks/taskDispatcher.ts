import type { PythonPackageTemplate } from '@/api'

import {
  blankPythonPackage,
  pythonPackageFromApi,
  pythonPackagePayload,
  type PythonPackageDraftState,
} from './pythonPackage'
import { cleanName, identity, isRecord, type BlockDraftBase, type BlockPayloadBase } from './shared'

export interface TaskDispatcherDraft extends BlockDraftBase, PythonPackageDraftState {}

export type TaskDispatcherDefaults = Record<string, never>
export type TaskDispatcherCatalogItem = PythonPackageTemplate

interface TaskDispatcherPayload extends BlockPayloadBase {
  python_package: PythonPackageDraftState['python_package']
  python_package_template?: PythonPackageDraftState['python_package_template']
}

export const taskDispatcherAdapter = {
  blank(): TaskDispatcherDraft {
    return { id: '', name: '', ...blankPythonPackage() }
  },
  fromApi(value: unknown): TaskDispatcherDraft {
    const source = isRecord(value) ? value : {}
    return {
      ...identity(source),
      ...pythonPackageFromApi(source),
    }
  },
  toPayload(value: TaskDispatcherDraft): TaskDispatcherPayload {
    return {
      name: cleanName(value.name),
      ...pythonPackagePayload(value),
    }
  },
}
