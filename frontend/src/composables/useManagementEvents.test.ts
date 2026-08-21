import { mount } from '@vue/test-utils'
import { defineComponent, nextTick } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import type { ManagementEvent } from '@/api'

import {
  useManagementEvents,
  type ManagementEventSource,
} from './useManagementEvents'

describe('useManagementEvents', () => {
  it('owns connection state and stops the watcher with component scope', async () => {
    let emitEvent: ((event: ManagementEvent) => void) | undefined
    let emitError: ((error: unknown) => void) | undefined
    const stop = vi.fn()
    const source: ManagementEventSource = {
      watchApiServerEvents(onEvent, onError) {
        emitEvent = onEvent
        emitError = onError
        return stop
      },
    }
    const observed = vi.fn()
    const reconnected = vi.fn()
    const Harness = defineComponent({
      setup() {
        return useManagementEvents(observed, source, reconnected)
      },
      template: '<div />',
    })

    const wrapper = mount(Harness)
    emitEvent?.({ type: 'event_stream_connected' })
    await nextTick()
    expect(wrapper.vm.connected).toBe(true)
    expect(reconnected).not.toHaveBeenCalled()

    emitEvent?.({ type: 'history_changed' })
    expect(observed).toHaveBeenCalledWith({ type: 'history_changed' })

    emitError?.(new Error('offline'))
    await nextTick()
    expect(wrapper.vm.connected).toBe(false)
    expect(wrapper.vm.error).toBe('offline')

    emitEvent?.({ type: 'event_stream_connected' })
    await nextTick()
    expect(wrapper.vm.connected).toBe(true)
    expect(reconnected).toHaveBeenCalledOnce()

    wrapper.unmount()
    expect(stop).toHaveBeenCalledOnce()
  })
})
