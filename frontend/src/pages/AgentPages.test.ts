import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ManagementApiError } from '@/api'
import type { MainAgentProfile, SubagentProfile } from '@/domain/agents'

import {
  buttonByText,
  deferred,
  getToastNotify,
  mountMainAgentPage,
  mountSubagentPage,
  resetAgentPageTestState,
  service,
} from './agentPages.testSupport'

beforeEach(resetAgentPageTestState)

describe('agent authoring pages', () => {
  it('updates a MainAgent only after loading its explicit UUID', async () => {
    const api = service()
    const id = '00000000-0000-0000-0000-000000000010'
    const { wrapper } = await mountMainAgentPage(
      api,
      `/agents/main?id=${id}`,
    )
    expect(wrapper.text()).not.toContain(id)
    await buttonByText(wrapper, 'common.save').trigger('click')
    await flushPromises()

    expect(api.getMainAgent).toHaveBeenCalledWith(id)
    expect(api.updateMainAgent).toHaveBeenCalledWith(
      id,
      expect.objectContaining({ name: 'Shared name' }),
    )
    expect(api.createMainAgent).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('loads a new MainAgent when only the route query UUID changes', async () => {
    const id = '00000000-0000-0000-0000-000000000011'
    const api = service({
      getMainAgent: vi.fn(async (requestedId) => ({
        id: requestedId,
        name: 'Routed MainAgent',
        capability_refs: [],
        subagents: [],
      })),
    })
    const { router, wrapper } = await mountMainAgentPage(api)

    await router.push({ path: '/agents/main', query: { id } })
    await flushPromises()

    expect(api.getMainAgent).toHaveBeenCalledWith(id)
    await buttonByText(wrapper, 'common.save').trigger('click')
    await flushPromises()
    expect(api.updateMainAgent).toHaveBeenCalledWith(
      id,
      expect.objectContaining({ name: 'Routed MainAgent' }),
    )
    wrapper.unmount()
  })

  it('keeps the latest Agent route when an earlier query load finishes late', async () => {
    const firstMainAgentId = '00000000-0000-0000-0000-000000000031'
    const secondMainAgentId = '00000000-0000-0000-0000-000000000032'
    const firstMainAgent = deferred<MainAgentProfile>()
    const secondMainAgent = deferred<MainAgentProfile>()
    const getMainAgent = vi.fn((id: string) => (
      id === firstMainAgentId ? firstMainAgent.promise : secondMainAgent.promise
    ))
    const mainAgentApi = service({ getMainAgent })
    const mainAgentPage = await mountMainAgentPage(mainAgentApi)

    await mainAgentPage.router.push({ path: '/agents/main', query: { id: firstMainAgentId } })
    await mainAgentPage.router.push({ path: '/agents/main', query: { id: secondMainAgentId } })
    await flushPromises()
    const mainAgentSurface = mainAgentPage.wrapper.get('.configuration-loading-surface')
    expect(mainAgentSurface.attributes('data-loading')).toBe('true')
    expect(mainAgentSurface.attributes('inert')).toBeDefined()
    expect(mainAgentPage.wrapper.text()).not.toContain('common.loading')
    secondMainAgent.resolve({
      id: secondMainAgentId,
      name: 'Latest MainAgent',
      capability_refs: [],
      subagents: [],
    })
    await flushPromises()
    expect(mainAgentSurface.attributes('data-loading')).toBe('false')
    expect(mainAgentSurface.attributes('inert')).toBeUndefined()
    firstMainAgent.resolve({
      id: firstMainAgentId,
      name: 'Late MainAgent',
      capability_refs: [],
      subagents: [],
    })
    await flushPromises()
    await buttonByText(mainAgentPage.wrapper, 'common.save').trigger('click')
    await flushPromises()

    expect(mainAgentApi.updateMainAgent).toHaveBeenCalledWith(
      secondMainAgentId,
      expect.objectContaining({ name: 'Latest MainAgent' }),
    )
    mainAgentPage.wrapper.unmount()

    const firstSubagentId = '00000000-0000-0000-0000-000000000041'
    const secondSubagentId = '00000000-0000-0000-0000-000000000042'
    const firstSubagent = deferred<SubagentProfile>()
    const secondSubagent = deferred<SubagentProfile>()
    const getSubagent = vi.fn((id: string) => (
      id === firstSubagentId ? firstSubagent.promise : secondSubagent.promise
    ))
    const subagentApi = service({ getSubagent })
    const subagentPage = await mountSubagentPage(subagentApi)

    await subagentPage.router.push({ path: '/agents/subagents', query: { id: firstSubagentId } })
    await subagentPage.router.push({ path: '/agents/subagents', query: { id: secondSubagentId } })
    await flushPromises()
    const subagentSurface = subagentPage.wrapper.get('.configuration-loading-surface')
    expect(subagentSurface.attributes('data-loading')).toBe('true')
    expect(subagentSurface.attributes('inert')).toBeDefined()
    expect(subagentPage.wrapper.text()).not.toContain('common.loading')
    secondSubagent.resolve({
      id: secondSubagentId,
      component_name: 'Latest Subagent',
      name: 'latest_worker',
      description: 'Latest worker.',
      settings: { capability_overrides: [] },
    })
    await flushPromises()
    expect(subagentSurface.attributes('data-loading')).toBe('false')
    expect(subagentSurface.attributes('inert')).toBeUndefined()
    firstSubagent.resolve({
      id: firstSubagentId,
      component_name: 'Late Subagent',
      name: 'late_worker',
      description: 'Late worker.',
      settings: { capability_overrides: [] },
    })
    await flushPromises()
    await buttonByText(subagentPage.wrapper, 'common.save').trigger('click')
    await flushPromises()

    expect(subagentApi.updateSubagent).toHaveBeenCalledWith(
      secondSubagentId,
      expect.objectContaining({ component_name: 'Latest Subagent' }),
    )
    subagentPage.wrapper.unmount()
  })

  it('keeps the loaded MainAgent identity when selecting another record fails', async () => {
    const currentId = '00000000-0000-0000-0000-000000000010'
    const failedId = '00000000-0000-0000-0000-000000000099'
    const api = service({
      listMainAgents: vi.fn(async () => [
        {
          id: currentId,
          name: 'Current MainAgent',
          capability_refs: [],
          subagents: [],
        },
        {
          id: failedId,
          name: 'Unavailable MainAgent',
          capability_refs: [],
          subagents: [],
        },
      ]),
      getMainAgent: vi.fn(async (id) => {
        if (id === failedId) throw new Error('load failed')
        return {
          id: currentId,
          name: 'Current MainAgent',
          capability_refs: [],
          subagents: [],
        }
      }),
    })
    const { wrapper } = await mountMainAgentPage(
      api,
      `/agents/main?id=${currentId}`,
    )

    await wrapper.get('[data-testid="record-picker-select"]').setValue(failedId)
    await flushPromises()
    await buttonByText(wrapper, 'common.save').trigger('click')
    await flushPromises()

    expect(api.updateMainAgent).toHaveBeenCalledWith(
      currentId,
      expect.objectContaining({ name: 'Current MainAgent' }),
    )
    expect(api.updateMainAgent).not.toHaveBeenCalledWith(
      failedId,
      expect.anything(),
    )
    wrapper.unmount()
  })

  it('clears an old save error after the next MainAgent save succeeds', async () => {
    const createMainAgent = vi.fn()
      .mockRejectedValueOnce(new ManagementApiError({
        status: 500,
        code: 'old_save_failure',
        message: 'The first save failed.',
      }))
      .mockResolvedValueOnce({
        id: 'created-mainAgent',
        name: '',
        capability_refs: [],
        subagents: [],
      })
    const api = service({ createMainAgent })
    const { wrapper } = await mountMainAgentPage(api)

    await buttonByText(wrapper, 'common.save').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('old_save_failure')

    await buttonByText(wrapper, 'common.save').trigger('click')
    await flushPromises()
    expect(getToastNotify()).toHaveBeenCalledWith({
      tone: 'success',
      title: 'agents.feedback.saved',
    })
    expect(wrapper.find('[data-testid="page-feedback"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('old_save_failure')
    wrapper.unmount()
  })
})
