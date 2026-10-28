import { enableAutoUnmount, flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { afterEach, describe, expect, it, vi } from 'vitest'

import ModalHost from './ModalHost.vue'

enableAutoUnmount(afterEach)

afterEach(() => {
  document.body.replaceChildren()
})

const closeActions = [
  ['header button', async (wrapper: VueWrapper) => wrapper.get('[data-action="close-modal"]').trigger('click')],
  ['Escape', async () => { document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })) }],
  ['backdrop', async (wrapper: VueWrapper) => wrapper.get('[role="dialog"]').trigger('mousedown')],
] as const

describe('ModalHost', () => {
  it.each(closeActions)('keeps the dialog open when its owner rejects a %s close request', async (_name, requestClose) => {
    const opener = document.createElement('button')
    document.body.append(opener)
    opener.focus()
    const onClose = vi.fn()
    const wrapper = mount(ModalHost, {
      attachTo: document.body,
      props: { open: true, title: 'Import connections', onClose },
      global: {
        plugins: [createI18n({
          legacy: false,
          locale: 'en',
          messages: { en: { common: { close: 'Close' } } },
        })],
      },
    })
    await flushPromises()
    const closeButton = wrapper.get('[data-action="close-modal"]').element
    expect(document.activeElement).toBe(closeButton)

    await requestClose(wrapper)
    await flushPromises()

    expect(onClose).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[role="dialog"]').exists()).toBe(true)
    expect(document.activeElement).toBe(closeButton)
    expect(document.body.classList.contains('modal-open')).toBe(true)

    await wrapper.setProps({ open: false })
    await flushPromises()

    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(document.activeElement).toBe(opener)
    expect(document.body.classList.contains('modal-open')).toBe(false)
  })
})
