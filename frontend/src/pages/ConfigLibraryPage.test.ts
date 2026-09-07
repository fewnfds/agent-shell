import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import type {
  CapabilityManifest,
  CatalogResponse,
  McpConnection,
  ModelConnection,
  SavedBlock,
  ValidationReport,
} from '@/api'
import { useConfirmation } from '@/composables/useConfirmation'
import { useToasts } from '@/composables/useToasts'
import type { ConfigLibraryApi } from '@/pages/configLibrary'

import ConfigLibraryPage from './ConfigLibraryPage.vue'

const messages = {
  navigation: {
    sections: {
      configurationRepositories: 'Component configurations',
    },
  },
  library: {
    eyebrow: 'Library',
    title: 'Configuration library',
    description: 'Saved configurations.',
    validationTitle: 'Repository validation',
    groups: {
      global: 'Global',
      components: 'Components',
      agentComponents: 'Agent components',
      workflowComponents: 'Workflow components',
      agents: 'Agents',
      workflows: 'Workflows',
      plugins: 'Plugins',
    },
    repository: {
      title: 'Configuration Repository', active: 'Active repository', newName: 'New repository name',
      create: 'Create and switch', created: 'Created', activated: 'Activated', restartRequired: 'Restart required',
    },
    bundle: {
      upload: 'Upload', download: 'Download', exportFailed: 'Export failed',
      previewTitle: 'Import Bundle', digest: 'Digest', originalName: 'Original', importName: 'Import name',
      targetId: 'Target UUID', bindings: 'Bindings', pathOrigin: 'Path origin', absolute: 'Absolute',
      selectPathOrigin: 'Select path origin', dataRootRelative: 'Data root relative', blockers: 'Blockers', warnings: 'Warnings', import: 'Import', imported: 'Imported',
      securityWarningTitle: 'Untrusted imports are dangerous', securityWarning: 'Review code and permissions.', unknownIssue: 'Issue {code}',
    },
    catalogUnavailable: 'Catalog unavailable',
    unknownCategory: 'Unknown category {type}',
    loadFailed: 'Load failed',
    empty: 'No saved configurations.',
    resultCount: '{count} configurations',
    search: {
      label: 'Search this category',
      placeholder: 'Name or UUID',
      applied: 'Applied search: {query}',
      all: 'All configurations',
      empty: 'No matches',
    },
    columns: { name: 'Name', actions: 'Actions' },
    pagination: { ariaLabel: 'Library pages' },
    detail: {
      title: 'Details for {name}',
      titleFallback: 'Configuration details',
      cardMode: 'Card',
      jsonMode: 'JSON',
    },
    copy: {
      title: 'Copy configuration',
      description: 'Copy {name} ({id})',
      nameHint: 'Enter a distinct name.',
      nameRequired: 'Enter a name.',
      submit: 'Copy',
      succeeded: 'Configuration copied',
      failed: 'Copy failed',
    },
    delete: {
      title: 'Delete configuration',
      description: 'Delete {name}?',
      succeeded: 'Configuration deleted',
      failed: 'Delete failed',
    },
    unsupportedBlock: {
      action: 'Delete retired configuration',
      title: 'Delete retired configuration?',
      description: 'Delete {type} {name}',
      succeeded: 'Retired configuration deleted',
      failed: 'Retired configuration delete failed',
    },
    deleteFiltered: {
      action: 'Delete filtered results',
      title: 'Delete filtered configurations?',
      description: 'Delete {count} configurations',
      succeeded: 'Deleted {count} configurations',
      failed: 'Bulk delete failed',
    },
  },
  common: {
    refresh: 'Refresh',
    refreshing: 'Refreshing',
    loading: 'Loading',
    retry: 'Retry',
    view: 'View',
    edit: 'Edit',
    copy: 'Copy',
    copying: 'Copying',
    delete: 'Delete',
    deleting: 'Deleting',
    search: 'Search',
    reset: 'Reset',
    cancel: 'Cancel',
    close: 'Close',
    detailSeparator: ': ',
    itemSeparator: '; ',
    previousPage: 'Previous page',
    nextPage: 'Next page',
    pagination: {
      first: 'First',
      last: 'Last',
      pageLabel: 'Page {page}',
      pageSize: 'Page size',
      pageSizeOption: '{count} items',
      jump: 'Go to page',
      jumpAction: 'Go',
      numberedSummary: '{total} items, {start}-{end}, page {page} of {totalPages}',
    },
    dataTable: {
      actions: 'Actions',
      operations: 'Operations',
    },
  },
  capabilities: {
    'model-connection': { label: 'Model connection' },
    'mcp-connection': { label: 'MCP connection' },
    filesystem: { label: 'Filesystem' },
    model: { label: 'Model' },
    'main-agent': { label: 'Main Agent' },
    'subagent-profile': { label: 'Subagent' },
    workflow: { label: 'Workflow' },
  },
  validation: {
    status: {
      unavailable: 'Unavailable',
      validating: 'Validating',
      valid: 'Valid',
      invalid: 'Invalid',
    },
    validatingDetail: 'Checking repository.',
    unavailableDetail: 'Validation unavailable.',
    issueSummary: 'Configuration problems: {count}. Expand to view the full details',
    scope: {},
  },
  fields: {
    id: 'UUID',
    name: 'Configuration name',
    unknown: 'Unknown field',
  },
  errors: {
    requestFailed: 'Request failed',
  },
}

const manifests: CapabilityManifest[] = [
  {
    type: 'model',
    terminology_key: 'model',
    label: 'ignored',
    order: 2,
    icon_key: 'bot',
    editor_key: 'model',
    subagent_overrideable: true,
    required: true,
    subagent_policy: 'inherit',
    tool_names: [],
  },
  {
    type: 'filesystem',
    terminology_key: 'file-system',
    label: 'ignored',
    order: 1,
    icon_key: 'folder',
    editor_key: 'filesystem',
    subagent_overrideable: false,
    required: true,
    subagent_policy: 'inherit',
    tool_names: [],
  },
]

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((accept) => {
    resolve = accept
  })
  return { promise, resolve }
}

function createApi() {
  const block: SavedBlock = { id: 'block-uuid', name: 'Original model' }
  const copied: SavedBlock = { id: 'copy-uuid', name: 'Copied model' }
  let stored = [block]
  const getCatalog = vi.fn(async (): Promise<CatalogResponse> => ({
    block_types: manifests,
    resource_component_types: [],
    workflow_component_types: [],
    editor_defaults: {},
  }))
  const validateRepository = vi.fn(async (): Promise<ValidationReport> => ({
    valid: true,
    stage: 'repository',
    issues: [],
  }))
  const collection = <T>(items: T[]) => ({
    items,
    total: items.length,
    repository_id: 'repository-id',
    repository_revision: 1,
  })
  const listBlockSummaries = vi.fn(async (
    _type: string,
    request?: { q?: string, offset?: number, limit?: number },
  ) => {
    const matches = stored.filter((item) => !request?.q || item.name.toLowerCase().includes(request.q.toLowerCase()))
    const offset = request?.offset ?? 0
    return collection(matches.slice(offset, request?.limit === undefined ? undefined : offset + request.limit))
  })
  const listMainAgentSummaries = vi.fn(async () => collection([]))
  const listSubagentSummaries = vi.fn(async () => collection([]))
  const listWorkflowSummaries = vi.fn(async () => collection([]))
  const modelConnection: ModelConnection = {
    id: '33333333-3333-4333-8333-333333333333',
    name: 'Local GPT',
    provider: 'openai',
    base_url: 'https://example.test/v1',
    credential: { status: 'masked' },
    model: 'gpt-local',
    provider_settings: {},
    tool_choice: null,
    response_format: null,
    model_settings: {},
  }
  const listModelConnections = vi.fn(async () => [modelConnection])
  const mcpConnection: McpConnection = {
    id: '44444444-4444-4444-8444-444444444444',
    name: 'Browser MCP',
    transport: 'stdio',
    package_source: 'npm',
    package: '@playwright/mcp',
    version: '0.0.1',
    args: [],
    env: {},
    installation: {
      status: 'not_installed',
      package_source: 'npm',
      package: '@playwright/mcp',
      version: '0.0.1',
    },
  }
  const listMcpConnections = vi.fn(async () => [mcpConnection])
  const copyBlock = vi.fn(async () => {
    stored = [...stored, copied]
    return copied
  })
  const deleteBlock = vi.fn(async (_type: string, id: string) => {
    stored = stored.filter((item) => item.id !== id)
    return { ok: true }
  })
  const deleteUnsupportedBlock = vi.fn(async () => ({ ok: true }))
  const deleteBlocks = vi.fn(async (ids: string[]) => {
    stored = stored.filter((item) => !ids.includes(item.id))
    return { deleted: ids.length }
  })
  const service: ConfigLibraryApi = {
    getCatalog,
    validateRepository,
    listBlockSummaries,
    listMainAgentSummaries,
    listSubagentSummaries,
    listWorkflowSummaries,
    listModelConnections,
    listMcpConnections,
    getBlock: vi.fn(async (_type, id) => stored.find((item) => item.id === id) ?? block),
    getMainAgent: vi.fn(async () => ({ id: 'main-id', name: 'Main Agent' } as never)),
    getSubagent: vi.fn(async () => ({ id: 'subagent-id', component_name: 'Subagent' } as never)),
    getWorkflow: vi.fn(async () => ({ id: 'workflow-id', name: 'Workflow' } as never)),
    getModelConnection: vi.fn(async () => modelConnection),
    getMcpConnection: vi.fn(async () => mcpConnection),
    copyBlock,
    copyMainAgent: vi.fn(),
    copySubagent: vi.fn(),
    copyWorkflow: vi.fn(),
    copyModelConnection: vi.fn(),
    copyMcpConnection: vi.fn(),
    deleteBlock,
    deleteUnsupportedBlock,
    deleteBlocks: vi.fn(async (_type, ids) => deleteBlocks(ids)),
    deleteBlocksMatching: vi.fn(async (_type, query) => {
      const ids = stored.filter((item) => item.name.toLowerCase().includes(query.toLowerCase())).map((item) => item.id)
      return deleteBlocks(ids)
    }),
    deleteMainAgent: vi.fn(),
    deleteSubagent: vi.fn(),
    deleteWorkflow: vi.fn(),
    deleteModelConnection: vi.fn(),
    deleteMcpConnection: vi.fn(),
    deleteMainAgents: vi.fn(),
    deleteMainAgentsMatching: vi.fn(),
    deleteSubagents: vi.fn(),
    deleteSubagentsMatching: vi.fn(),
    deleteWorkflows: vi.fn(),
    deleteWorkflowsMatching: vi.fn(),
    exportConfigurationBundle: vi.fn(async () => ({
      blob: new Blob(),
      filename: 'configuration.agent-shell-config.zip',
    })),
    previewConfigurationBundle: vi.fn(),
    importConfigurationBundle: vi.fn(),
  }
  return {
    service,
    block,
    getCatalog,
    validateRepository,
    listBlockSummaries,
    listMainAgentSummaries,
    listSubagentSummaries,
    copyBlock,
    deleteBlock,
    deleteUnsupportedBlock,
    deleteBlocks,
  }
}

async function mountPage(service: ConfigLibraryApi, path = '/library/model') {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/library/:type', component: ConfigLibraryPage }],
  })
  await router.push(path)
  await router.isReady()
  const i18n = createI18n({
    legacy: false,
    locale: 'en',
    messages: { en: messages },
  })
  const wrapper = mount(ConfigLibraryPage, {
    props: { api: service },
    global: {
      plugins: [router, i18n],
    },
  })
  await flushPromises()
  return { wrapper, router }
}

function buttonByText(wrapper: ReturnType<typeof mount>, text: string) {
  const button = wrapper.findAll('button').find((item) => item.text() === text)
  if (!button) throw new Error(`Button not found: ${text}`)
  return button
}

afterEach(() => {
  useConfirmation().cancel()
  const toasts = useToasts()
  for (const item of toasts.items.value) toasts.dismiss(item.id)
})

describe('ConfigLibraryPage', () => {
  it('lists Workflows with the common copy, download, and delete actions', async () => {
    const api = createApi()
    const workflow = {
      id: 'workflow-uuid', name: 'Workflow',
      description: '', workflow_event_output_id: null,
      durability: 'async' as const, on_disconnect: 'cancel' as const,
      enabled: false,
    }
    vi.mocked(api.service.listWorkflowSummaries).mockResolvedValue({
      items: [workflow], total: 1, repository_id: 'repository-id', repository_revision: 1,
    })
    const { wrapper } = await mountPage(api.service, '/library/workflow')

    expect(api.service.listWorkflowSummaries).toHaveBeenCalledWith({
      q: undefined, offset: 0, limit: 20,
    })
    expect(wrapper.text()).toContain('Workflow')
    expect(wrapper.findAll('button').some((button) => button.text() === 'Copy')).toBe(true)
    expect(wrapper.findAll('button').some((button) => button.text() === 'Delete')).toBe(true)
    expect(wrapper.findAll('button').some((button) => button.text() === 'Download')).toBe(true)
  })

  it('keeps the shared Bundle actions on instance Model Connections', async () => {
    const api = createApi()
    const { wrapper } = await mountPage(api.service, '/library/model-connection')

    expect(api.service.listModelConnections).toHaveBeenCalledOnce()
    expect(api.service.validateRepository).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain('Local GPT')
    expect(wrapper.findAll('button').some((button) => button.text() === 'View')).toBe(true)
    expect(wrapper.findAll('button').some((button) => button.text() === 'Edit')).toBe(true)
    expect(wrapper.findAll('button').some((button) => button.text() === 'Copy')).toBe(true)
    expect(wrapper.findAll('button').some((button) => button.text() === 'Delete')).toBe(true)
    expect(wrapper.findAll('button').some((button) => button.text() === 'Download')).toBe(false)
    expect(wrapper.findAll('button').some((button) => button.text() === 'Upload')).toBe(true)
    expect(wrapper.find('[data-testid="repository-switcher"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="library-validation-region"]').exists()).toBe(true)
    expect(wrapper.get('[data-testid="library-global-group"] > span').text()).toBe('Global')
  })

  it('lists instance MCP Connections without offering Bundle download', async () => {
    const api = createApi()
    const { wrapper } = await mountPage(api.service, '/library/mcp-connection')

    expect(api.service.listMcpConnections).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain('Browser MCP')
    expect(wrapper.findAll('button').some((button) => button.text() === 'Download')).toBe(false)
  })

  it('commits the same uploaded Bundle digest and target UUID plan', async () => {
    const api = createApi()
    const file = new File(['bundle'], 'model.zip', { type: 'application/zip' })
    vi.mocked(api.service.previewConfigurationBundle).mockResolvedValue({
      bundle_sha256: 'a'.repeat(64), manifest_sha256: 'b'.repeat(64),
      plan_token: 'c'.repeat(64),
      root: { kind: 'component', type: 'model', source_id: 'source-id', target_id: 'target-id' },
      target_ids: { 'source-id': 'target-id' },
      records: [{ source_id: 'source-id', target_id: 'target-id', kind: 'component', type: 'model', original_name: 'Model', suggested_name: 'Model', selected_name: 'Model', requires_confirmation: false }],
      filesystem_bindings: [], skill_packages: [], errors: [], warnings: [], ready: true,
    })
    vi.mocked(api.service.importConfigurationBundle).mockResolvedValue({
      bundle_sha256: 'a'.repeat(64),
      root: { kind: 'component', type: 'model', source_id: 'source-id', target_id: 'target-id' },
      target_ids: { 'source-id': 'target-id' }, records: [], skill_packages: [], warnings: [],
    })
    const { wrapper } = await mountPage(api.service)
    const input = wrapper.get('input[type="file"]')
    Object.defineProperty(input.element, 'files', { configurable: true, value: [file] })
    await input.trigger('change')
    await flushPromises()
    await buttonByText(wrapper, 'Import').trigger('click')
    await flushPromises()

    expect(api.service.importConfigurationBundle).toHaveBeenCalledWith(file, 'a'.repeat(64), 'c'.repeat(64), {
      target_ids: { 'source-id': 'target-id' }, names: { 'source-id': 'Model' }, filesystem_bindings: {},
    })
  })

  it('requires an explicit name for a conflict and enables import after the user renames it', async () => {
    const api = createApi()
    const file = new File(['bundle'], 'duplicate.zip', { type: 'application/zip' })
    vi.mocked(api.service.previewConfigurationBundle).mockResolvedValue({
      bundle_sha256: 'a'.repeat(64), manifest_sha256: 'b'.repeat(64),
      plan_token: 'c'.repeat(64),
      root: { kind: 'component', type: 'model', source_id: 'source-id', target_id: 'target-id' },
      target_ids: { 'source-id': 'target-id' },
      records: [{
        source_id: 'source-id', target_id: 'target-id', kind: 'component', type: 'model',
        original_name: 'Existing model', suggested_name: 'Existing model (imported)',
        selected_name: 'Existing model (imported)', requires_confirmation: true,
      }],
      filesystem_bindings: [], skill_packages: [], errors: [], warnings: [], ready: false,
    })
    vi.mocked(api.service.importConfigurationBundle).mockResolvedValue({
      bundle_sha256: 'a'.repeat(64),
      root: { kind: 'component', type: 'model', source_id: 'source-id', target_id: 'target-id' },
      target_ids: { 'source-id': 'target-id' }, records: [], skill_packages: [], warnings: [],
    })
    const { wrapper, router } = await mountPage(api.service)
    const input = wrapper.get('input[type="file"]')
    Object.defineProperty(input.element, 'files', { configurable: true, value: [file] })
    await input.trigger('change')
    await flushPromises()

    const nameInput = wrapper.get('table input')
    const importButton = buttonByText(wrapper, 'Import')
    expect((nameInput.element as HTMLInputElement).value).toBe('')
    expect(nameInput.attributes('placeholder')).toBe('Existing model (imported)')
    expect(importButton.attributes('disabled')).toBeDefined()

    await nameInput.setValue('Imported model copy')
    expect(importButton.attributes('disabled')).toBeUndefined()
    await importButton.trigger('click')
    await flushPromises()

    expect(api.service.importConfigurationBundle).toHaveBeenCalledWith(
      file,
      'a'.repeat(64),
      'c'.repeat(64),
      expect.objectContaining({ names: { 'source-id': 'Imported model copy' } }),
    )
    expect(router.currentRoute.value.fullPath).toBe('/library/model')
  })

  it.each(['mapped-directory', 'local-shell-workspace'] as const)('keeps Bundle import disabled until a %s resolution is ready', async (bindingKind) => {
    const api = createApi()
    const file = new File(['bundle'], 'filesystem.zip', { type: 'application/zip' })
    const bindingPath = bindingKind === 'mapped-directory'
      ? 'mapped_directories[0].local_path'
      : 'workspace.local_path'
    vi.mocked(api.service.previewConfigurationBundle).mockResolvedValue({
      bundle_sha256: 'a'.repeat(64), manifest_sha256: 'b'.repeat(64),
      plan_token: 'c'.repeat(64),
      root: { kind: 'component', type: 'filesystem', source_id: 'source-id', target_id: 'target-id' },
      target_ids: { 'source-id': 'target-id' },
      records: [{ source_id: 'source-id', target_id: 'target-id', kind: 'component', type: 'filesystem', original_name: 'Files', suggested_name: 'Files', selected_name: 'Files', requires_confirmation: false }],
      filesystem_bindings: [{
        binding_id: `source-id:${bindingPath}`, source_id: 'source-id',
        configuration_name: 'Files', path: bindingPath, kind: bindingKind,
        source_value: 'C:/source', source_path_origin: 'absolute', required: true,
        status: 'binding-required', target_value: null,
      }],
      skill_packages: [],
      errors: [{
        code: 'filesystem_binding_required', message: 'Select a target path.',
        message_key: 'configurationBundle.issues.filesystem_binding_required', message_args: {},
        source_id: 'source-id', path: bindingPath,
      }],
      warnings: [], ready: false,
    })
    const { wrapper } = await mountPage(api.service)
    const input = wrapper.get('input[type="file"]')
    Object.defineProperty(input.element, 'files', { configurable: true, value: [file] })
    await input.trigger('change')
    await flushPromises()
    const importButton = buttonByText(wrapper, 'Import')

    expect(importButton.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('Blockers')
    await wrapper.get('[data-testid="bundle-binding-value"]').setValue('D:/target')
    expect(importButton.attributes('disabled')).toBeDefined()
    await wrapper.get('[data-testid="bundle-path-origin"]').setValue('absolute')
    expect(importButton.attributes('disabled')).toBeUndefined()
    expect(wrapper.text()).not.toContain('Blockers')
    await wrapper.get('table input').setValue('')
    expect(importButton.attributes('disabled')).toBeDefined()
    await importButton.trigger('click')
    expect(api.service.importConfigurationBundle).not.toHaveBeenCalled()
  })

  it('keeps Bundle import disabled when the preview reports blockers', async () => {
    const api = createApi()
    const file = new File(['bundle'], 'blocked.zip', { type: 'application/zip' })
    vi.mocked(api.service.previewConfigurationBundle).mockResolvedValue({
      bundle_sha256: 'a'.repeat(64), manifest_sha256: 'b'.repeat(64),
      plan_token: 'c'.repeat(64),
      root: { kind: 'component', type: 'filesystem', source_id: 'source-id', target_id: 'target-id' },
      target_ids: { 'source-id': 'target-id' }, records: [], filesystem_bindings: [], skill_packages: [],
      errors: [{ code: 'blocked', message: 'Blocked' }], warnings: [], ready: false,
    })
    const { wrapper } = await mountPage(api.service)
    const input = wrapper.get('input[type="file"]')
    Object.defineProperty(input.element, 'files', { configurable: true, value: [file] })
    await input.trigger('change')
    await flushPromises()

    expect(buttonByText(wrapper, 'Import').attributes('disabled')).toBeDefined()
  })

  it('keeps list and copy failures in their local error regions without toasts', async () => {
    const listFailure = createApi()
    listFailure.listBlockSummaries.mockRejectedValueOnce(new Error('offline'))
    const { wrapper: listWrapper } = await mountPage(listFailure.service)

    expect(listWrapper.get('[data-testid="data-table-error"]').attributes('role')).toBe('alert')
    expect(useToasts().items.value).toHaveLength(0)
    listWrapper.unmount()

    const copyFailure = createApi()
    copyFailure.copyBlock.mockRejectedValueOnce(new Error('copy failed'))
    const { wrapper: copyWrapper } = await mountPage(copyFailure.service)
    await buttonByText(copyWrapper, 'Copy').trigger('click')
    await copyWrapper.get('#library-copy-form input').setValue('Copied model')
    await copyWrapper.get('#library-copy-form').trigger('submit')
    await flushPromises()

    expect(copyWrapper.get('[data-testid="copy-error"]').attributes('role')).toBe('alert')
    expect(useToasts().items.value).toHaveLength(0)
    copyWrapper.unmount()
  })

  it('uses catalog order and loads only the route category', async () => {
    const api = createApi()
    const { wrapper } = await mountPage(api.service)

    expect(api.listBlockSummaries).toHaveBeenCalledWith('model', {
      q: undefined, offset: 0, limit: 20,
    })
    expect(wrapper.get('[data-testid="library-component-group"] > span').text()).toBe('Agent components')
    expect(wrapper
      .get('[data-testid="library-component-group"] [data-testid="section-nav"]')
      .findAll('button')
      .map((item) => item.text())).toEqual(['Filesystem', 'Model'])
    expect(wrapper.get('[data-testid="library-agent-group"] > span').text()).toBe('Agents')
    expect(wrapper
      .get('[data-testid="library-agent-group"] [data-testid="section-nav"]')
      .findAll('button')
      .map((item) => item.text())).toEqual(['Main Agent', 'Subagent'])
    expect(wrapper.get('[data-testid="data-table-row"]').text()).not.toContain('block-uuid')
  })

  it('keeps the latest repository validation when an earlier request finishes late', async () => {
    const staleValidation = deferred<ValidationReport>()
    const latestValidation = deferred<ValidationReport>()
    const api = createApi()
    api.validateRepository
      .mockImplementationOnce(() => staleValidation.promise)
      .mockImplementationOnce(() => latestValidation.promise)
    const { wrapper } = await mountPage(api.service)

    await buttonByText(wrapper, 'Refresh').trigger('click')
    latestValidation.resolve({ valid: true, stage: 'repository_load', issues: [] })
    await flushPromises()
    staleValidation.resolve({
      valid: false,
      stage: 'repository_load',
      issues: [{
        code: 'stale.validation',
        scope: 'repository',
        owner_id: '',
        owner_name: '',
        path: 'repository',
        message: 'stale result',
        message_key: 'errors.requestFailed',
        message_args: {},
      }],
    })
    await flushPromises()

    expect(wrapper.get('[data-testid="validation-checklist"]').attributes('data-status')).toBe('valid')
    expect(wrapper.find('[data-testid="validation-issue"]').exists()).toBe(false)
  })

  it('hides internal IDs in ordinary views while actions still use the selected UUID', async () => {
    const api = createApi()
    const { wrapper, router } = await mountPage(api.service)

    await buttonByText(wrapper, 'View').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-testid="config-detail-list"]').text()).not.toContain('block-uuid')
    await wrapper.get('[data-testid="detail-json-mode"]').setValue(true)
    await flushPromises()
    expect(wrapper.get('[data-testid="config-detail-json"]').text()).toContain('block-uuid')
    await buttonByText(wrapper, 'Close').trigger('click')

    await buttonByText(wrapper, 'Copy').trigger('click')
    await flushPromises()
    await wrapper.get('#library-copy-form input').setValue('Copied model')
    await wrapper.get('#library-copy-form').trigger('submit')
    await flushPromises()
    expect(api.copyBlock).toHaveBeenCalledWith('model', 'block-uuid', 'Copied model')

    await buttonByText(wrapper, 'Delete').trigger('click')
    expect(useConfirmation().current.value?.description).toContain('Original model')
    expect(useConfirmation().current.value?.description).not.toContain('block-uuid')
    useConfirmation().accept()
    await flushPromises()
    expect(api.deleteBlock).toHaveBeenCalledWith('model', 'block-uuid')

    await buttonByText(wrapper, 'Edit').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/agent-components/model')
    expect(router.currentRoute.value.query.id).toBe('copy-uuid')
  })

  it('deletes only the submitted search results through one category batch command', async () => {
    const api = createApi()
    api.listBlockSummaries.mockResolvedValueOnce({
      items: [api.block, { id: 'other-uuid', name: 'Other model' }],
      total: 2,
      repository_id: 'repository-id',
      repository_revision: 1,
    })
    const { wrapper } = await mountPage(api.service)

    await wrapper.get('#configuration-library-query').setValue('Original')
    const bulk = buttonByText(wrapper, 'Delete filtered results')
    expect(bulk.attributes('disabled')).toBeDefined()
    await wrapper.get('form[role="search"]').trigger('submit')
    await flushPromises()
    expect(wrapper.findAll('[data-testid="data-table-row"]')).toHaveLength(1)

    await bulk.trigger('click')
    useConfirmation().accept()
    await flushPromises()
    expect(api.service.deleteBlocksMatching).toHaveBeenCalledWith('model', 'Original')
  })
})
