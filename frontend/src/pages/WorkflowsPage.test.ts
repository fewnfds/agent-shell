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
  workflow_role: 'parent',
  description: 'Runs the research agent.',
  workflow_event_output_id: null,
  recursion_limit: 1_000_000,
  execution_timeout_seconds: 1_200,
  max_concurrency: 100,
  enabled: true,
}
const eventOutput: SavedBlock = { id: 'event-output-1', name: 'Public events' }

function mockComponentLists(): void {
  vi.spyOn(managementApi, 'listBlocks').mockImplementation(async (type) => {
    if (type === 'workflow-event-output') return [eventOutput]
    return []
  })
}

function testRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/workflows', component: { template: '<div />' } },
      { path: '/workflows/parents', component: { template: '<div />' } },
      { path: '/workflows/children', component: { template: '<div />' } },
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
    vi.spyOn(managementApi, 'listWorkflows').mockResolvedValue([workflow])
    mockComponentLists()
    const create = vi.spyOn(managementApi, 'createWorkflow').mockResolvedValue(workflow)
    const router = testRouter()
    await router.push('/workflows/parents')
    await router.isReady()

    const wrapper = mount(WorkflowsPage, {
      props: { workflowRole: 'parent' },
      global: { plugins: [i18n(), router] },
    })
    await flushPromises()

    expect(wrapper.text()).toContain(workflow.name)
    expect(wrapper.text()).toContain('Edit Flow')
    expect(wrapper.text()).not.toContain('Delete')
    await wrapper.findAll('button').find((button) => button.text() === 'New')!.trigger('click')
    await flushPromises()

    await wrapper.get('[data-field="record-name"]').setValue('New Workflow')
    await wrapper.get('textarea').setValue('New description')
    const componentSelects = wrapper.findAll('select').filter((select) => !select.attributes('data-testid'))
    await componentSelects[0]!.setValue(eventOutput.id)
    const runtimeLimits = wrapper.findAll('input[type="number"]')
    await runtimeLimits[0]!.setValue(250)
    await runtimeLimits[1]!.setValue(90_000)
    await runtimeLimits[2]!.setValue(300)
    await wrapper.findAll('button').find((button) => button.text() === 'Save')!.trigger('click')
    await flushPromises()

    expect(create).toHaveBeenCalledWith({
      name: 'New Workflow',
      workflow_role: 'parent',
      description: 'New description',
      workflow_event_output_id: eventOutput.id,
      recursion_limit: 250,
      execution_timeout_seconds: 90_000,
      max_concurrency: 300,
    })

    wrapper.unmount()
  })

  it('queries and creates child Workflows from the child page', async () => {
    const list = vi.spyOn(managementApi, 'listWorkflows').mockResolvedValue([])
    mockComponentLists()
    const child = { ...workflow, id: 'workflow-child', workflow_role: 'child' as const }
    const create = vi.spyOn(managementApi, 'createWorkflow').mockResolvedValue(child)
    const router = testRouter()
    await router.push('/workflows/children')
    await router.isReady()

    const wrapper = mount(WorkflowsPage, {
      props: { workflowRole: 'child' },
      global: { plugins: [i18n(), router] },
    })
    await flushPromises()

    expect(list).toHaveBeenCalledWith('child')
    await wrapper.findAll('button').find((button) => button.text() === 'New')!.trigger('click')
    await wrapper.get('[data-field="record-name"]').setValue('Child Workflow')
    await wrapper.findAll('button').find((button) => button.text() === 'Save')!.trigger('click')
    await flushPromises()

    expect(create).toHaveBeenCalledWith({
      name: 'Child Workflow',
      workflow_role: 'child',
      description: '',
      workflow_event_output_id: null,
      recursion_limit: 1_000_000,
      execution_timeout_seconds: 1_200,
      max_concurrency: 100,
    })
    wrapper.unmount()
  })

  it('round-trips the reusable event output component reference', async () => {
    const configured = {
      ...workflow,
      workflow_event_output_id: eventOutput.id,
    }
    vi.spyOn(managementApi, 'listWorkflows').mockResolvedValue([configured])
    mockComponentLists()
    const update = vi.spyOn(managementApi, 'updateWorkflow').mockResolvedValue(configured)
    const router = testRouter()
    await router.push('/workflows/parents')
    await router.isReady()

    const wrapper = mount(WorkflowsPage, {
      props: { workflowRole: 'parent' },
      global: { plugins: [i18n(), router] },
    })
    await flushPromises()

    const componentSelects = wrapper.findAll('select').filter((select) => !select.attributes('data-testid'))
    expect((componentSelects[0]!.element as HTMLSelectElement).value).toBe(eventOutput.id)
    await wrapper.findAll('button').find((button) => button.text() === 'Save')!.trigger('click')
    await flushPromises()

    expect(update).toHaveBeenCalledWith(workflow.id, {
      name: workflow.name,
      workflow_role: 'parent',
      description: workflow.description,
      workflow_event_output_id: eventOutput.id,
      recursion_limit: 1_000_000,
      execution_timeout_seconds: 1_200,
      max_concurrency: 100,
    })
    wrapper.unmount()
  })

  it('freezes record changes during save and sorts a created Workflow immediately', async () => {
    const pending = deferred<Workflow>()
    vi.spyOn(managementApi, 'listWorkflows').mockResolvedValue([workflow])
    mockComponentLists()
    vi.spyOn(managementApi, 'createWorkflow').mockReturnValue(pending.promise)
    const router = testRouter()
    await router.push('/workflows/parents')
    await router.isReady()
    const wrapper = mount(WorkflowsPage, {
      props: { workflowRole: 'parent' },
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
    const list = vi.spyOn(managementApi, 'listWorkflows').mockResolvedValue([workflow])
    mockComponentLists()
    const router = testRouter()
    await router.push('/workflows/parents?id=missing')
    await router.isReady()
    const wrapper = mount(WorkflowsPage, {
      props: { workflowRole: 'parent' },
      global: { plugins: [i18n(), router] },
    })
    await flushPromises()

    expect(router.currentRoute.value.query.id).toBe(workflow.id)
    wrapper.unmount()

    list.mockResolvedValue([])
    const emptyRouter = testRouter()
    await emptyRouter.push('/workflows/parents?id=missing')
    await emptyRouter.isReady()
    const emptyWrapper = mount(WorkflowsPage, {
      props: { workflowRole: 'parent' },
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
        state_contract: 'agent-shell.workflow.agent-invocations.v1',
        nodes: [
          { id: 'start', type: 'start', type_version: 1, config: {} },
          {
            id: 'agent',
            type: 'agent',
            type_version: 1,
            config: { main_agent_id: '11111111-1111-4111-8111-111111111111' },
          },
          { id: 'end', type: 'end', type_version: 1, config: {} },
        ],
        edges: [
          {
            id: 'edge-start-agent',
            source: 'start',
            source_handle: 'next',
            target: 'agent',
            target_handle: 'in',
          },
          {
            id: 'edge-agent-end',
            source: 'agent',
            source_handle: 'next',
            target: 'end',
            target_handle: 'in',
          },
        ],
      },
      layout: {
        nodes: {
          start: { x: 80, y: 180 },
          agent: { x: 360, y: 180 },
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
        workflow_roles: ['parent', 'child'],
        input_handles: [],
        output_handles: [{ id: 'next', kind: 'control', edge_type: 'normal', max_connections: null }],
      },
      {
        type: 'agent',
        type_version: 1,
        runtime_kind: 'agent_wrapper',
        title_key: '',
        description_key: '',
        config_schema: {},
        workflow_roles: ['parent', 'child'],
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
        workflow_roles: ['parent', 'child'],
        input_handles: [{ id: 'in', kind: 'control', edge_type: 'normal', max_connections: null }],
        output_handles: [],
      },
    ])

    expect(workflowCanvasToDocument(canvas.nodes, canvas.edges, canvas.viewport)).toEqual(document)
  })
})
