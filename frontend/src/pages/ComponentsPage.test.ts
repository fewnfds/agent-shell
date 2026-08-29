import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  ManagementApiError,
  type BlockPayload,
  type BlockType,
  type CapabilityManifest,
  type SavedBlock,
  type SkillPackageInspection,
  type WorkflowComponentManifest,
} from '@/api'
import { useConfirmation } from '@/composables/useConfirmation'

import ComponentsPage from './ComponentsPage.vue'

const api = vi.hoisted(() => ({
  getCatalog: vi.fn(),
  listBlockSummaries: vi.fn(),
  getBlock: vi.fn(),
  saveBlock: vi.fn(),
  copyBlock: vi.fn(),
  deleteBlock: vi.fn(),
  listModelProviders: vi.fn(),
  listModelConnections: vi.fn(),
  getModelConnection: vi.fn(),
  saveModelConnection: vi.fn(),
  copyModelConnection: vi.fn(),
  deleteModelConnection: vi.fn(),
  fetchModels: vi.fn(),
  validateDraft: vi.fn(),
  validateRepository: vi.fn(),
  listCustomToolTemplates: vi.fn(),
  listMiddlewareTemplates: vi.fn(),
  listAgentEventOutputTemplates: vi.fn(),
  listWorkflowEventOutputTemplates: vi.fn(),
  listCommandTemplates: vi.fn(),
  listSkills: vi.fn(),
  inspectPythonPackage: vi.fn(),
  inspectPrivateSkills: vi.fn(),
  addPrivateSkill: vi.fn(),
  deletePrivateSkill: vi.fn(),
}))

const toastNotify = vi.hoisted(() => vi.fn())

vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return { ...actual, managementApi: api }
})

vi.mock('@/composables/useToasts', () => ({
  useToasts: () => ({ notify: toastNotify }),
}))

vi.mock('vue-i18n', async (importOriginal) => {
  const actual = await importOriginal<typeof import('vue-i18n')>()
  return {
    ...actual,
    useI18n: () => ({
      locale: { value: 'en' },
      t: (key: string) => key,
      te: () => true,
    }),
  }
})

const modelManifest: CapabilityManifest = {
  type: 'model-requirement',
  terminology_key: 'model-requirement',
  label: 'Model requirement manifest label',
  order: 1,
  icon_key: 'bot',
  editor_key: 'model_requirement',
  subagent_overrideable: true,
  required: true,
  subagent_policy: 'inherit',
  tool_names: [],
}

const skillManifest: CapabilityManifest = {
  ...modelManifest,
  type: 'skill',
  terminology_key: 'skill',
  label: 'Skill manifest label',
  order: 2,
  editor_key: 'skill',
  required: false,
}

const commandManifest: WorkflowComponentManifest = {
  type: 'command',
  terminology_key: 'command',
  label: 'Condition router',
  order: 1,
  icon_key: 'workflow',
  editor_key: 'command',
}

const responseStreamSchedulingManifest: WorkflowComponentManifest = {
  ...commandManifest,
  type: 'response-stream-scheduling',
  terminology_key: 'response-stream-scheduling',
  label: 'Response Stream Scheduling',
  editor_key: 'response_stream_scheduling',
}

const responseStreamSchedulingDefaults = {
  queue: {
    strategy: 'request' as const,
    idle_timeout_seconds: 2,
    max_batch_kb: 64,
    send_interval_seconds: 0.05,
  },
}

const commandTemplate = {
  key: 'basic-router',
  format_version: 1 as const,
  family: 'workflow-node' as const,
  adapter: 'command' as const,
  name: 'Basic router',
  revision: 'template-revision',
  files: [{
    path: 'main.py', content: 'def create_command():\n    return route\n', exists: true,
  }],
}

function modelRequirementRecord(id: string): SavedBlock {
  return {
    id,
    name: 'Shared name',
    description: 'A local model with reasoning capability.',
  }
}

function skillRecord(id: string): SavedBlock {
  return {
    id,
    name: 'Skill configuration',
    skill_package: { folder: id },
    skill_package_contents: { folder: id, path: `skills/${id}`, catalog: [], warnings: {} },
    instruction_override: null,
  }
}

function modelConnection(id: string, name = 'Local model') {
  return {
    id,
    name,
    provider: 'openai',
    base_url: 'https://api.openai.com/v1',
    credential: { status: 'masked' as const },
    model: 'gpt-5-mini',
    provider_settings: {},
    tool_choice: null,
    response_format: null,
    model_settings: {},
  }
}

function privateSkillInspection(ownerId: string, skillName: string): SkillPackageInspection {
  return {
    folder: ownerId,
    path: `skills/${ownerId}`,
    catalog: [{
      name: skillName,
      folder: skillName.toLowerCase(),
      description: `${skillName} description`,
    }],
    warnings: {},
  }
}

function pythonPackageInspection(ownerId: string) {
  return {
    repository_id: '00000000-0000-4000-8000-000000000098',
    owner_id: ownerId,
    revision: 'package-revision',
    files: [],
    python_package_manifest: null,
    python_package_error: null,
    requirements_fingerprint: '',
    dependency_status: 'ready' as const,
    dependency_error_code: '',
  }
}

async function mountAt(path: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/agent-components/:type', component: ComponentsPage }],
  })
  await router.push(path)
  await router.isReady()
  const wrapper = mount(ComponentsPage, { global: { plugins: [router] } })
  await settleComponentPage(wrapper)
  return { router, wrapper }
}

async function settleComponentPage(wrapper: ReturnType<typeof mount>): Promise<void> {
  await vi.waitFor(() => {
    expect(
      wrapper.find('[data-testid="component-layout"]').exists()
      || wrapper.find('[data-testid="page-error"]').exists(),
    ).toBe(true)
  })
  await flushPromises()
}

function buttonByText(wrapper: Awaited<ReturnType<typeof mountAt>>['wrapper'], text: string) {
  const button = wrapper.findAll('button').find((item) => item.text() === text)
  if (!button) throw new Error(`Button not found: ${text}`)
  return button
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((accept) => {
    resolve = accept
  })
  return { promise, resolve }
}

function summaryCollection(items: SavedBlock[]) {
  return {
    items,
    total: items.length,
    repository_id: '00000000-0000-4000-8000-000000000098',
    repository_revision: 1,
  }
}

beforeEach(() => {
  useConfirmation().cancel()
  vi.clearAllMocks()
  api.getCatalog.mockResolvedValue({
    block_types: [skillManifest, modelManifest],
    workflow_component_types: [],
    editor_defaults: {
      skill: { system_prompt: 'default skill prompt', required_placeholders: [] },
    },
  })
  api.listBlockSummaries.mockImplementation(async (type: BlockType) => summaryCollection(
    type === 'model-requirement'
      ? [modelRequirementRecord('00000000-0000-0000-0000-000000000001')]
      : [skillRecord('00000000-0000-0000-0000-000000000002')],
  ))
  api.getBlock.mockImplementation(async (type: BlockType, id: string) => (
    type === 'model-requirement' ? modelRequirementRecord(id) : skillRecord(id)
  ))
  api.saveBlock.mockImplementation(async (type: BlockType, data: BlockPayload & { id?: string }) => ({
    ...(type === 'model-requirement'
      ? modelRequirementRecord(data.id ?? '00000000-0000-0000-0000-000000000099')
      : skillRecord(data.id ?? '00000000-0000-0000-0000-000000000099')),
    ...data,
    id: data.id ?? '00000000-0000-0000-0000-000000000099',
  }))
  api.copyBlock.mockImplementation(async (_type: BlockType, _id: string, name: string) => ({
    ...modelRequirementRecord('00000000-0000-4000-8000-000000000088'),
    name,
  }))
  api.deleteBlock.mockResolvedValue({ ok: true })
  api.listModelProviders.mockResolvedValue({ providers: [] })
  api.listModelConnections.mockResolvedValue([])
  api.getModelConnection.mockRejectedValue(new Error('unexpected model connection load'))
  api.saveModelConnection.mockRejectedValue(new Error('unexpected model connection save'))
  api.copyModelConnection.mockRejectedValue(new Error('unexpected model connection copy'))
  api.deleteModelConnection.mockResolvedValue({ ok: true })
  api.fetchModels.mockResolvedValue([])
  api.validateDraft.mockResolvedValue({ valid: true, stage: 'draft_validation', issues: [] })
  api.validateRepository.mockResolvedValue({ valid: true, stage: 'repository_load', issues: [] })
  api.listCustomToolTemplates.mockResolvedValue({ catalog: [], errors: {} })
  api.listMiddlewareTemplates.mockResolvedValue({ catalog: [], errors: {} })
  api.listAgentEventOutputTemplates.mockResolvedValue({ catalog: [], errors: {} })
  api.listWorkflowEventOutputTemplates.mockResolvedValue({ catalog: [], errors: {} })
  api.listCommandTemplates.mockResolvedValue({ catalog: [], errors: {} })
  api.listSkills.mockResolvedValue({
    catalog: [{ name: 'research', folder: 'research', template_path: 'group/research', description: 'Research skill' }],
    errors: {},
  })
  api.inspectPythonPackage.mockImplementation(async (_type: BlockType, id: string) => (
    pythonPackageInspection(id)
  ))
  api.inspectPrivateSkills.mockImplementation(async (id: string) => ({
    folder: id, path: `skills/${id}`, catalog: [], warnings: {},
  }))
})

describe('ComponentsPage', () => {
  it('uses the Workflow Components section navigation without a duplicate type navigation', async () => {
    api.getCatalog.mockResolvedValueOnce({
      block_types: [skillManifest, modelManifest],
      workflow_component_types: [commandManifest],
      editor_defaults: { command: {} },
    })
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{
        path: '/workflow-components/:type',
        component: ComponentsPage,
        props: { scope: 'workflow' },
      }],
    })
    await router.push('/workflow-components/command')
    await router.isReady()
    const wrapper = mount(ComponentsPage, {
      props: { scope: 'workflow' },
      global: { plugins: [router] },
    })
    await settleComponentPage(wrapper)

    expect(api.listCommandTemplates).toHaveBeenCalledOnce()

    expect(wrapper.findAll('[data-testid="section-nav"] button').map((item) => item.text())).toEqual([
      'navigation.sections.checkpointer',
      'navigation.sections.workflowEventOutput',
      'navigation.sections.responseStreamScheduling',
      'navigation.sections.command',
    ])
    expect(wrapper.get('.page-action-dock').findAll('button').map((button) => button.text())).toEqual([
      'common.copy',
      'common.delete',
      'common.new',
      'common.save',
    ])
    wrapper.unmount()
  })

  it('creates Response Stream Scheduling through the shared Workflow Component CRUD', async () => {
    api.getCatalog.mockResolvedValueOnce({
      block_types: [],
      workflow_component_types: [responseStreamSchedulingManifest],
      editor_defaults: {
        response_stream_scheduling: responseStreamSchedulingDefaults,
      },
    })
    api.listBlockSummaries.mockResolvedValueOnce(summaryCollection([]))
    api.saveBlock.mockResolvedValueOnce({
      id: 'response-scheduling-id',
      name: 'Fair stream',
      queue: {
        strategy: 'node_invocation',
        idle_timeout_seconds: 1.5,
        max_batch_kb: 32,
        send_interval_seconds: 0.1,
      },
    })
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{
        path: '/workflow-components/:type',
        component: ComponentsPage,
        props: { scope: 'workflow' },
      }],
    })
    await router.push('/workflow-components/response-stream-scheduling')
    await router.isReady()
    const wrapper = mount(ComponentsPage, {
      props: { scope: 'workflow' },
      global: { plugins: [router] },
    })
    await settleComponentPage(wrapper)

    expect(wrapper.find('[data-editor="response-stream-scheduling"]').exists()).toBe(true)
    await wrapper.get('[data-field="record-name"]').setValue('Fair stream')
    await wrapper.get('#response-queue-strategy').setValue('node_invocation')
    await wrapper.get('#response-idle-timeout').setValue('1.5')
    await wrapper.get('#response-max-batch').setValue('32')
    await wrapper.get('#response-send-interval').setValue('0.1')
    await buttonByText(wrapper, 'common.save').trigger('click')
    await flushPromises()

    expect(api.saveBlock).toHaveBeenCalledWith(
      'response-stream-scheduling',
      {
        name: 'Fair stream',
        queue: {
          strategy: 'node_invocation',
          idle_timeout_seconds: 1.5,
          max_batch_kb: 32,
          send_interval_seconds: 0.1,
        },
      },
    )
    wrapper.unmount()
  })

  it('resolves each base component route from the first scoped catalog manifest', async () => {
    api.getCatalog.mockResolvedValue({
      block_types: [skillManifest],
      workflow_component_types: [commandManifest],
      editor_defaults: {
        skill: { system_prompt: 'default skill prompt', required_placeholders: [] },
      },
    })
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/agent-components', component: ComponentsPage },
        { path: '/agent-components/:type', component: ComponentsPage },
        {
          path: '/workflow-components',
          component: ComponentsPage,
          props: { scope: 'workflow' },
        },
        {
          path: '/workflow-components/:type',
          component: ComponentsPage,
          props: { scope: 'workflow' },
        },
      ],
    })
    await router.push('/agent-components')
    await router.isReady()
    const wrapper = mount({ template: '<RouterView />' }, { global: { plugins: [router] } })
    await flushPromises()

    expect(router.currentRoute.value.path).toBe('/agent-components/skill')
    expect(api.listBlockSummaries).toHaveBeenLastCalledWith('skill')

    await router.push('/workflow-components')
    await flushPromises()

    await vi.waitFor(() => {
      expect(router.currentRoute.value.path).toBe('/workflow-components/command')
      expect(wrapper.find('[data-editor="command"]').exists()).toBe(true)
    })
    expect(api.listBlockSummaries).toHaveBeenLastCalledWith('command')
    expect(wrapper.find('[data-editor="command"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('uses catalog order and loads only the routed type and explicit UUID', async () => {
    const id = '00000000-0000-0000-0000-000000000001'
    const { wrapper } = await mountAt(`/agent-components/model-requirement?id=${id}`)

    const navLabels = wrapper.findAll('[data-testid="section-nav"] button').map((item) => item.text())
    expect(navLabels).toEqual(['capabilities.model-requirement.label', 'capabilities.skill.label'])
    expect(wrapper.find('.app-content-header').exists()).toBe(false)
    expect(wrapper.find('[data-testid="editor-region"] > h2').exists()).toBe(false)
    expect(wrapper.get('.page-action-dock').findAll('button').map((button) => button.text())).toEqual([
      'common.copy',
      'common.delete',
      'common.new',
      'common.save',
    ])
    expect(api.listBlockSummaries).toHaveBeenCalledTimes(1)
    expect(api.listBlockSummaries).toHaveBeenCalledWith('model-requirement')
    expect(api.getBlock).toHaveBeenCalledWith('model-requirement', id)
    expect(wrapper.find('[data-editor="model-requirement"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="navigation-region"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="config-editor-layout"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="editor-region"]').find('[data-testid="validation-checklist"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="inspector-region"]').find('[data-testid="validation-checklist"]').exists()).toBe(true)
    expect(wrapper.get('[data-testid="component-layout"]').classes()).toContain('configuration-loading-surface')
    expect(wrapper.get('[data-testid="component-layout"]').attributes('data-loading')).toBe('false')
    expect(wrapper.text()).not.toContain('common.loading')
    expect(wrapper.text()).not.toContain(id)
    expect(api.listSkills).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('refreshes stored validation before reading a collection with a new Repository revision', async () => {
    const modelId = '00000000-0000-4000-8000-000000000001'
    const skillId = '00000000-0000-4000-8000-000000000002'
    api.listBlockSummaries.mockImplementation(async (type: BlockType) => ({
      ...summaryCollection(type === 'model-requirement'
        ? [modelRequirementRecord(modelId)]
        : [skillRecord(skillId)]),
      repository_revision: type === 'model-requirement' ? 1 : 2,
    }))
    api.validateRepository
      .mockResolvedValueOnce({ valid: true, stage: 'repository_load', issues: [] })
      .mockResolvedValueOnce({
        valid: false,
        stage: 'repository_load',
        issues: [{
          code: 'storage.skill_package_owner_mismatch',
          scope: 'block',
          owner_id: skillId,
          owner_name: 'Skill configuration',
          owner_type: 'skill',
          path: 'skill_package.folder',
          message: 'Stored Skill package owner mismatch.',
          message_key: 'validation.issue.storage.skillPackageOwnerMismatch',
          message_args: {},
        }],
      })
    const { router, wrapper } = await mountAt(`/agent-components/model-requirement?id=${modelId}`)

    await router.push(`/agent-components/skill?id=${skillId}`)
    await vi.waitFor(() => {
      expect(api.validateRepository).toHaveBeenCalledTimes(2)
      expect(wrapper.find('[data-testid="stored-invalid-warning"]').exists()).toBe(true)
    })
    wrapper.unmount()
  })

  it('revalidates independently edited Python package assets on explicit refresh', async () => {
    const id = '00000000-0000-4000-8000-000000000081'
    const command = {
      id,
      name: 'Editable command',
      python_package: { folder: id },
    }
    api.getCatalog.mockResolvedValueOnce({
      block_types: [],
      workflow_component_types: [commandManifest],
      editor_defaults: { command: {} },
    })
    api.listBlockSummaries.mockResolvedValueOnce(summaryCollection([command]))
    api.getBlock.mockResolvedValueOnce(command)
    api.validateRepository
      .mockResolvedValueOnce({ valid: true, stage: 'repository_load', issues: [] })
      .mockResolvedValueOnce({
        valid: false,
        stage: 'repository_load',
        issues: [{
          code: 'python_package.invalid',
          scope: 'block',
          owner_id: id,
          owner_name: command.name,
          owner_type: 'command',
          path: 'python_package.folder',
          message: 'The referenced Python package is invalid.',
          message_key: 'validation.issue.pythonPackage.invalid',
          message_args: { package_id: id },
        }],
      })
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{
        path: '/workflow-components/:type',
        component: ComponentsPage,
        props: { scope: 'workflow' },
      }],
    })
    await router.push(`/workflow-components/command?id=${id}`)
    await router.isReady()
    const wrapper = mount(ComponentsPage, {
      props: { scope: 'workflow' },
      global: { plugins: [router] },
    })
    await settleComponentPage(wrapper)

    const refresh = wrapper.findAll('[data-editor="command"] button')
      .find((button) => button.attributes('aria-label') === 'common.refresh')
    if (!refresh) throw new Error('Python package refresh button not found')
    await refresh.trigger('click')
    await vi.waitFor(() => {
      expect(api.validateRepository).toHaveBeenCalledTimes(2)
      expect(wrapper.find('[data-testid="stored-invalid-warning"]').exists()).toBe(true)
    })
    wrapper.unmount()
  })

  it('uses the same component editor framework for model connections', async () => {
    const id = '00000000-0000-4000-8000-000000000077'
    const connection = modelConnection(id)
    api.listModelConnections.mockResolvedValueOnce([connection])
    api.getModelConnection.mockResolvedValueOnce(connection)
    api.listModelProviders.mockResolvedValueOnce({
      langchain_version: '1.0.0',
      providers: [{
        provider: 'openai', package: 'langchain-openai', class_name: 'ChatOpenAI',
        installed: true, version: '1.0.0', documentation_url: 'https://example.invalid',
      }],
    })
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{
        path: '/models/connections',
        component: ComponentsPage,
        props: { scope: 'model' },
      }],
    })
    await router.push(`/models/connections?id=${id}`)
    await router.isReady()
    const wrapper = mount(ComponentsPage, {
      props: { scope: 'model' },
      global: { plugins: [router] },
    })
    await settleComponentPage(wrapper)

    expect(api.getCatalog).not.toHaveBeenCalled()
    expect(api.listModelConnections).toHaveBeenCalledOnce()
    expect(api.getModelConnection).toHaveBeenCalledWith(id)
    expect(wrapper.find('[data-editor="model"]').exists()).toBe(true)
    expect(wrapper.get('[data-testid="editor-region"]').classes()).toContain('component-editor-region')
    expect(wrapper.get('[data-testid="inspector-region"] [data-testid="validation-checklist"]').exists()).toBe(true)
    expect(wrapper.get('.page-action-dock').findAll('button').map((button) => button.text())).toEqual([
      'common.copy', 'common.delete', 'common.new', 'common.save',
    ])
    wrapper.unmount()
  })

  it('keeps route loading failures inline without also creating a toast', async () => {
    api.listBlockSummaries.mockRejectedValueOnce(new Error('offline'))
    const { wrapper } = await mountAt('/agent-components/model-requirement')

    expect(wrapper.get('[data-testid="page-error"]').attributes('role')).toBe('alert')
    expect(toastNotify).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('loads Skill templates on entry and refreshes them explicitly', async () => {
    const { router, wrapper } = await mountAt('/agent-components/model-requirement')
    await router.push('/agent-components/skill')
    await flushPromises()

    expect(api.listBlockSummaries).toHaveBeenLastCalledWith('skill')
    expect(api.listSkills).toHaveBeenCalledOnce()
    expect(api.inspectPrivateSkills).not.toHaveBeenCalled()
    const refresh = wrapper.findAll('[data-editor="skill"] button')
      .find((button) => button.text() === 'editors.common.refresh')
    if (!refresh) throw new Error('skill refresh button not found')
    await refresh.trigger('click')
    await flushPromises()

    expect(api.listSkills).toHaveBeenCalledTimes(2)
    expect(api.inspectPrivateSkills).not.toHaveBeenCalled()
    expect(api.listCustomToolTemplates).not.toHaveBeenCalled()
    expect(api.listMiddlewareTemplates).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('ignores a Skill package inspection that finishes after another owner is selected', async () => {
    const firstId = '00000000-0000-4000-8000-000000000011'
    const secondId = '00000000-0000-4000-8000-000000000022'
    const first = deferred<SkillPackageInspection>()
    api.listBlockSummaries.mockResolvedValueOnce(summaryCollection([
      skillRecord(firstId), skillRecord(secondId),
    ]))
    api.getBlock.mockImplementation(async (_type: BlockType, id: string) => ({
      ...skillRecord(id),
      skill_package_contents: privateSkillInspection(
        id,
        id === firstId ? 'First owner skill' : 'Second owner skill',
      ),
    }))
    api.inspectPrivateSkills.mockReturnValueOnce(first.promise)
    const { router, wrapper } = await mountAt(`/agent-components/skill?id=${firstId}`)

    const refresh = wrapper.findAll('[data-editor="skill"] button')
      .find((button) => button.text() === 'editors.common.refresh')
    if (!refresh) throw new Error('skill refresh button not found')
    await refresh.trigger('click')
    expect(api.inspectPrivateSkills).toHaveBeenCalledWith(firstId)

    await router.push(`/agent-components/skill?id=${secondId}`)
    await flushPromises()
    first.resolve(privateSkillInspection(firstId, 'First owner skill'))
    await flushPromises()

    expect(api.listBlockSummaries).toHaveBeenCalledTimes(1)
    expect(api.validateRepository).toHaveBeenCalledTimes(1)
    expect(api.inspectPrivateSkills).toHaveBeenCalledTimes(1)
    expect(wrapper.get('[data-testid="private-skill-item"]').text()).toContain('Second owner skill')
    expect(wrapper.text()).not.toContain('First owner skill')
    wrapper.unmount()
  })

  it('ignores a Skill package mutation response after switching owners', async () => {
    const firstId = '00000000-0000-4000-8000-000000000033'
    const secondId = '00000000-0000-4000-8000-000000000044'
    const mutation = deferred<SkillPackageInspection>()
    api.listBlockSummaries.mockResolvedValueOnce(summaryCollection([
      skillRecord(firstId), skillRecord(secondId),
    ]))
    api.getBlock.mockImplementation(async (_type: BlockType, id: string) => ({
      ...skillRecord(id),
      skill_package_contents: privateSkillInspection(
        id,
        id === firstId ? 'First existing skill' : 'Second existing skill',
      ),
    }))
    api.addPrivateSkill.mockReturnValueOnce(mutation.promise)
    const { router, wrapper } = await mountAt(`/agent-components/skill?id=${firstId}`)

    await wrapper.get('[data-testid="skill-template-item"] button').trigger('click')
    expect(api.addPrivateSkill).toHaveBeenCalledWith(firstId, 'group/research')
    await router.push(`/agent-components/skill?id=${secondId}`)
    await flushPromises()
    mutation.resolve(privateSkillInspection(firstId, 'Stale added skill'))
    await flushPromises()

    expect(wrapper.get('[data-testid="private-skill-item"]').text()).toContain('Second existing skill')
    expect(wrapper.text()).not.toContain('Stale added skill')
    wrapper.unmount()
  })

  it('loads templates without validating an extension before its first save', async () => {
    api.getCatalog.mockResolvedValueOnce({
      block_types: [skillManifest, modelManifest],
      workflow_component_types: [commandManifest],
      editor_defaults: { 'command': {} },
    })
    api.listBlockSummaries.mockResolvedValueOnce(summaryCollection([]))
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{
        path: '/workflow-components/:type',
        component: ComponentsPage,
        props: { scope: 'workflow' },
      }],
    })
    await router.push('/workflow-components/command')
    await router.isReady()

    const wrapper = mount(ComponentsPage, {
      props: { scope: 'workflow' },
      global: { plugins: [router] },
    })
    await settleComponentPage(wrapper)

    expect(api.listCommandTemplates).toHaveBeenCalledOnce()
    expect(api.listMiddlewareTemplates).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid="validation-checklist"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('requires a template and rejects duplicate names for Python extensions', async () => {
    api.getCatalog.mockResolvedValueOnce({
      block_types: [skillManifest, modelManifest],
      workflow_component_types: [commandManifest],
      editor_defaults: { 'command': {} },
    })
    api.listBlockSummaries.mockResolvedValueOnce(summaryCollection([{
      id: '00000000-0000-4000-8000-000000000010',
      name: 'Existing router',
      python_package: { folder: '00000000-0000-4000-8000-000000000010' },
    }]))
    api.listCommandTemplates.mockResolvedValueOnce({
      catalog: [commandTemplate],
      errors: {},
    })
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{
        path: '/workflow-components/:type',
        component: ComponentsPage,
        props: { scope: 'workflow' },
      }],
    })
    await router.push('/workflow-components/command')
    await router.isReady()
    const wrapper = mount(ComponentsPage, {
      props: { scope: 'workflow' },
      global: { plugins: [router] },
    })
    await settleComponentPage(wrapper)

    expect(wrapper.find('option[value="__empty__"]').exists()).toBe(false)
    await buttonByText(wrapper, 'common.save').trigger('click')
    expect(wrapper.get('[data-testid="page-error"]').text())
      .toContain('errors.pythonPackageTemplateRequired')
    expect(api.saveBlock).not.toHaveBeenCalled()

    await wrapper.get('[data-field="record-name"]').setValue('Existing router')
    await wrapper.get('[data-editor="command"] select').setValue('basic-router')
    await buttonByText(wrapper, 'common.save').trigger('click')
    expect(wrapper.get('[data-testid="page-error"]').text())
      .toContain('errors.configurationNameConflict')
    expect(useConfirmation().current.value).toBeNull()
    expect(api.saveBlock).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('updates with an explicit UUID and creates a uniquely named new draft', async () => {
    const id = '00000000-0000-0000-0000-000000000001'
    const { wrapper } = await mountAt(`/agent-components/model-requirement?id=${id}`)
    await wrapper.get('[data-field="record-name"]').setValue('Renamed configuration')
    await buttonByText(wrapper, 'common.save').trigger('click')
    await flushPromises()

    expect(api.saveBlock).toHaveBeenNthCalledWith(
      1,
      'model-requirement',
      expect.objectContaining({ id, name: 'Renamed configuration' }),
    )

    const newButton = wrapper.findAll('button').find((button) => button.text() === 'common.new')
    if (!newButton) throw new Error('new button not found')
    await newButton.trigger('click')
    useConfirmation().accept()
    await flushPromises()
    const nameInput = wrapper.get('[data-field="record-name"]')
    expect(nameInput.classes()).toContain('is-invalid')
    expect(nameInput.attributes('aria-invalid')).toBe('true')
    expect(wrapper.get('.record-picker-name-field .invalid-feedback').text()).toBe('')
    await nameInput.setValue('Another name')
    expect(nameInput.classes()).not.toContain('is-invalid')
    expect(nameInput.attributes('aria-invalid')).toBeUndefined()
    await buttonByText(wrapper, 'common.save').trigger('click')
    await flushPromises()

    const createPayload = api.saveBlock.mock.calls[1]?.[1]
    expect(createPayload).toEqual(expect.objectContaining({ name: 'Another name' }))
    expect(createPayload).not.toHaveProperty('id')
    wrapper.unmount()
  })

  it('copies and deletes from the shared editor actions', async () => {
    const id = '00000000-0000-0000-0000-000000000001'
    const copyId = '00000000-0000-4000-8000-000000000088'
    const { router, wrapper } = await mountAt(`/agent-components/model-requirement?id=${id}`)

    await buttonByText(wrapper, 'common.copy').trigger('click')
    await wrapper.get('#component-copy-form input').setValue('Copied configuration')
    await wrapper.get('#component-copy-form').trigger('submit')
    await flushPromises()

    expect(api.copyBlock).toHaveBeenCalledWith('model-requirement', id, 'Copied configuration')
    expect(router.currentRoute.value.query.id).toBe(copyId)

    await buttonByText(wrapper, 'common.delete').trigger('click')
    useConfirmation().accept()
    await flushPromises()

    expect(api.deleteBlock).toHaveBeenCalledWith('model-requirement', copyId)
    expect(router.currentRoute.value.query.id).toBeUndefined()
    wrapper.unmount()
  })

  it('confirms before replacing a saved configuration with the same name', async () => {
    const existingId = '00000000-0000-0000-0000-000000000001'
    const { wrapper } = await mountAt('/agent-components/model-requirement')
    await wrapper.get('[data-field="record-name"]').setValue('Shared name')

    await buttonByText(wrapper, 'common.save').trigger('click')

    expect(useConfirmation().current.value).toMatchObject({
      title: 'components.overwrite.title',
      confirmLabel: 'components.overwrite.confirm',
      dangerous: true,
    })
    expect(api.saveBlock).not.toHaveBeenCalled()

    useConfirmation().accept()
    await flushPromises()

    expect(api.saveBlock).toHaveBeenCalledWith(
      'model-requirement',
      expect.objectContaining({ id: existingId, name: 'Shared name' }),
    )
    wrapper.unmount()
  })

  it('keeps save enabled and renders validation returned by a failed save', async () => {
    const validation = {
      valid: false,
      stage: 'block_save',
      issues: [{
        code: 'field.required',
        scope: 'block',
        owner_id: '',
        owner_name: '',
        path: 'name',
        message: 'backend validation message',
        message_key: 'validation.issue.contract.fieldRequired',
        message_args: {},
      }],
    }
    api.saveBlock.mockRejectedValueOnce(new ManagementApiError({
      status: 422,
      code: 'configuration_validation_failed',
      message: 'save rejected',
      validation,
    }))
    const { wrapper } = await mountAt('/agent-components/model-requirement')
    const saveButton = buttonByText(wrapper, 'common.save')

    expect(saveButton.attributes('disabled')).toBeUndefined()
    await saveButton.trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="validation-checklist"]').attributes('data-status')).toBe('invalid')
    expect(wrapper.get('[data-testid="validation-checklist"]').text()).toContain('validation.issue.contract.fieldRequired')
    expect(wrapper.get('[data-testid="validation-checklist"]').text()).not.toContain('backend validation message')
    expect(toastNotify).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('keeps a dirty draft until the user confirms a route change', async () => {
    const { router, wrapper } = await mountAt('/agent-components/model-requirement')
    await wrapper.get('[data-field="record-name"]').setValue('Unsaved name')

    const skillButton = wrapper.findAll('[data-testid="section-nav"] button')
      .find((button) => button.text().includes('capabilities.skill.label'))
    if (!skillButton) throw new Error('skill navigation button not found')

    await skillButton.trigger('click')
    expect(useConfirmation().current.value?.title).toBe('unsavedChanges.title')
    useConfirmation().cancel()
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/agent-components/model-requirement')
    expect(wrapper.get('[data-field="record-name"]').element).toHaveProperty('value', 'Unsaved name')

    await skillButton.trigger('click')
    useConfirmation().accept()
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/agent-components/skill')
    expect(wrapper.find('.app-content-header').exists()).toBe(false)
    wrapper.unmount()
  })

})
