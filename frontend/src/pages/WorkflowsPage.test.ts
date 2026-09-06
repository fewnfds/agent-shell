import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import {
  managementApi,
  type SavedBlock,
  type Workflow,
  type WorkflowGraphDocument,
} from '@/api'
import { useConfirmation } from '@/composables/useConfirmation'
import { useToasts } from '@/composables/useToasts'
import {
  workflowCanvasToDocument,
  workflowDocumentToCanvas,
} from '@/domain/workflowGraph'
import { en } from '@/locales/en'

import WorkflowsPage from './WorkflowsPage.vue'

function i18n() {
  return createI18n({ legacy: false, locale: 'en', messages: { en } })
}

const workflow: Workflow = {
  id: 'workflow-1',
  name: 'Research Workflow',
  description: 'Runs the research agent.',
  is_model_entry: true,
  workflow_event_output_id: null,
  durability: 'async',
  on_disconnect: 'cancel',
  enabled: true,
}
const eventOutput: SavedBlock = { id: 'event-output-1', name: 'Public events' }

function mockComponentLists(workflows: Workflow[] = []) {
  const options = vi.spyOn(managementApi, 'getConfigurationOptions').mockResolvedValue({
    repository_id: '00000000-0000-4000-8000-000000000099',
    repository_revision: 1,
    components: {
      'workflow-event-output': [eventOutput],
    },
    main_agents: [],
    subagents: [],
    async_subagents: [],
    workflows,
  })
  vi.spyOn(managementApi, 'getWorkflow').mockImplementation(async (id) => {
    const selected = workflows.find((item) => item.id === id)
    if (!selected) throw new Error('Workflow not found')
    return selected
  })
  vi.spyOn(managementApi, 'validateRepository').mockResolvedValue({
    valid: true,
    stage: 'repository_load',
    issues: [],
  })
  return options
}

function testRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/workflows', component: { template: '<div />' } },
      { path: '/workflows/:id/editor', component: { template: '<div />' } },
    ],
  })
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((accept) => {
    resolve = accept
  })
  return { promise, resolve }
}

afterEach(() => {
  vi.restoreAllMocks()
  useConfirmation().cancel()
  const toasts = useToasts()
  for (const toast of toasts.items.value) toasts.dismiss(toast.id)
})

describe('WorkflowsPage', () => {
  it('loads a Workflow and creates a new configuration from the action dock', async () => {
    mockComponentLists([workflow])
    const create = vi.spyOn(managementApi, 'createWorkflow').mockResolvedValue(workflow)
    const router = testRouter()
    await router.push('/workflows')
    await router.isReady()

    const wrapper = mount(WorkflowsPage, {
      global: { plugins: [i18n(), router] },
    })
    await flushPromises()

    expect(wrapper.text()).toContain(workflow.name)
    expect(wrapper.text()).toContain('Edit')
    expect(wrapper.text()).toContain('Copy')
    expect(wrapper.text()).toContain('Delete')
    const assemblyColumns = wrapper.get('[data-testid="workflow-component-assembly-row"]').findAll(':scope > div')
    expect(assemblyColumns).toHaveLength(4)
    expect(assemblyColumns.every((column) => column.classes().includes('col-lg-4'))).toBe(true)
    expect(assemblyColumns.every((column) => column.find('.card').exists())).toBe(true)
    expect(wrapper.get('#workflow-description').element.tagName).toBe('TEXTAREA')
    expect(wrapper.get('#workflow-model-entry').element.tagName).toBe('SELECT')
    await wrapper.findAll('button').find((button) => button.text() === 'New')!.trigger('click')
    await flushPromises()

    await wrapper.get('[data-field="record-name"]').setValue('New Workflow')
    await wrapper.get('textarea').setValue('New description')
    await wrapper.get('#workflow-model-entry').setValue(true)
    await wrapper.get('#workflow-event-output').setValue(eventOutput.id)
    await wrapper.get('#workflow-durability').setValue('sync')
    await wrapper.get('#workflow-on-disconnect').setValue('continue')
    await wrapper.findAll('button').find((button) => button.text() === 'Save')!.trigger('click')
    await flushPromises()

    expect(create).toHaveBeenCalledWith({
      name: 'New Workflow',
      description: 'New description',
      is_model_entry: true,
      workflow_event_output_id: eventOutput.id,
      durability: 'sync',
      on_disconnect: 'continue',
    })

    wrapper.unmount()
  })

  it('copies the selected Workflow and switches to the draft copy', async () => {
    mockComponentLists([workflow])
    const copied = {
      ...workflow,
      id: 'workflow-copy',
      name: 'Research Workflow copy',
      enabled: false,
    }
    const copy = vi.spyOn(managementApi, 'copyWorkflow').mockResolvedValue(copied)
    const router = testRouter()
    await router.push('/workflows')
    await router.isReady()
    const wrapper = mount(WorkflowsPage, {
      global: { plugins: [i18n(), router] },
    })
    await flushPromises()

    await wrapper.findAll('button').find((button) => button.text() === 'Copy')!.trigger('click')
    await wrapper.get('#workflow-copy-form input').setValue(copied.name)
    await wrapper.get('#workflow-copy-form').trigger('submit')
    await flushPromises()

    expect(copy).toHaveBeenCalledWith(workflow.id, copied.name)
    expect(router.currentRoute.value.query.id).toBe(copied.id)
    expect(wrapper.text()).toContain('Draft')
    wrapper.unmount()
  })

  it('deletes the selected Workflow and returns to a blank form', async () => {
    mockComponentLists([workflow])
    const remove = vi.spyOn(managementApi, 'deleteWorkflow').mockResolvedValue({ ok: true })
    const router = testRouter()
    await router.push(`/workflows?id=${workflow.id}`)
    await router.isReady()
    const wrapper = mount(WorkflowsPage, {
      global: { plugins: [i18n(), router] },
    })
    await flushPromises()

    await wrapper.findAll('button').find((button) => button.text() === 'Delete')!.trigger('click')
    useConfirmation().accept()
    await flushPromises()

    expect(remove).toHaveBeenCalledWith(workflow.id)
    expect(router.currentRoute.value.query.id).toBeUndefined()
    expect((wrapper.get('[data-field="record-name"]').element as HTMLInputElement).value).toBe('')
    expect(wrapper.text()).toContain('Not saved')
    wrapper.unmount()
  })

  it('round-trips official execution settings and can remove event output', async () => {
    const configured = {
      ...workflow,
      workflow_event_output_id: eventOutput.id,
      durability: 'exit' as const,
      on_disconnect: 'continue' as const,
    }
    mockComponentLists([configured])
    const update = vi.spyOn(managementApi, 'updateWorkflow').mockResolvedValue(configured)
    const router = testRouter()
    await router.push('/workflows')
    await router.isReady()

    const wrapper = mount(WorkflowsPage, {
      global: { plugins: [i18n(), router] },
    })
    await flushPromises()

    expect((wrapper.get('#workflow-event-output').element as HTMLSelectElement).value).toBe(eventOutput.id)
    expect((wrapper.get('#workflow-durability').element as HTMLSelectElement).value).toBe('exit')
    expect((wrapper.get('#workflow-on-disconnect').element as HTMLSelectElement).value).toBe('continue')
    await wrapper.get('#workflow-event-output').setValue('')
    await wrapper.findAll('button').find((button) => button.text() === 'Save')!.trigger('click')
    await flushPromises()

    expect(update).toHaveBeenCalledWith(workflow.id, {
      name: workflow.name,
      description: workflow.description,
      is_model_entry: true,
      workflow_event_output_id: null,
      durability: 'exit',
      on_disconnect: 'continue',
    })
    wrapper.unmount()
  })

  it('shows missing metadata UUIDs and only this Workflow repository issues', async () => {
    const missingOutputId = '00000000-0000-4000-8000-000000000072'
    const configured = {
      ...workflow,
      workflow_event_output_id: missingOutputId,
    }
    mockComponentLists([configured])
    vi.mocked(managementApi.validateRepository).mockResolvedValue({
      valid: false,
      stage: 'repository_load',
      issues: [
        {
          code: 'configuration.reference_not_found',
          scope: 'workflow',
          owner_id: workflow.id,
          owner_name: workflow.name,
          owner_type: 'workflow',
          path: 'workflow_event_output_id',
          message: 'Missing Workflow Event Output',
          message_key: 'validation.issue.configuration.referenceNotFound',
          message_args: { expected_type: 'workflow-event-output', reference_id: missingOutputId },
          severity: 'error',
        },
        {
          code: 'configuration.reference_not_found',
          scope: 'workflow',
          owner_id: 'other-workflow',
          owner_name: 'Other Workflow',
          owner_type: 'workflow',
          path: 'workflow_event_output_id',
          message: 'Unrelated',
          message_key: 'validation.issue.configuration.referenceNotFound',
          message_args: { expected_type: 'workflow-event-output', reference_id: 'other-id' },
          severity: 'error',
        },
      ],
    })
    const router = testRouter()
    await router.push(`/workflows?id=${workflow.id}`)
    await router.isReady()
    const wrapper = mount(WorkflowsPage, {
      global: { plugins: [i18n(), router] },
    })
    await flushPromises()

    expect(wrapper.get('#workflow-event-output').text()).toContain(missingOutputId)
    expect(wrapper.findAll('[data-testid="validation-issue"]')).toHaveLength(1)
    expect(wrapper.text()).not.toContain('Other Workflow')
    wrapper.unmount()
  })

  it('freezes record changes during save and sorts a created Workflow immediately', async () => {
    const pending = deferred<Workflow>()
    mockComponentLists([workflow])
    vi.spyOn(managementApi, 'createWorkflow').mockReturnValue(pending.promise)
    const router = testRouter()
    await router.push('/workflows')
    await router.isReady()
    const wrapper = mount(WorkflowsPage, {
      global: { plugins: [i18n(), router] },
    })
    await flushPromises()

    await wrapper.findAll('button').find((button) => button.text() === 'New')!.trigger('click')
    await wrapper.get('[data-field="record-name"]').setValue('Apple Workflow')
    await wrapper.findAll('button').find((button) => button.text() === 'Save')!.trigger('click')
    await flushPromises()

    const newButton = wrapper.findAll('button').find((button) => button.text() === 'New')!
    expect(newButton.attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-testid="record-picker-select"]').attributes('disabled')).toBeDefined()
    await newButton.trigger('click')
    expect((wrapper.get('[data-field="record-name"]').element as HTMLInputElement).value).toBe('Apple Workflow')

    pending.resolve({ ...workflow, id: 'workflow-apple', name: 'Apple Workflow' })
    await flushPromises()
    expect(wrapper.get('[data-testid="record-picker-select"]').findAll('option').slice(1).map((option) => option.text())).toEqual([
      'Apple Workflow',
      'Research Workflow',
    ])
    wrapper.unmount()
  })

  it('canonicalizes an invalid Workflow query and removes it for an empty list', async () => {
    const options = mockComponentLists([workflow])
    const router = testRouter()
    await router.push('/workflows?id=missing')
    await router.isReady()
    const wrapper = mount(WorkflowsPage, {
      global: { plugins: [i18n(), router] },
    })
    await flushPromises()

    expect(router.currentRoute.value.query.id).toBe(workflow.id)
    wrapper.unmount()

    options.mockResolvedValue({
      repository_id: '00000000-0000-4000-8000-000000000099',
      repository_revision: 1,
      components: {
        'workflow-event-output': [eventOutput],
      },
      main_agents: [],
      subagents: [],
      workflows: [],
    })
    const emptyRouter = testRouter()
    await emptyRouter.push('/workflows?id=missing')
    await emptyRouter.isReady()
    const emptyWrapper = mount(WorkflowsPage, {
      global: { plugins: [i18n(), emptyRouter] },
    })
    await flushPromises()

    expect(emptyRouter.currentRoute.value.query.id).toBeUndefined()
    emptyWrapper.unmount()
  })

  it('round-trips the current Vue Flow document and viewport', () => {
    const document: WorkflowGraphDocument = {
      definition: {
        schema_version: 1,
        state_contract: 'agent-shell.workflow.control.v1',
        nodes: [
          { id: 'start', type: 'start', type_version: 1, config: {} },
          {
            id: 'command',
            type: 'command',
            type_version: 1,
            config: { command_id: '11111111-1111-4111-8111-111111111111' },
          },
          { id: 'end', type: 'end', type_version: 1, config: {} },
        ],
        edges: [
          {
            id: 'edge-start-command',
            source: 'start',
            source_handle: 'next',
            target: 'command',
            target_handle: 'in',
          },
          {
            id: 'edge-command-end',
            source: 'command',
            source_handle: 'next',
            target: 'end',
            target_handle: 'in',
          },
        ],
      },
      layout: {
        nodes: {
          start: { x: 80, y: 180 },
          command: { x: 360, y: 180 },
          end: { x: 680, y: 180 },
        },
        viewport: { x: 25, y: 40, zoom: 1.25 },
      },
    }

    const canvas = workflowDocumentToCanvas(document, [
      {
        type: 'start',
        type_version: 1,
        runtime_kind: 'graph_entry',
        title_key: '',
        description_key: '',
        config_schema: {},
        input_handles: [],
        output_handles: [{ id: 'next', kind: 'control', edge_type: 'normal', max_connections: null }],
      },
      {
        type: 'command',
        type_version: 1,
        runtime_kind: 'command_node',
        title_key: '',
        description_key: '',
        config_schema: {},
        input_handles: [{ id: 'in', kind: 'control', edge_type: 'normal', max_connections: null }],
        output_handles: [{ id: 'next', kind: 'control', edge_type: 'normal', max_connections: null }],
      },
      {
        type: 'end',
        type_version: 1,
        runtime_kind: 'graph_exit',
        title_key: '',
        description_key: '',
        config_schema: {},
        input_handles: [{ id: 'in', kind: 'control', edge_type: 'normal', max_connections: null }],
        output_handles: [],
      },
    ])

    expect(workflowCanvasToDocument(canvas.nodes, canvas.edges, canvas.viewport)).toEqual(document)
  })
})
