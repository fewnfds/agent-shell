import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, ref } from 'vue'
import { createI18n } from 'vue-i18n'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { managementAuth } from '@/api'
import { en } from '@/locales/en'

import AgentThreadView from './AgentThreadView.vue'

const useColorModeMock = vi.hoisted(() => vi.fn())

vi.mock('@adminlte/vue', () => ({
  useColorMode: () => useColorModeMock(),
}))

vi.mock('markstream-vue', () => ({
  default: defineComponent({
    props: {
      content: { type: String, default: '' },
      final: { type: Boolean, default: false },
    },
    template: '<div class="markdown-render" :data-final="String(final)">{{ content }}</div>',
  }),
}))

interface OpenEventStream {
  channels: string[]
  controller: ReadableStreamDefaultController<Uint8Array>
}

const encoder = new TextEncoder()
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

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    headers: { 'content-type': 'application/json' },
  })
}

function enqueueEvent(stream: OpenEventStream, event: object): void {
  stream.controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`))
}

function protocolEvent(seq: number, method: string, data: object, namespace: string[] = []) {
  return {
    type: 'event',
    event_id: `event-${seq}`,
    seq,
    method,
    params: {
      namespace,
      node: namespace[0]?.split(':', 1)[0],
      timestamp: seq,
      data,
    },
  }
}

afterEach(() => {
  managementAuth.clear()
  delete (HTMLElement.prototype as HTMLElement & { scrollTo?: unknown }).scrollTo
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  useColorModeMock.mockReset()
})

describe('AgentThreadView live stream', () => {
  it('renders each official message delta before root terminal and then finalizes it', async () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
      configurable: true,
      value: vi.fn(),
    })
    const eventStreams: OpenEventStream[] = []
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname === '/threads/thread-1/state') {
        return jsonResponse({
          values: {
            messages: [{ type: 'human', id: 'human-1', content: 'Question' }],
          },
          next: ['model'],
          tasks: [],
          checkpoint: {
            thread_id: 'thread-1',
            checkpoint_ns: '',
            checkpoint_id: 'checkpoint-1',
          },
          metadata: { step: 0 },
        })
      }
      if (url.pathname === '/threads/thread-1/history') return jsonResponse([])
      if (url.pathname === '/threads/thread-1/stream/events') {
        const body = JSON.parse(String(init.body ?? '{}')) as { channels?: string[] }
        let controller: ReadableStreamDefaultController<Uint8Array> | undefined
        const stream = new ReadableStream<Uint8Array>({
          start(value) {
            controller = value
          },
        })
        eventStreams.push({ channels: body.channels ?? [], controller: controller! })
        return new Response(stream, { headers: { 'content-type': 'text/event-stream' } })
      }
      throw new Error(`Unexpected request: ${init.method ?? 'GET'} ${url.pathname}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('localStorage', storageMock)
    vi.stubGlobal('matchMedia', vi.fn(() => ({
      matches: false,
      media: '(prefers-color-scheme: dark)',
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })))
    managementAuth.submit('management-token')

    useColorModeMock.mockReturnValue({ resolvedMode: ref('light') })
    const wrapper = mount(AgentThreadView, {
      props: { assistantId: 'assistant-1', threadId: 'thread-1' },
      global: {
        plugins: [createI18n({ legacy: false, locale: 'en', messages: { en } })],
      },
    })

    await vi.waitFor(() => {
      expect(eventStreams.some((stream) => stream.channels.includes('messages'))).toBe(true)
    })
    const contentStream = eventStreams.find((stream) => stream.channels.includes('messages'))!
    const modelNamespace = ['model:invoke-1']

    enqueueEvent(contentStream, protocolEvent(1, 'lifecycle', { event: 'running' }))
    enqueueEvent(contentStream, protocolEvent(2, 'messages', {
      event: 'message-start',
      id: 'ai-live',
      role: 'ai',
      metadata: { run_id: 'model-run-1' },
    }, modelNamespace))
    enqueueEvent(contentStream, protocolEvent(3, 'messages', {
      event: 'content-block-start',
      index: 0,
      content: { type: 'text', text: '' },
    }, modelNamespace))
    enqueueEvent(contentStream, protocolEvent(4, 'messages', {
      event: 'content-block-delta',
      index: 0,
      delta: { type: 'text-delta', text: 'Hello' },
    }, modelNamespace))

    await vi.waitFor(() => {
      const blocks = wrapper.findAll('.markdown-render')
      expect(blocks.map((block) => block.text())).toEqual(['Question', 'Hello'])
      expect(blocks[1]?.attributes('data-final')).toBe('false')
    })

    enqueueEvent(contentStream, protocolEvent(5, 'messages', {
      event: 'content-block-delta',
      index: 0,
      delta: { type: 'text-delta', text: ' world' },
    }, modelNamespace))
    await vi.waitFor(() => {
      expect(wrapper.findAll('.markdown-render')[1]?.text()).toBe('Hello world')
    })

    enqueueEvent(contentStream, protocolEvent(6, 'messages', {
      event: 'content-block-finish',
      index: 0,
      content: { type: 'text', text: 'Hello world' },
    }, modelNamespace))
    enqueueEvent(contentStream, protocolEvent(7, 'messages', {
      event: 'message-finish',
      reason: 'stop',
      usage: { input_tokens: 1, output_tokens: 2, total_tokens: 3 },
    }, modelNamespace))
    await flushPromises()

    expect(wrapper.findAll('.markdown-render')[1]?.attributes('data-final')).toBe('false')
    enqueueEvent(contentStream, protocolEvent(8, 'lifecycle', { event: 'completed' }))
    await vi.waitFor(() => {
      const answer = wrapper.findAll('.markdown-render')[1]
      expect(answer?.text()).toBe('Hello world')
      expect(answer?.attributes('data-final')).toBe('true')
    })

    expect(fetchMock.mock.calls.some(([input]) => (
      new Headers((fetchMock.mock.calls.find(([candidate]) => candidate === input)?.[1] as RequestInit | undefined)?.headers)
        .get('Authorization') === 'Bearer management-token'
    ))).toBe(true)
    wrapper.unmount()
  })
})
