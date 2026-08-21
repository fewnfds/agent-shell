import type { PythonPackageTemplate } from '@/api'

import {
  blankPythonPackage,
  pythonPackageFromApi,
  pythonPackagePayload,
  type PythonPackageDraftState,
} from './pythonPackage'
import { cleanName, identity, isRecord, type BlockDraftBase, type BlockPayloadBase } from './shared'

export interface CustomToolDraft extends BlockDraftBase, PythonPackageDraftState {}
export type CustomToolCatalogItem = PythonPackageTemplate

interface CustomToolPayload extends BlockPayloadBase {
  python_package: PythonPackageDraftState['python_package']
  python_package_template?: PythonPackageDraftState['python_package_template']
}

export const customToolAdapter = {
  blank(): CustomToolDraft {
    return { id: '', name: '', ...blankPythonPackage() }
  },
  fromApi(value: unknown): CustomToolDraft {
    const source = isRecord(value) ? value : {}
    return {
      ...identity(source),
      ...pythonPackageFromApi(source),
    }
  },
  toPayload(value: CustomToolDraft): CustomToolPayload {
    return {
      name: cleanName(value.name),
      ...pythonPackagePayload(value),
    }
  },
}
