import type {
  PythonPackageInspection,
  PythonPackageReference,
  PythonPackageTemplate,
} from '@/api'

import { isRecord, stringValue } from './shared'

export interface PythonPackageTemplateSelection {
  key: string
  revision: string
}

export interface PythonPackageDraftState {
  python_package: PythonPackageReference
  python_package_template: PythonPackageTemplateSelection
  python_package_inspection: PythonPackageInspection | null
}

export interface PythonPackagePayload {
  python_package: PythonPackageReference
  python_package_template?: PythonPackageTemplateSelection
}

export function blankPythonPackage(): PythonPackageDraftState {
  return {
    python_package: { folder: '' },
    python_package_template: { key: '', revision: '' },
    python_package_inspection: null,
  }
}

export function pythonPackageFromApi(source: Record<string, unknown>): PythonPackageDraftState {
  const reference = isRecord(source.python_package) ? source.python_package : {}
  return {
    python_package: { folder: stringValue(reference.folder) },
    python_package_template: { key: '', revision: '' },
    python_package_inspection: null,
  }
}

export function applyPythonPackageTemplate(
  target: PythonPackageDraftState,
  template: PythonPackageTemplate | undefined,
): void {
  target.python_package = { folder: '' }
  target.python_package_template = {
    key: template?.key ?? '',
    revision: template?.revision ?? '',
  }
  target.python_package_inspection = null
}

export function applyPythonPackageInspection(
  target: PythonPackageDraftState,
  inspection: PythonPackageInspection,
): void {
  target.python_package_inspection = inspection
}

export function pythonPackagePayload(value: PythonPackageDraftState): PythonPackagePayload {
  const python_package = { folder: value.python_package.folder }
  if (python_package.folder) return { python_package }
  return {
    python_package,
    python_package_template: {
      key: value.python_package_template.key,
      revision: value.python_package_template.revision,
    },
  }
}
