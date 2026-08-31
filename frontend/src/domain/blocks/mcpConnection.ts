import type {
  BlockPayload,
  McpConfiguredValue,
  McpConnection,
  McpInstallation,
} from '@/api'

import {
  cleanName,
  identity,
  isRecord,
  stringValue,
  type BlockDraftBase,
} from './shared'

export interface McpConfiguredValueDraft {
  name: string
  source: 'literal' | 'secret'
  value: string
  status: 'masked' | 'missing'
}

interface McpConnectionDraftBase extends BlockDraftBase {
  transport: 'stdio' | 'http'
}

export interface McpStdioConnectionDraft extends McpConnectionDraftBase {
  transport: 'stdio'
  package_source: 'npm' | 'pypi'
  package: string
  version: string
  entrypoint: string
  args: string[]
  cwd: string
  values: McpConfiguredValueDraft[]
  installation: McpInstallation
}

export interface McpHttpConnectionDraft extends McpConnectionDraftBase {
  transport: 'http'
  url: string
  values: McpConfiguredValueDraft[]
}

export type McpConnectionDraft = McpStdioConnectionDraft | McpHttpConnectionDraft

function configuredValues(value: unknown): McpConfiguredValueDraft[] {
  if (!isRecord(value)) return []
  return Object.entries(value).map(([name, raw]) => {
    const configured = isRecord(raw) ? raw : {}
    const source = configured.source === 'literal' ? 'literal' : 'secret'
    return {
      name,
      source,
      value: stringValue(configured.value),
      status: configured.status === 'masked' ? 'masked' : 'missing',
    }
  })
}

function valuesPayload(values: McpConfiguredValueDraft[]): Record<string, McpConfiguredValue> {
  return Object.fromEntries(values.map((item) => [
    item.name.trim(),
    item.source === 'literal'
      ? { source: 'literal' as const, value: item.value }
      : item.value
        ? { source: 'secret' as const, value: item.value }
        : { source: 'secret' as const, status: item.status },
  ]))
}

export const mcpConnectionAdapter = {
  blank(): McpConnectionDraft {
    return {
      id: '',
      name: '',
      transport: 'stdio',
      package_source: 'npm',
      package: '',
      version: '',
      entrypoint: '',
      args: [],
      cwd: '',
      values: [],
      installation: {
        status: 'not_installed',
        package_source: 'npm',
        package: '',
        version: '',
        entrypoint: null,
      },
    }
  },
  fromApi(value: McpConnection): McpConnectionDraft {
    const base = identity(value)
    if (value.transport === 'http') {
      return {
        ...base,
        transport: 'http',
        url: value.url,
        values: configuredValues(value.headers),
      }
    }
    return {
      ...base,
      transport: 'stdio',
      package_source: value.package_source,
      package: value.package,
      version: value.version,
      entrypoint: stringValue(value.entrypoint),
      args: [...value.args],
      cwd: stringValue(value.cwd),
      values: configuredValues(value.env),
      installation: value.installation,
    }
  },
  toPayload(value: McpConnectionDraft): BlockPayload {
    const common = { name: cleanName(value.name), transport: value.transport }
    if (value.transport === 'http') {
      return {
        ...common,
        transport: 'http',
        url: value.url.trim(),
        headers: valuesPayload(value.values),
      }
    }
    return {
      ...common,
      transport: 'stdio',
      package_source: value.package_source,
      package: value.package.trim(),
      version: value.version.trim(),
      ...(value.entrypoint.trim() ? { entrypoint: value.entrypoint.trim() } : {}),
      args: value.args,
      ...(value.cwd.trim() ? { cwd: value.cwd.trim() } : {}),
      env: valuesPayload(value.values),
    }
  },
}
