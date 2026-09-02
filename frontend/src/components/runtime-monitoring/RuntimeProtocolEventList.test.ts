import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { describe, expect, it } from 'vitest'

import type { RuntimeMonitoringProtocolEventSequence } from '@/api'
import { en } from '@/locales/en'

import RuntimeProtocolEventList from './RuntimeProtocolEventList.vue'

const sequence: RuntimeMonitoringProtocolEventSequence = {
  availability: 'available',
  read_at: '2026-09-03T00:00:10Z',
  items: [{
    sequence: 7,
    method: 'messages',
    captured_at: '2026-09-03T00:00:05Z',
    envelope: {
      type: 'event',
      method: 'messages',
      seq: 7,
      params: {
        namespace: [],
        timestamp: 1,
        data: [{
          event: 'content-block-delta',
          delta: { type: 'text-delta', text: 'persisted stream text' },
        }],
      },
    },
    origin: {
      source_type: 'agent',
      workflow_node_id: 'agent-node',
      node_invocation_id: 'invocation-1',
      agent_profile_id: 'agent-profile-1',
      subagent_profile_id: '',
    },
  }],
  after_sequence: 0,
  next_after_sequence: 7,
  limit: 100,
  remaining: 0,
}

function mountList(error = '') {
  return mount(RuntimeProtocolEventList, {
    props: { sequence, loading: false, error },
    global: {
      plugins: [createI18n({ legacy: false, locale: 'en', messages: { en } })],
    },
  })
}

describe('RuntimeProtocolEventList', () => {
  it('keeps the last good stream visible with direct origin when refresh fails', () => {
    const wrapper = mountList('temporary refresh failure')

    expect(wrapper.text()).toContain('temporary refresh failure')
    expect(wrapper.text()).toContain('persisted stream text')
    expect(wrapper.text()).toContain('Node agent-node')
    expect(wrapper.text()).toContain('Invocation invocation-1')
    expect(wrapper.text()).toContain('Agent agent-profile-1')
    expect(wrapper.get('pre').text()).toContain('workflow_node_id')
  })

  it('lets the reader pause and resume following the latest event', async () => {
    const wrapper = mountList()
    const followButton = wrapper.findAll('button').find((button) => (
      button.text().includes('Following latest')
    ))!

    await followButton.trigger('click')
    expect(wrapper.text()).toContain('Follow latest')
    await followButton.trigger('click')
    expect(wrapper.text()).toContain('Following latest')
  })
})
