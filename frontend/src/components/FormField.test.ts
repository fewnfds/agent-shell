import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { h } from 'vue'

import FormField from './FormField.vue'
import { i18n } from '@/locales'

describe('FormField', () => {
  it('resolves a top-level payload path through the shared field catalog', () => {
    i18n.global.locale.value = 'zh-CN'
    const wrapper = mount(FormField, {
      props: { fieldPath: 'name' },
      slots: { default: '<input name="name">' },
      global: { plugins: [i18n] },
    })

    expect(wrapper.get('.form-label').text()).toBe('配置名称')
    expect(wrapper.get('.form-label').classes()).not.toContain('font-monospace')
  })

  it('uses the nested Subagent field label without another hardcoded map', () => {
    i18n.global.locale.value = 'en'
    const wrapper = mount(FormField, {
      props: { fieldPath: 'subagents.0.name' },
      slots: { default: '<input name="subagent-name">' },
      global: { plugins: [i18n] },
    })

    expect(wrapper.get('.form-label').text()).toBe('Configuration name')
  })

  it('shows the exact payload key for a technical field', () => {
    i18n.global.locale.value = 'zh-CN'
    const wrapper = mount(FormField, {
      props: { fieldPath: 'max_tokens', technical: true },
      slots: { default: '<input name="max_tokens">' },
      global: { plugins: [i18n] },
    })

    expect(wrapper.get('.form-label').text()).toBe('max_tokens')
    expect(wrapper.get('.form-label').classes()).toContain('font-monospace')
  })

  it('shows the full payload path in debug locale', () => {
    i18n.global.locale.value = 'debug'
    const wrapper = mount(FormField, {
      props: { fieldPath: 'middlewares.0.source' },
      slots: { default: '<input name="source">' },
      global: { plugins: [i18n] },
    })

    expect(wrapper.get('.form-label').text()).toBe('middlewares.0.source')
    expect(wrapper.get('.form-label').classes()).toContain('font-monospace')
  })

  it('associates the label, help and error with an identified control', () => {
    i18n.global.locale.value = 'en'
    const wrapper = mount(FormField, {
      props: {
        controlId: 'timeout',
        error: 'Choose a valid timeout.',
        fieldPath: 'timeout',
        hint: 'Measured in seconds.',
      },
      slots: {
        default: ({ describedBy }: { describedBy?: string }) => h('input', {
          id: 'timeout',
          'aria-describedby': describedBy,
        }),
      },
      global: { plugins: [i18n] },
    })

    expect(wrapper.get('label').attributes('for')).toBe('timeout')
    expect(wrapper.get('input').attributes('aria-describedby')).toBe('timeout-help timeout-error')
    expect(wrapper.get('[data-ui-slot="help"]').attributes('id')).toBe('timeout-help')
    expect(wrapper.get('[data-ui-slot="error"]').attributes('id')).toBe('timeout-error')
  })
})
