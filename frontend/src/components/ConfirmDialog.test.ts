import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { nextTick } from 'vue'

import ConfirmDialog from './ConfirmDialog.vue'
import { i18n } from '@/locales'

function mountDialog() {
  return mount(ConfirmDialog, {
    props: {
      open: true,
      title: 'Delete configuration',
      description: 'This action cannot be undone.',
      confirmLabel: 'Delete',
      cancelLabel: 'Cancel',
      dangerous: true,
    },
    global: {
      plugins: [i18n],
    },
  })
}

describe('ConfirmDialog', () => {
  it('emits the explicit confirmation action', async () => {
    const wrapper = mountDialog()
    await nextTick()

    await wrapper.get('.modal-footer .btn-danger').trigger('click')

    expect(wrapper.emitted('confirm')).toHaveLength(1)
  })

  it('cancels when the standard dialog requests close', async () => {
    const wrapper = mountDialog()
    await nextTick()

    await wrapper.get('[data-action="close-modal"]').trigger('click')

    expect(wrapper.emitted('cancel')).toHaveLength(1)
  })
})
