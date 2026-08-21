import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { describe, expect, it } from 'vitest'

import PaginationControls from './PaginationControls.vue'

const i18n = createI18n({
  legacy: false,
  locale: 'en',
  messages: {
    en: {
      common: {
        previousPage: 'Previous page',
        nextPage: 'Next page',
        pagination: {
          first: 'First',
          last: 'Last',
          pageLabel: 'Page {page}',
          pageSize: 'Page size',
          pageSizeOption: '{count} items',
          jump: 'Go to page',
          jumpAction: 'Go',
          numberedSummary: '{total} items, {start}-{end}, page {page} of {totalPages}',
        },
      },
    },
  },
})

describe('PaginationControls', () => {
  it('shows a clickable page window around the current page', async () => {
    const wrapper = mount(PaginationControls, {
      props: {
        id: 'history',
        page: 4,
        pageSize: 20,
        itemCount: 20,
        total: 200,
        totalPages: 10,
        ariaLabel: 'History pages',
      },
      global: { plugins: [i18n] },
    })

    expect(wrapper.findAll('.page-item').slice(2, -2).map(item => item.text())).toEqual([
      '1', '2', '3', '4', '5', '6', '7',
    ])
    expect(wrapper.get('.page-item.active').text()).toBe('4')
    expect(wrapper.get('.page-item.active').attributes('aria-current')).toBe('page')

    await wrapper.get('button[aria-label="Page 6"]').trigger('click')
    expect(wrapper.emitted('change')).toEqual([[6]])
  })

  it('shrinks the page window at the first and last page', async () => {
    const wrapper = mount(PaginationControls, {
      props: {
        id: 'events',
        page: 1,
        pageSize: 20,
        itemCount: 20,
        total: 200,
        totalPages: 10,
        ariaLabel: 'Event pages',
      },
      global: { plugins: [i18n] },
    })

    expect(wrapper.findAll('.page-item').slice(2, -2).map(item => item.text())).toEqual([
      '1', '2', '3', '4',
    ])

    await wrapper.setProps({ page: 10 })
    expect(wrapper.findAll('.page-item').slice(2, -2).map(item => item.text())).toEqual([
      '7', '8', '9', '10',
    ])
  })

  it('owns numbered navigation, direct jump, page size, and boundaries', async () => {
    const wrapper = mount(PaginationControls, {
      props: {
        id: 'history',
        page: 2,
        pageSize: 20,
        itemCount: 20,
        total: 95,
        totalPages: 5,
        ariaLabel: 'History pages',
      },
      global: { plugins: [i18n] },
    })

    expect(wrapper.text()).toContain('95 items, 21-40, page 2 of 5')
    await wrapper.findAll('button').find((button) => button.text() === 'Next page')!.trigger('click')
    expect(wrapper.emitted('change')).toContainEqual([3])

    await wrapper.get('input[type="number"]').setValue(5)
    await wrapper.get('.collection-page-jump').trigger('submit')
    expect(wrapper.emitted('change')).toContainEqual([5])

    await wrapper.get('select').setValue(50)
    expect(wrapper.emitted('pageSizeChange')).toEqual([[50]])

    await wrapper.setProps({ page: 5, itemCount: 15 })
    const next = wrapper.findAll('button').find((button) => button.text() === 'Next page')!
    expect(next.attributes('disabled')).toBeDefined()
  })

  it('does not emit an out-of-range numbered page', async () => {
    const wrapper = mount(PaginationControls, {
      props: {
        id: 'events',
        page: 2,
        pageSize: 50,
        itemCount: 12,
        total: 62,
        totalPages: 2,
        ariaLabel: 'Event pages',
      },
      global: { plugins: [i18n] },
    })

    expect(wrapper.find('.collection-page-jump').exists()).toBe(true)
    expect(wrapper.findAll('button').find((button) => button.text() === 'Next page')!
      .attributes('disabled')).toBeDefined()
    await wrapper.findAll('button').find((button) => button.text() === 'Previous page')!.trigger('click')
    expect(wrapper.emitted('change')).toEqual([[1]])
  })
})
