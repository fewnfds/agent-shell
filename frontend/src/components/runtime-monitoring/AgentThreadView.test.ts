import { AIMessage, HumanMessage, ToolMessage } from '@langchain/core/messages'
import { mount } from '@vue/test-utils'
import { computed, defineComponent, nextTick, ref, type Ref } from 'vue'
import { createI18n } from 'vue-i18n'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { managementAuthorizedFetch } from '@/api'
import { en } from '@/locales/en'

import AgentThreadView from './AgentThreadView.vue'

const useStreamMock = vi.fn()
const useColorModeMock = vi.hoisted(() => vi.fn())
const storageMock = {
  clear: vi.fn(),
  getItem: vi.fn(() => null),
  key: vi.fn(() => null),
  get length() {
    return 0
  },
  removeItem: vi.fn(),
  setItem: vi.fn(),
}

vi.mock('@langchain/vue', () => ({
  useStream: (...args: unknown[]) => useStreamMock(...args),
}))

vi.mock('@adminlte/vue', () => ({
  useColorMode: () => useColorModeMock(),
}))

vi.mock('markstream-vue', () => ({
  default: defineComponent({
    props: { content: { type: String, default: '' } },
    template: '<div class="markdown-render">{{ content }}</div>',
  }),
}))

interface TestColorMode {
  resolvedMode: Ref<'light' | 'dark'>
  setColorMode: (mode: 'light' | 'dark') => void
}

let colorMode: TestColorMode

function mountAgentThreadView(): { wrapper: ReturnType<typeof mount>, colorMode: TestColorMode } {
  const wrapper = mount(AgentThreadView, {
    props: { assistantId: 'assistant-1', threadId: 'thread-1' },
    global: {
      plugins: [createI18n({ legacy: false, locale: 'en', messages: { en } })],
    },
  })
  return { wrapper, colorMode }
}

beforeEach(() => {
  const resolvedMode = ref<'light' | 'dark'>('light')
  colorMode = {
    resolvedMode,
    setColorMode: (mode) => { resolvedMode.value = mode },
  }
  useColorModeMock.mockReset()
  useColorModeMock.mockReturnValue(colorMode)
  vi.stubGlobal('localStorage', storageMock)
  vi.stubGlobal('matchMedia', vi.fn(() => ({
    matches: false,
    media: '(prefers-color-scheme: dark)',
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })))
})

afterEach(() => {
  document.documentElement.removeAttribute('data-bs-theme')
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  useStreamMock.mockReset()
  useColorModeMock.mockReset()
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
      interrupts: ref([{ id: 'interrupt-1', value: { question: 'Approve?' } }]),
      error: ref(undefined),
      isThreadLoading: ref(false),
      isLoading: computed(() => false),
    })

    const { wrapper } = mountAgentThreadView()

    expect(useStreamMock).toHaveBeenCalledWith(expect.objectContaining({
      assistantId: 'assistant-1',
      threadId: 'thread-1',
      fetch: managementAuthorizedFetch,
      callerOptions: { fetch: managementAuthorizedFetch },
    }))
    expect(wrapper.findAll('.markdown-render').map((block) => block.text()))
      .toEqual(['Question', 'Working', 'Answer'])
    expect(wrapper.findAll('.tool-activity')).toHaveLength(1)
    expect(wrapper.get('.tool-activity').text()).toContain('search')
    expect(wrapper.get('.tool-activity').text()).toContain('Finished')
    expect(wrapper.get('.tool-activity').text()).toContain('result')
    expect(wrapper.findAll('.agent-event-row').some((row) => row.text().includes('Approve?')))
      .toBe(true)
  })

  it('projects the resolved AdminLTE mode to the Markdown theme scope', async () => {
    useStreamMock.mockReturnValue({
      values: ref({ messages: [] }),
      messages: ref([new AIMessage({ id: 'ai-1', content: '`themed`' })]),
      toolCalls: ref([]),
      interrupts: ref([]),
      error: ref(undefined),
      isThreadLoading: ref(false),
      isLoading: computed(() => false),
    })

    const { wrapper, colorMode } = mountAgentThreadView()
    const themeScope = wrapper.get('.agent-thread-feed')

    expect(colorMode.resolvedMode.value).toBe('light')
    expect(themeScope.classes()).not.toContain('dark')

    colorMode.setColorMode('dark')
    await nextTick()

    expect(colorMode.resolvedMode.value).toBe('dark')
    expect(themeScope.classes()).toContain('dark')

    colorMode.setColorMode('light')
    await nextTick()

    expect(themeScope.classes()).not.toContain('dark')
  })

  it('renders the concrete Agent Server error instead of its transport envelope', () => {
    useStreamMock.mockReturnValue({
      values: ref({ messages: [] }),
      messages: ref([]),
      toolCalls: ref([]),
      interrupts: ref([]),
      error: ref(new Error(
        'agent-shell.runtime-error.v1:' + JSON.stringify({
          code: 'provider_request_failed',
          message: 'ProviderGatewayError: upstream returned 503',
          status_code: 502,
          source_exception_type: 'ProviderGatewayError',
          traceback: 'ProviderGatewayError: upstream returned 503',
        }),
      )),
      isThreadLoading: ref(false),
      isLoading: computed(() => false),
    })

    const { wrapper } = mountAgentThreadView()

    expect(wrapper.get('.agent-event-row--error').text())
      .toBe('ProviderGatewayError: upstream returned 503')
    expect(wrapper.text()).not.toContain('agent-shell.runtime-error.v1')
  })
})
