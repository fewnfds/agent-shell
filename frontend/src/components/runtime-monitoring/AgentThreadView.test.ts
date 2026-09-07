import { AIMessage, HumanMessage, ToolMessage } from '@langchain/core/messages'
import { mount } from '@vue/test-utils'
import { computed, defineComponent, ref } from 'vue'
import { createI18n } from 'vue-i18n'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { managementAuthorizedFetch } from '@/api'
import { en } from '@/locales/en'

import AgentThreadView from './AgentThreadView.vue'

const useStreamMock = vi.fn()

vi.mock('@langchain/vue', () => ({
  useStream: (...args: unknown[]) => useStreamMock(...args),
}))

vi.mock('markstream-vue', () => ({
  default: defineComponent({
    props: ['content'],
    template: '<div class="markdown-render">{{ content }}</div>',
  }),
}))

afterEach(() => {
  vi.restoreAllMocks()
  useStreamMock.mockReset()
})

describe('AgentThreadView', () => {
  it('binds an existing Thread with management auth and renders message and Tool facts', () => {
    useStreamMock.mockReturnValue({
      values: ref({ messages: [] }),
      messages: ref([
        new HumanMessage({ id: 'human-1', content: 'Question' }),
        new AIMessage({
          id: 'ai-1',
          content: [
            { type: 'reasoning', reasoning: 'Working', id: 'reasoning-1' },
            { type: 'text', text: 'Answer', id: 'text-1' },
            {
              type: 'tool_call',
              id: 'call-1',
              name: 'search',
              args: { query: 'evidence' },
            },
          ],
          tool_calls: [{ id: 'call-1', name: 'search', args: { query: 'evidence' } }],
        }),
        new ToolMessage({
          id: 'tool-1',
          tool_call_id: 'call-1',
          content: 'result',
        }),
      ]),
      toolCalls: ref([]),
      interrupts: ref([]),
      error: ref(undefined),
      isThreadLoading: ref(false),
      isLoading: computed(() => false),
    })

    const wrapper = mount(AgentThreadView, {
      props: { assistantId: 'assistant-1', threadId: 'thread-1' },
      global: {
        plugins: [createI18n({ legacy: false, locale: 'en', messages: { en } })],
      },
    })

    expect(useStreamMock).toHaveBeenCalledWith(expect.objectContaining({
      assistantId: 'assistant-1',
      threadId: 'thread-1',
      fetch: managementAuthorizedFetch,
      callerOptions: { fetch: managementAuthorizedFetch },
      fetchStateHistory: false,
    }))
    expect(wrapper.findAll('.markdown-render').map((block) => block.text()))
      .toEqual(['Question', 'Working', 'Answer'])
    expect(wrapper.findAll('.tool-activity')).toHaveLength(1)
    expect(wrapper.get('.tool-activity').text()).toContain('search')
    expect(wrapper.get('.tool-activity').text()).toContain('Finished')
    expect(wrapper.get('.tool-activity').text()).toContain('result')
  })
})
