import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import {
  managementApi,
  type ResponseStreamPolicy,
  type Workflow,
  type WorkflowGraphDocument,
} from '@/api'
import { en } from '@/locales/en'

import WorkflowResponseStreamPage from './WorkflowResponseStreamPage.vue'

const workflow: Workflow = {
  id: 'workflow-1',
  name: 'Streaming Workflow',
  workflow_role: 'parent',
  description: '',
  checkpointer_id: null,
  workflow_event_output_id: null,
  cancel_on_upstream_termination: true,
  recursion_limit: 1_000_000,
  execution_timeout_seconds: 1_200,
  max_concurrency: 100,
  enabled: true,
}

const policy: ResponseStreamPolicy = {
  queue: { mode: 'fair_turns', successor_grace_seconds: 2 },
  assistant_text: { delivery: 'live', live_wrapper: { start: '', end: '' } },
  reasoning: {
    delivery: 'live',
    live_wrapper: { start: '<reasoning>', end: '</reasoning>\n' },
  },
  subagent_content: { delivery: 'hidden' },
  tools: { delivery: 'paired' },
  subagent_lifecycle: { delivery: 'activity' },
  workflow_custom: { delivery: 'complete' },
  workflow_lifecycle: { delivery: 'activity' },
  activity: {
    announce_start: true,
    announce_queued: true,
    hidden_delta_pulse_seconds: 15,
    quiet_notice_after_seconds: 30,
    quiet_notice_repeat_seconds: 60,
  },
  source_overrides: [],
}

const graph: WorkflowGraphDocument = {
  definition: {
    schema_version: 1,
    state_contract: 'agent-shell.workflow.agent-invocations.v1',
    nodes: [
      { id: 'start', type: 'start', type_version: 1, config: {} },
      {
        id: 'writer',
        type: 'agent',
        type_version: 1,
        config: { main_agent_id: 'agent-1' },
      },
      {
        id: 'route',
        type: 'command',
        type_version: 1,
        config: { command_id: 'command-1' },
      },
      { id: 'end', type: 'end', type_version: 1, config: {} },
    ],
    edges: [],
  },
  layout: { nodes: {}, viewport: { x: 0, y: 0, zoom: 1 } },
}

function i18n() {
  return createI18n({ legacy: false, locale: 'en', messages: { en } })
}

function testRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/workflows/parents', component: { template: '<div />' } },
      {
        path: '/workflows/:id/response-stream',
        component: WorkflowResponseStreamPage,
      },
    ],
  })
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('WorkflowResponseStreamPage', () => {
  it('loads and saves the narrow policy without editing Workflow metadata', async () => {
    vi.spyOn(managementApi, 'getWorkflow').mockResolvedValue(workflow)
    vi.spyOn(managementApi, 'getResponseStreamPolicy').mockResolvedValue(
      structuredClone(policy),
    )
    vi.spyOn(managementApi, 'getWorkflowGraph').mockResolvedValue(graph)
    const save = vi.spyOn(
      managementApi,
      'updateResponseStreamPolicy',
    ).mockImplementation(async (_id, payload) => structuredClone(payload))
    const metadataSave = vi.spyOn(managementApi, 'updateWorkflow')
    const router = testRouter()
    await router.push('/workflows/workflow-1/response-stream')
    await router.isReady()

    const wrapper = mount(WorkflowResponseStreamPage, {
      global: { plugins: [i18n(), router] },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('Streaming Workflow')
    expect(wrapper.text()).toContain('Fair Agent turns')
    expect(wrapper.text()).toContain('writer · Agent Node')
    expect(wrapper.text()).not.toContain('start · Start')

    await wrapper.get('#response-queue-mode').setValue('strict_source')
    await wrapper.get('#response-successor-grace').setValue('1.5')
    const wrapperTextareas = wrapper.findAll('textarea')
    await wrapperTextareas[0]!.setValue('  <answer>\n')
    await wrapper.get('#source-writer').setValue('activity_only')
    await wrapper.get('#activity-quiet_notice_repeat_seconds').setValue('')
    const saveButton = wrapper.get('[data-testid="response-stream-save"]')
    expect(saveButton.attributes('disabled')).toBeUndefined()
    await saveButton.trigger('click')
    await flushPromises()

    expect(save).toHaveBeenCalledOnce()
    const [workflowId, savedPolicy] = save.mock.calls[0]!
    expect(workflowId).toBe(workflow.id)
    expect(savedPolicy.queue).toEqual({
      mode: 'strict_source',
      successor_grace_seconds: 1.5,
    })
    expect(savedPolicy.assistant_text.live_wrapper.start).toBe('  <answer>\n')
    expect(savedPolicy.activity.quiet_notice_repeat_seconds).toBeNull()
    expect(savedPolicy.source_overrides).toEqual([
      { workflow_node_id: 'writer', visibility: 'activity_only' },
    ])
    expect(metadataSave).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid="response-stream-saved"]').exists()).toBe(true)
    wrapper.unmount()
  })
})
