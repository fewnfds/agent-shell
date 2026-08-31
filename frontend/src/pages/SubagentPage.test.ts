import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  buttonByText,
  filesystemManifest,
  filesystemToolsManifest,
  middlewareManifest,
  modelManifest,
  mountMainAgentPage,
  mountSubagentPage,
  agentEventOutputManifest,
  promptManifest,
  resetAgentPageTestState,
  service,
  subagentManifest,
  toolManifest,
} from './agentPages.testSupport'

beforeEach(resetAgentPageTestState)

describe('Subagent authoring page', () => {
  it('orders independent Custom Tool references in three-column cards', async () => {
    const firstId = '00000000-0000-0000-0000-000000000061'
    const secondId = '00000000-0000-0000-0000-000000000062'
    const api = service({
      getCatalog: vi.fn(async () => ({
        block_types: [modelManifest, promptManifest, toolManifest],
        editor_defaults: {},
      })),
      getConfigurationOptions: vi.fn(async () => ({
        repository_id: '00000000-0000-4000-8000-000000000099',
        repository_revision: 1,
        components: {
          model: [{ id: '00000000-0000-0000-0000-000000000001', name: 'model block' }],
          'system-prompt': [{ id: '00000000-0000-0000-0000-000000000002', name: 'system-prompt block' }],
          'custom-tool': [{ id: firstId, name: 'First Tool' }, { id: secondId, name: 'Second Tool' }],
        },
        main_agents: [],
        subagents: [],
        workflows: [],
      })),
    })

    for (const mountPage of [mountMainAgentPage, mountSubagentPage]) {
      const { wrapper } = await mountPage(api)
      const add = wrapper.get('[data-action="add-tool-reference"]')
      await add.trigger('click')
      await add.trigger('click')
      const rows = wrapper.findAll('[data-testid="tool-reference-row"]')
      expect(rows).toHaveLength(2)
      expect(rows.every((row) => row.classes().includes('col-md-6'))).toBe(true)
      expect(rows.every((row) => row.classes().includes('col-lg-4'))).toBe(true)
      await rows[0]!.get('[data-testid="tool-reference"]').setValue(firstId)
      await rows[1]!.get('[data-testid="tool-reference"]').setValue(secondId)
      await rows[0]!.get('[data-action="move-tool-reference-down"]').trigger('click')
      await buttonByText(wrapper, 'common.save').trigger('click')
      await flushPromises()
      wrapper.unmount()
    }

    expect(api.createMainAgent).toHaveBeenCalledWith(expect.objectContaining({
      tool_refs: [{ tool_id: secondId }, { tool_id: firstId }],
    }))
    expect(api.createSubagent).toHaveBeenCalledWith(expect.objectContaining({
      settings: expect.objectContaining({
        tool_refs: [{ tool_id: secondId }, { tool_id: firstId }],
      }),
    }))
  })

  it('keeps missing capability and ordered-reference UUIDs selectable for repair', async () => {
    const missingModelId = '00000000-0000-4000-8000-000000000075'
    const missingToolId = '00000000-0000-4000-8000-000000000076'
    const mainAgent = {
      id: '00000000-0000-4000-8000-000000000077',
      name: 'Broken Main Agent',
      capability_refs: [{ type: 'model' as const, block_id: missingModelId }],
      tool_refs: [{ tool_id: missingToolId }],
      middleware_refs: [],
      subagents: [],
    }
    const subagent = {
      id: '00000000-0000-4000-8000-000000000078',
      component_name: 'Broken Subagent',
      name: 'broken_worker',
      description: 'Exercises repair controls.',
      settings: {
        capability_overrides: [{ type: 'model' as const, mode: 'replace' as const, block_id: missingModelId }],
        tool_refs: [{ tool_id: missingToolId }],
        middleware_refs: [],
      },
    }
    const api = service({
      getCatalog: vi.fn(async () => ({
        block_types: [modelManifest, toolManifest],
        workflow_component_types: [],
        editor_defaults: {},
      })),
      getConfigurationOptions: vi.fn(async () => ({
        repository_id: '00000000-0000-4000-8000-000000000099',
        repository_revision: 1,
        components: { model: [], 'custom-tool': [] },
        main_agents: [mainAgent],
        subagents: [subagent],
        workflows: [],
      })),
      getMainAgent: vi.fn(async () => mainAgent),
      getSubagent: vi.fn(async () => subagent),
    })

    const main = await mountMainAgentPage(api, `/agents/main?id=${mainAgent.id}`)
    expect((main.wrapper.get('#main-agent-capability-model').element as HTMLSelectElement).value).toBe(missingModelId)
    expect(main.wrapper.get(`#main-agent-capability-model option[value="${missingModelId}"]`).attributes('disabled')).toBeDefined()
    expect((main.wrapper.get('[data-testid="tool-reference"]').element as HTMLSelectElement).value).toBe(missingToolId)
    expect(main.wrapper.get(`[data-testid="tool-reference"] option[value="${missingToolId}"]`).attributes('disabled')).toBeDefined()
    main.wrapper.unmount()

    const sub = await mountSubagentPage(api, `/agents/subagents?id=${subagent.id}`)
    expect((sub.wrapper.get('[data-testid="subagent-capability-model"]').element as HTMLSelectElement).value).toBe(missingModelId)
    expect(sub.wrapper.get(`[data-testid="subagent-capability-model"] option[value="${missingModelId}"]`).attributes('disabled')).toBeDefined()
    expect((sub.wrapper.get('[data-testid="tool-reference"]').element as HTMLSelectElement).value).toBe(missingToolId)
    sub.wrapper.unmount()
  })

  it('orders independent Middleware references for Main Agent and Subagent', async () => {
    const firstId = '00000000-0000-0000-0000-000000000071'
    const secondId = '00000000-0000-0000-0000-000000000072'
    const api = service({
      getCatalog: vi.fn(async () => ({
        block_types: [modelManifest, promptManifest, middlewareManifest],
        editor_defaults: {},
      })),
      getConfigurationOptions: vi.fn(async () => ({
        repository_id: '00000000-0000-4000-8000-000000000099',
        repository_revision: 1,
        components: {
          model: [{ id: '00000000-0000-0000-0000-000000000001', name: 'model block' }],
          'system-prompt': [{ id: '00000000-0000-0000-0000-000000000002', name: 'system-prompt block' }],
          'custom-middleware': [{ id: firstId, name: 'First' }, { id: secondId, name: 'Second' }],
        },
        main_agents: [],
        subagents: [],
        workflows: [],
      })),
    })

    for (const mountPage of [mountMainAgentPage, mountSubagentPage]) {
      const { wrapper } = await mountPage(api)
      const add = wrapper.get('[data-action="add-middleware-reference"]')
      await add.trigger('click')
      await add.trigger('click')
      const rows = wrapper.findAll('[data-testid="middleware-reference-row"]')
      expect(rows).toHaveLength(2)
      expect(rows.every((row) => row.classes().includes('col-md-6'))).toBe(true)
      expect(rows.every((row) => row.classes().includes('col-lg-4'))).toBe(true)
      await rows[0]!.get('[data-testid="middleware-reference"]').setValue(firstId)
      await rows[1]!.get('[data-testid="middleware-reference"]').setValue(secondId)
      await rows[0]!.get('[data-action="move-middleware-reference-down"]').trigger('click')
      await buttonByText(wrapper, 'common.save').trigger('click')
      await flushPromises()
      wrapper.unmount()
    }

    expect(api.createMainAgent).toHaveBeenCalledWith(expect.objectContaining({
      middleware_refs: [{ middleware_id: secondId }, { middleware_id: firstId }],
    }))
    expect(api.createSubagent).toHaveBeenCalledWith(expect.objectContaining({
      settings: expect.objectContaining({
        middleware_refs: [{ middleware_id: secondId }, { middleware_id: firstId }],
      }),
    }))
  })

  it('adds, selects, and removes ordered Subagent entity references', async () => {
    const api = service()
    const { wrapper } = await mountMainAgentPage(api)

    const addButton = wrapper.get('[data-action="add-subagent-reference"]')
    await addButton.trigger('click')
    await addButton.trigger('click')
    expect(wrapper.findAll('[data-testid="subagent-reference-row"]')).toHaveLength(2)
    expect(wrapper.findAll('[data-action="remove-subagent-reference"]')).toHaveLength(2)

    await wrapper.findAll('[data-action="remove-subagent-reference"]')[0]?.trigger('click')
    expect(wrapper.findAll('[data-testid="subagent-reference-row"]')).toHaveLength(1)
    const row = wrapper.get('[data-testid="subagent-reference-row"]')
    await row.get('[data-testid="subagent-reference"]').setValue(
      '00000000-0000-0000-0000-000000000020',
    )
    await flushPromises()
    await buttonByText(wrapper, 'common.save').trigger('click')
    await flushPromises()

    expect(api.createMainAgent).toHaveBeenCalledWith(expect.objectContaining({
      subagents: [{
        subagent_id: '00000000-0000-0000-0000-000000000020',
      }],
    }))
    wrapper.unmount()
  })

  it('renders one select per configurable Subagent capability', async () => {
    const api = service()
    const mainAgentPage = await mountMainAgentPage(api)
    const { wrapper } = await mountSubagentPage(api)

    expect(wrapper.text()).toContain('agents.subagent.roleName')
    expect(wrapper.findAll('[data-capability] input[type="radio"]')).toHaveLength(0)
    expect(wrapper.findAll('[data-capability] select')).toHaveLength(2)
    expect(mainAgentPage.wrapper.findAll('[data-testid^="main-agent-capability-filesystem"]')).toHaveLength(2)
    expect(wrapper.findAll('[data-testid^="subagent-capability-filesystem"]')).toHaveLength(2)

    mainAgentPage.wrapper.unmount()
    wrapper.unmount()
  })

  it('lets each Agent select its effective Filesystem', async () => {
    const api = service({
      getCatalog: vi.fn(async () => ({
        block_types: [
          modelManifest,
          promptManifest,
          filesystemManifest,
          filesystemToolsManifest,
          agentEventOutputManifest,
          subagentManifest,
        ],
        editor_defaults: {},
      })),
    })
    const { wrapper } = await mountSubagentPage(api)

    expect(wrapper.findAll('[data-capability]')).toHaveLength(3)
    const filesystem = wrapper.get('[data-testid="subagent-capability-filesystem"]')
    expect(filesystem.attributes('disabled')).toBeUndefined()
    expect((filesystem.element as HTMLSelectElement).value).toBe('__inherit__')
    expect(filesystem.find('option[value="__disabled__"]').exists()).toBe(false)
    expect(filesystem.text()).toContain('agents.override.mode.inherit')
    await filesystem.setValue('00000000-0000-0000-0000-000000000002')

    const tools = wrapper.get('[data-testid="subagent-capability-filesystem-tools"]')
    expect(tools.attributes('disabled')).toBeUndefined()
    expect((tools.element as HTMLSelectElement).value).toBe('__inherit__')
    expect(tools.find('option[value="__disabled__"]').exists()).toBe(false)
    await tools.setValue('00000000-0000-0000-0000-000000000002')

    const eventOutput = wrapper.get('[data-testid="subagent-capability-agent-event-output"]')
    expect(eventOutput.attributes('disabled')).toBeDefined()
    expect((eventOutput.element as HTMLSelectElement).value).toBe('__invalid__')
    expect(eventOutput.text()).toContain('agents.override.mode.invalid')

    expect(wrapper.find('[data-testid="subagent-capability-subagent"]').exists()).toBe(false)
    await buttonByText(wrapper, 'common.save').trigger('click')
    await flushPromises()
    expect(api.createSubagent).toHaveBeenCalledWith(expect.objectContaining({
      settings: expect.objectContaining({
        capability_overrides: expect.arrayContaining([
          {
            type: 'filesystem-tools',
            mode: 'replace',
            block_id: '00000000-0000-0000-0000-000000000002',
          },
        ]),
      }),
    }))
    expect(api.createSubagent).toHaveBeenCalledWith(expect.objectContaining({
      settings: expect.objectContaining({
        capability_overrides: expect.arrayContaining([
          {
            type: 'filesystem',
            mode: 'replace',
            block_id: '00000000-0000-0000-0000-000000000002',
          },
        ]),
      }),
    }))

    wrapper.unmount()
  })

  it('adds inherit to Subagent choices and stores disabled or replacement selections', async () => {
    const api = service()
    const { wrapper } = await mountSubagentPage(api)

    const modelSelect = wrapper.get('[data-testid="subagent-capability-model"]')
    const optionalSelect = wrapper.get('[data-testid="subagent-capability-system-prompt"]')
    expect(modelSelect.find('option[value="__inherit__"]').exists()).toBe(true)
    expect(modelSelect.find('option[value="__disabled__"]').exists()).toBe(false)
    expect(optionalSelect.find('option[value="__inherit__"]').exists()).toBe(true)
    expect(optionalSelect.find('option[value="__disabled__"]').exists()).toBe(true)

    await modelSelect.setValue('00000000-0000-0000-0000-000000000001')
    await optionalSelect.setValue('__disabled__')
    await flushPromises()
    await buttonByText(wrapper, 'common.save').trigger('click')
    await flushPromises()

    expect(api.createSubagent).toHaveBeenCalledWith({
      component_name: '',
      name: '',
      description: '',
      settings: {
        capability_overrides: [
          { type: 'model', mode: 'replace', block_id: '00000000-0000-0000-0000-000000000001' },
          { type: 'system-prompt', mode: 'disabled', block_id: '' },
        ],
        tool_refs: [],
        middleware_refs: [],
        mcp_refs: [],
      },
    })
    wrapper.unmount()
  })

  it('loads a Subagent entity from the configuration-library query UUID', async () => {
    const api = service()
    const id = '00000000-0000-0000-0000-000000000020'
    const { wrapper } = await mountSubagentPage(
      api,
      `/agents/subagents?id=${id}`,
    )

    expect(api.getSubagent).toHaveBeenCalledWith(id)
    await buttonByText(wrapper, 'common.save').trigger('click')
    await flushPromises()
    expect(api.updateSubagent).toHaveBeenCalledWith(
      id,
      expect.objectContaining({
        component_name: 'Worker component',
        name: 'worker',
      }),
    )
    wrapper.unmount()
  })
})
