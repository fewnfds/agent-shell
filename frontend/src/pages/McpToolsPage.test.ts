import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import {
  managementApi,
  type McpTool,
  type SavedBlock,
} from '@/api'
import { useConfirmation } from '@/composables/useConfirmation'
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
      { path: '/workflows/mcp-tools', component: McpToolsPage },
      { path: '/workflows/mcp-tools/:id/editor', component: { template: '<div />' } },
    ],
  })
}

afterEach(() => {
  vi.restoreAllMocks()
  useConfirmation().cancel()
})

describe('McpToolsPage', () => {
  it('keeps MCP Tool metadata when a record change is cancelled', async () => {
    const first: McpTool = {
      id: 'mcp-tool-1', name: 'first_tool', description: 'First tool',
      python_schema_id: pythonSchema.id, enabled: false,
    }
    const second: McpTool = { ...first, id: 'mcp-tool-2', name: 'second_tool' }
    vi.spyOn(managementApi, 'getConfigurationOptions').mockResolvedValue({
      repository_id: '00000000-0000-4000-8000-000000000099',
      repository_revision: 1,
      components: { 'python-schema': [pythonSchema] },
      main_agents: [], mcp_tools: [first, second], subagents: [], workflows: [],
    })
    vi.spyOn(managementApi, 'getMcpTool').mockImplementation(async (id) => (
      id === first.id ? first : second
    ))
    vi.spyOn(managementApi, 'validateRepository').mockResolvedValue({
      valid: true, stage: 'repository_load', issues: [],
    })
    const router = testRouter()
    await router.push(`/workflows/mcp-tools?id=${first.id}`)
    await router.isReady()
    const wrapper = mount({ template: '<RouterView />' }, {
      global: { plugins: [i18n(), router] },
    })
    await flushPromises()

    await wrapper.get('#mcp-tool-description').setValue('Unsaved MCP Tool metadata')
    await wrapper.get('[data-testid="record-picker-select"]').setValue(second.id)
    expect(useConfirmation().current.value?.title).toBe(en.unsavedChanges.title)
    useConfirmation().cancel()
    await flushPromises()

    expect(router.currentRoute.value.query.id).toBe(first.id)
    expect(wrapper.get('[data-testid="record-picker-select"]').element).toHaveProperty('value', first.id)
    expect(wrapper.get('#mcp-tool-description').element)
      .toHaveProperty('value', 'Unsaved MCP Tool metadata')
    wrapper.unmount()
  })

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
