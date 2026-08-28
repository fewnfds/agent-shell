import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { describe, expect, it } from 'vitest'

import type { ResponseStreamPolicy, WorkflowGraphNode } from '@/api'
import { en } from '@/locales/en'

import ResponseStreamPolicyEditor from './ResponseStreamPolicyEditor.vue'

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

const graphNodes: WorkflowGraphNode[] = [
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
]

function i18n() {
  return createI18n({ legacy: false, locale: 'en', messages: { en } })
}

describe('ResponseStreamPolicyEditor', () => {
  it('edits the Parent Workflow policy without owning save or CRUD actions', async () => {
    const wrapper = mount(ResponseStreamPolicyEditor, {
      props: {
        graphNodes,
        modelValue: structuredClone(policy),
        'onUpdate:modelValue': (value: ResponseStreamPolicy) => {
          void wrapper.setProps({ modelValue: value })
        },
      },
      global: { plugins: [i18n()] },
    })

    expect(wrapper.text()).toContain('Fair Agent turns')
    expect(wrapper.text()).toContain('writer · Agent Node')
    expect(wrapper.text()).not.toContain('start · Start')
    expect(wrapper.find('[data-testid="response-stream-policy-editor"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="response-stream-save"]').exists()).toBe(false)

    await wrapper.get('#response-queue-mode').setValue('strict_source')
    await wrapper.get('#response-successor-grace').setValue('1.5')
    await wrapper.findAll('textarea')[0]!.setValue('  <answer>\n')
    await wrapper.get('#source-writer').setValue('activity_only')
    await wrapper.get('#activity-quiet_notice_repeat_seconds').setValue('')

    const updates = wrapper.emitted<ResponseStreamPolicy[]>('update:modelValue') ?? []
    const savedPolicy = updates.at(-1)?.[0]
    expect(savedPolicy?.queue).toEqual({
      mode: 'strict_source',
      successor_grace_seconds: 1.5,
    })
    expect(savedPolicy?.assistant_text.live_wrapper.start).toBe('  <answer>\n')
    expect(savedPolicy?.activity.quiet_notice_repeat_seconds).toBeNull()
    expect(savedPolicy?.source_overrides).toEqual([
      { workflow_node_id: 'writer', visibility: 'activity_only' },
    ])
  })
})
