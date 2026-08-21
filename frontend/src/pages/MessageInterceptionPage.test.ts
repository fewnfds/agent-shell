import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import type { ManagementEvent, MessageInterception } from '@/api'
import { i18n } from '@/locales'

import MessageInterceptionPage from './MessageInterceptionPage.vue'

describe('MessageInterceptionPage', () => {
  it('toggles interception and refreshes the latest raw request from management events', async () => {
    i18n.global.locale.value = 'zh-CN'
    let emit: ((event: ManagementEvent) => void) | undefined
    const empty: MessageInterception = { enabled: false, latest: null }
    const captured: MessageInterception = {
      enabled: true,
      latest: {
        sequence: 1,
        intercepted_at: '2026-08-17T12:00:00.000+00:00',
        request_id: 'request-1',
        request_raw_json: '{"model":"workflow","messages":[{"role":"user","content":"raw"}]}',
      },
    }
    const api = {
      getMessageInterception: vi.fn()
        .mockResolvedValueOnce(empty)
        .mockResolvedValueOnce(captured),
      updateMessageInterception: vi.fn(async () => ({ enabled: true, latest: null })),
      watchApiServerEvents: vi.fn((onEvent: (event: ManagementEvent) => void) => {
        emit = onEvent
        onEvent({ type: 'event_stream_connected' })
        return () => undefined
      }),
    }
    const wrapper = mount(MessageInterceptionPage, {
      props: { api },
      global: { plugins: [i18n] },
    })
    await flushPromises()

    const toggle = wrapper.get('#message-interception-enabled')
    expect((toggle.element as HTMLInputElement).checked).toBe(false)
    await toggle.setValue(true)
    await flushPromises()
    expect(api.updateMessageInterception).toHaveBeenCalledWith(true)

    emit?.({ type: 'message_intercepted', sequence: 1 })
    await flushPromises()

    const raw = wrapper.get('#message-interception-raw')
    expect((raw.element as HTMLTextAreaElement).value).toBe(
      captured.latest?.request_raw_json,
    )
    expect(raw.attributes('readonly')).toBeDefined()
    expect(wrapper.text()).toContain('request-1')
    wrapper.unmount()
  })

  it('keeps the latest message when an earlier refresh finishes last', async () => {
    i18n.global.locale.value = 'zh-CN'
    let emit: ((event: ManagementEvent) => void) | undefined
    let resolveInitial: ((value: MessageInterception) => void) | undefined
    const initial = new Promise<MessageInterception>((resolve) => {
      resolveInitial = resolve
    })
    const captured: MessageInterception = {
      enabled: true,
      latest: {
        sequence: 2,
        intercepted_at: '2026-08-17T12:00:01.000+00:00',
        request_id: 'request-2',
        request_raw_json: '{"model":"workflow","messages":[{"role":"user","content":"latest"}]}',
      },
    }
    const api = {
      getMessageInterception: vi.fn()
        .mockReturnValueOnce(initial)
        .mockResolvedValueOnce(captured),
      updateMessageInterception: vi.fn(),
      watchApiServerEvents: vi.fn((onEvent: (event: ManagementEvent) => void) => {
        emit = onEvent
        onEvent({ type: 'event_stream_connected' })
        return () => undefined
      }),
    }
    const wrapper = mount(MessageInterceptionPage, {
      props: { api },
      global: { plugins: [i18n] },
    })
    await flushPromises()

    emit?.({ type: 'message_intercepted', sequence: 2 })
    await flushPromises()
    resolveInitial?.({ enabled: false, latest: null })
    await flushPromises()

    expect((wrapper.get('#message-interception-raw').element as HTMLTextAreaElement).value).toBe(
      captured.latest?.request_raw_json,
    )
    wrapper.unmount()
  })
})
