import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { describe, expect, it } from 'vitest'

import ToastHost from './ToastHost.vue'

function mountHost() {
  const i18n = createI18n({
    legacy: false,
    locale: 'en',
    messages: { en: { feedback: { dismiss: 'Dismiss notification' } } },
  })
  return mount(ToastHost, {
    props: {
      items: [
        { id: 'saved', tone: 'success', title: 'Saved', message: 'Configuration saved.' },
        { id: 'failed', tone: 'danger', title: 'Failed' },
      ],
    },
    global: { plugins: [i18n] },
  })
}

describe('ToastHost', () => {
  it('maps product feedback tones to the approved AdminLTE toasts', () => {
    const wrapper = mountHost()
    const toasts = wrapper.findAll('[role="alert"]')

    expect(wrapper.get('aside').classes()).toContain('toast-host')
    expect(wrapper.get('aside').classes()).not.toContain('top-0')
    expect(toasts).toHaveLength(2)
    expect(toasts[0]?.classes()).toContain('text-bg-success')
    expect(toasts[1]?.classes()).toContain('text-bg-danger')
    expect(wrapper.text()).toContain('Configuration saved.')
  })

  it('dismisses the exact queue item when the upstream toast closes', async () => {
    const wrapper = mountHost()

    await wrapper.findAll('.btn-close')[1]?.trigger('click')

    expect(wrapper.emitted('dismiss')).toEqual([['failed']])
  })
})
