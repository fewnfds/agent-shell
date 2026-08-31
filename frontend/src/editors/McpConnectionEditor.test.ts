import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { describe, expect, it } from 'vitest'

import { en } from '@/locales/en'

import McpConnectionEditor from './McpConnectionEditor.vue'

const i18n = () => createI18n({ legacy: false, locale: 'en', messages: { en } })

describe('MCP Connection editor', () => {
  it('clears transport-specific values when changing transport', async () => {
    const wrapper = mount(McpConnectionEditor, {
      props: {
        modelValue: {
          id: '11111111-1111-4111-8111-111111111111',
          name: 'Remote MCP',
          transport: 'http',
          url: 'https://example.test/mcp',
          values: [{
            name: 'Authorization',
            source: 'secret',
            value: '',
            status: 'masked',
          }],
        },
      },
      global: { plugins: [i18n()] },
    })

    await wrapper.get('#mcp-transport').setValue('stdio')

    expect(wrapper.emitted('update:modelValue')?.at(-1)?.[0]).toMatchObject({
      transport: 'stdio',
      values: [],
    })
  })
})
