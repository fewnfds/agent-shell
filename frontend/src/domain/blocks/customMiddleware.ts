import type { PythonPackageTemplate } from '@/api'

import {
  blankPythonPackage,
  pythonPackageFromApi,
  pythonPackagePayload,
  type PythonPackageDraftState,
} from './pythonPackage'
import { cleanName, identity, isRecord, type BlockDraftBase, type BlockPayloadBase } from './shared'

export interface CustomMiddlewareDraft extends BlockDraftBase, PythonPackageDraftState {}
export type CustomMiddlewareCatalogItem = PythonPackageTemplate

interface CustomMiddlewarePayload extends BlockPayloadBase {
  python_package: PythonPackageDraftState['python_package']
  python_package_template?: PythonPackageDraftState['python_package_template']
}

export const customMiddlewareAdapter = {
  blank(): CustomMiddlewareDraft {
    return { id: '', name: '', ...blankPythonPackage() }
  },
  fromApi(value: unknown): CustomMiddlewareDraft {
    const source = isRecord(value) ? value : {}
    return {
      ...identity(source),
      ...pythonPackageFromApi(source),
    }
  },
  toPayload(value: CustomMiddlewareDraft): CustomMiddlewarePayload {
    return {
      name: cleanName(value.name),
      ...pythonPackagePayload(value),
    }
  },
}
