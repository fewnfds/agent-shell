import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import {
  managementApi,
  type McpTool,
  type SavedBlock,
} from '@/api'
import { en } from '@/locales/en'

import McpToolsPage from './McpToolsPage.vue'

const pythonSchema: SavedBlock = {
  id: 'python-schema-1',
  name: 'Echo state',
}

function i18n() {
  return createI18n({ legacy: false, locale: 'en', messages: { en } })
}

function testRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/workflows/mcp-tools', component: { template: '<div />' } },
      { path: '/workflows/mcp-tools/:id/editor', component: { template: '<div />' } },
    ],
  })
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('McpToolsPage', () => {
  it('selects a Python Schema component and saves it with the MCP Tool', async () => {
    vi.spyOn(managementApi, 'getConfigurationOptions').mockResolvedValue({
      repository_id: '00000000-0000-4000-8000-000000000099',
      repository_revision: 1,
      components: {
        'python-schema': [pythonSchema],
      },
      main_agents: [],
      mcp_tools: [],
      subagents: [],
      workflows: [],
    })
    vi.spyOn(managementApi, 'validateRepository').mockResolvedValue({
      valid: true,
      stage: 'repository_load',
      issues: [],
    })
    const created: McpTool = {
      id: 'mcp-tool-1',
      name: 'echo_topic',
      description: 'Echo a topic.',
      python_schema_id: pythonSchema.id,
      enabled: false,
    }
    const create = vi.spyOn(managementApi, 'createMcpTool').mockResolvedValue(created)
    const router = testRouter()
    await router.push('/workflows/mcp-tools')
    await router.isReady()

    const wrapper = mount(McpToolsPage, {
      global: { plugins: [i18n(), router] },
    })
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === 'New')!.trigger('click')
    await wrapper.get('[data-field="record-name"]').setValue(created.name)
    await wrapper.get('#mcp-tool-description').setValue(created.description)
    await wrapper.get('#mcp-tool-python-schema').setValue(pythonSchema.id)
    await wrapper.findAll('button').find((button) => button.text() === 'Save')!.trigger('click')
    await flushPromises()

    expect(create).toHaveBeenCalledWith({
      name: created.name,
      description: created.description,
      python_schema_id: pythonSchema.id,
    })
    wrapper.unmount()
  })
})
