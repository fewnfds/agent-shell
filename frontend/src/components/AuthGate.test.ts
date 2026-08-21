import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'

import { managementAuth, ManagementAuthCancelledError } from '@/api'

import AuthGate from './AuthGate.vue'

const messages = {
  auth: {
    eyebrow: 'Restricted',
    title: 'Management authentication',
    requiredMessage: 'Enter a management token.',
    invalidMessage: 'The credential was rejected.',
    tokenLabel: 'Management token',
    memoryOnlyHint: 'Held in memory only.',
    emptyToken: 'Enter a token.',
    cancel: 'Cancel',
    submit: 'Continue',
  },
}

function mountGate() {
  const i18n = createI18n({
    legacy: false,
    locale: 'en',
    messages: { en: messages },
  })
  return mount(AuthGate, {
    global: {
      plugins: [i18n],
    },
  })
}

afterEach(() => {
  managementAuth.clear()
  vi.unstubAllGlobals()
})

describe('AuthGate', () => {
  it('submits a challenge without persisting the token', async () => {
    const localSetItem = vi.fn()
    const sessionSetItem = vi.fn()
    vi.stubGlobal('localStorage', { getItem: vi.fn(() => null), setItem: localSetItem })
    vi.stubGlobal('sessionStorage', { getItem: vi.fn(() => null), setItem: sessionSetItem })
    const challenge = managementAuth.challenge('required')
    const wrapper = mountGate()
    await nextTick()

    const input = wrapper.get<HTMLInputElement>('#management-auth-token')
    await input.setValue('memory-only-secret')
    await wrapper.get('form').trigger('submit')
    await nextTick()

    await expect(challenge).resolves.toBe('memory-only-secret')
    expect(managementAuth.getSnapshot().open).toBe(false)
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(localSetItem).not.toHaveBeenCalled()
    expect(sessionSetItem).not.toHaveBeenCalled()
  })

  it('cancels the pending challenge', async () => {
    const challenge = managementAuth.challenge('required')
    const rejection = expect(challenge).rejects.toBeInstanceOf(ManagementAuthCancelledError)
    const wrapper = mountGate()
    await nextTick()
    await nextTick()

    await wrapper.get('.btn-warning').trigger('click')

    await rejection
    expect(managementAuth.getSnapshot().open).toBe(false)
  })
})
