import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { expect, it } from 'vitest'

import { piiAdapter, type PiiDefaults, type PiiDraft } from '@/domain/blocks'
import { en } from '@/locales/en'
import PiiEditor from './PiiEditor.vue'

it('edits, orders and serializes PII rules without changing regex text', async () => {
  const defaults: PiiDefaults = {
    pii_types: ['email', 'credit_card', 'ip', 'mac_address', 'url'],
    strategies: ['block', 'redact', 'mask', 'hash'],
    default_value: { rules: [{ pii_type: 'email', strategy: 'redact', detector: null, apply_to_input: true, apply_to_output: false, apply_to_tool_results: false }] },
  }
  const draft = piiAdapter.blank(defaults)
  const wrapper = mount(PiiEditor, {
    props: { modelValue: draft, defaults },
    global: { plugins: [createI18n({ legacy: false, locale: 'en', messages: { en } })] },
  })
  expect(wrapper.get('label[for="pii-type-0"]').text()).toBe('PII type')
  expect(wrapper.get('label[for="pii-apply_to_input-0"]').text()).toBe('Apply to input')
  await wrapper.get('[data-action="add-rule"]').trigger('click')
  await wrapper.get('#pii-type-1').setValue('access_code')
  await wrapper.get('#pii-custom-detector-1').setValue(true)
  await wrapper.get('#pii-detector-1').setValue(' code-\\d+ ')
  await wrapper.get('#pii-apply_to_output-1').setValue(true)
  await wrapper.get('#pii-strategy-1').setValue('block')
  await wrapper.findAll('[data-action="move-up"]')[1]!.trigger('click')
  const emitted = wrapper.emitted('update:modelValue')!.at(-1)![0] as PiiDraft
  const payload = piiAdapter.toPayload({ ...emitted, name: 'PII' })
  expect(payload.rules.map((rule) => rule.pii_type)).toEqual(['access_code', 'email'])
  expect(payload.rules[0]).toEqual({ pii_type: 'access_code', detector: ' code-\\d+ ', strategy: 'block', apply_to_input: true, apply_to_output: true, apply_to_tool_results: false })
  expect(draft.rules).toHaveLength(1)
  expect(defaults.default_value.rules[0]!.detector).toBeNull()
  await wrapper.findAll('[data-action="delete-rule"]')[0]!.trigger('click')
  expect(wrapper.findAll('[data-testid="pii-rule"]')).toHaveLength(1)
  wrapper.unmount()
})
