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
      package_source: 'npm',
      package: '',
      version: '',
      values: [],
      installation: { status: 'not_installed' },
    })
  })

  it('emits installation only for a saved clean local package declaration', async () => {
    const wrapper = mount(McpConnectionEditor, {
      props: {
        canInstall: true,
        modelValue: {
          id: '11111111-1111-4111-8111-111111111111',
          name: 'Browser MCP',
          transport: 'stdio',
          package_source: 'npm',
          package: '@playwright/mcp',
          version: '0.0.1',
          entrypoint: '',
          args: [],
          cwd: '',
          values: [],
          installation: {
            status: 'not_installed',
            package_source: 'npm',
            package: '@playwright/mcp',
            version: '0.0.1',
          },
        },
      },
      global: { plugins: [i18n()] },
    })

    await wrapper.get('section:nth-of-type(3) button').trigger('click')

    expect(wrapper.emitted('install')).toHaveLength(1)
  })

  it('does not project an installed environment onto a changed entrypoint', async () => {
    const wrapper = mount(McpConnectionEditor, {
      props: {
        canInstall: false,
        modelValue: {
          id: '11111111-1111-4111-8111-111111111111',
          name: 'Browser MCP',
          transport: 'stdio',
          package_source: 'npm',
          package: '@playwright/mcp',
          version: '0.0.1',
          entrypoint: 'playwright-mcp',
          args: [],
          cwd: '',
          values: [],
          installation: {
            status: 'ready',
            package_source: 'npm',
            package: '@playwright/mcp',
            version: '0.0.1',
            entrypoint: 'playwright-mcp',
          },
        },
      },
      global: { plugins: [i18n()] },
    })

    await wrapper.get('#mcp-entrypoint').setValue('')

    expect(wrapper.text()).toContain('Not installed')
  })
})
