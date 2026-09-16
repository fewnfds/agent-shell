import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import type { ExternalAgent, ExternalAgentSummary } from '@/api'
import type { ExternalAgentAuthoringService } from '@/domain/externalAgent'

import ExternalAgentPage from './ExternalAgentPage.vue'

const toastNotify = vi.hoisted(() => vi.fn())

vi.mock('@/composables/useToasts', () => ({
  useToasts: () => ({ notify: toastNotify }),
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    locale: { value: 'en' },
    t: (key: string) => key,
    te: () => true,
  }),
}))

const summary: ExternalAgentSummary = {
  id: '00000000-0000-0000-0000-000000000030',
  name: 'Antigravity Reviewer',
  description: 'Reviews a diff and returns findings.',
  provider: 'antigravity-cli',
  agent_name: 'antigravity-reviewer',
}

const preset: ExternalAgent = {
  ...summary,
  system_prompt: 'Answer with findings only.',
  model: null,
  effort: 'low',
  print_timeout: '5m',
  output_format: 'stream-json',
  conversation: 'new',
  exclude_default_components: true,
  tools: ['view_file'],
  tool_guidance: 'Read files with absolute paths.',
  tool_permission: 'request-review',
  permission_allow: ['read_file(*)'],
  env: { AGY_PROBE: '1' },
}

function service(
  overrides: Partial<ExternalAgentAuthoringService> = {},
): ExternalAgentAuthoringService {
  const base: ExternalAgentAuthoringService = {
    listExternalAgents: vi.fn(async () => ({
      items: [summary],
      total: 1,
      repository_id: '00000000-0000-4000-8000-000000000099',
      repository_revision: 1,
    })),
    getExternalAgent: vi.fn(async () => preset),
    createExternalAgent: vi.fn(async (payload) => ({
      ...preset,
      ...payload,
      id: 'created-external-agent',
    })),
    updateExternalAgent: vi.fn(async (id, payload) => ({
      ...preset,
      ...payload,
      id,
    })),
    copyExternalAgent: vi.fn(async (_id, name) => ({
      ...preset,
      id: 'copied-external-agent',
      name,
    })),
    deleteExternalAgent: vi.fn(async () => ({ ok: true })),
    validateDraft: vi.fn(async () => ({
      valid: true,
      stage: 'draft_validation',
      issues: [],
    })),
    getExternalAgentRuntimeStatus: vi.fn(async () => ({
      provider: 'antigravity-cli',
      available: true,
      expected_path: 'H:/agent-shell/runtime/antigravity/1.2.4/agy.exe',
      version: '1.2.4',
      sha256: '0'.repeat(64),
      detail: '',
      guidance: '',
    })),
  }
  return { ...base, ...overrides }
}

async function mountPage(api: ExternalAgentAuthoringService) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/agents/external', component: ExternalAgentPage }],
  })
  await router.push('/agents/external')
  await router.isReady()
  const wrapper = mount(ExternalAgentPage, {
    props: { service: api },
    global: { plugins: [router] },
  })
  await flushPromises()
  return wrapper
}

function inputValue(wrapper: ReturnType<typeof mount>, testId: string): string {
  return (wrapper.get(`[data-testid="${testId}"]`).element as HTMLInputElement).value
}

describe('ExternalAgentPage', () => {
  beforeEach(() => {
    toastNotify.mockReset()
  })

  it('loads the preset list and renders the stored preset', async () => {
    const api = service()
    const wrapper = await mountPage(api)

    expect(api.listExternalAgents).toHaveBeenCalledTimes(1)
    await wrapper.get('[data-testid="record-picker-select"]').setValue(summary.id)
    await flushPromises()

    expect(api.getExternalAgent).toHaveBeenCalledWith(summary.id)
    expect(inputValue(wrapper, 'external-agent-agent-name')).toBe('antigravity-reviewer')
    expect(inputValue(wrapper, 'external-agent-print-timeout')).toBe('5m')
    expect(inputValue(wrapper, 'external-agent-model')).toBe('')
    expect(
      (wrapper.get('[data-testid="external-agent-provider"]').element as HTMLSelectElement)
        .options,
    ).toHaveLength(1)
    expect(
      (wrapper.get('[data-testid="external-agent-effort"]').element as HTMLSelectElement).value,
    ).toBe('low')
    expect(
      (wrapper.get('[data-testid="external-agent-conversation"]').element as HTMLSelectElement)
        .value,
    ).toBe('new')
    expect(
      (wrapper.get('[data-testid="external-agent-output-format"]').element as HTMLSelectElement)
        .value,
    ).toBe('stream-json')
    expect(
      (wrapper.get('[data-testid="external-agent-tool-view_file"]')
        .element as HTMLInputElement).checked,
    ).toBe(true)
  })

  it('creates a preset with the payload the CLI invocation consumes', async () => {
    const api = service({
      listExternalAgents: vi.fn(async () => ({
        items: [],
        total: 0,
        repository_id: '00000000-0000-4000-8000-000000000099',
        repository_revision: 1,
      })),
    })
    const wrapper = await mountPage(api)

    await wrapper.get('[data-field="record-name"]').setValue('Antigravity Reviewer')
    await wrapper.get('[data-testid="external-agent-description"]')
      .setValue('Reviews a diff.')
    await wrapper.get('[data-testid="external-agent-agent-name"]')
      .setValue('antigravity-reviewer')
    await wrapper.get('[data-testid="external-agent-system-prompt"]')
      .setValue('Answer with findings only.')
    await wrapper.get('[data-testid="external-agent-effort"]').setValue('medium')
    await wrapper.get('[data-testid="external-agent-conversation"]')
      .setValue('continue-latest')
    await wrapper.get('[data-testid="external-agent-tool-view_file"]').setValue(true)
    await wrapper.get('[data-testid="external-agent-permission-allow"]')
      .setValue('read_file(*)')
    await wrapper.get('[data-testid="external-agent-env"]').setValue('AGY_PROBE=1')

    const save = wrapper.findAll('button')
      .find((button) => button.text() === 'common.save')
    expect(save).toBeDefined()
    await save!.trigger('click')
    await flushPromises()

    expect(api.createExternalAgent).toHaveBeenCalledWith({
      name: 'Antigravity Reviewer',
      description: 'Reviews a diff.',
      provider: 'antigravity-cli',
      agent_name: 'antigravity-reviewer',
      system_prompt: 'Answer with findings only.',
      model: null,
      effort: 'medium',
      print_timeout: '5m',
      output_format: 'stream-json',
      conversation: 'continue-latest',
      exclude_default_components: true,
      tools: ['view_file'],
      tool_guidance: '',
      tool_permission: 'request-review',
      permission_allow: ['read_file(*)'],
      env: { AGY_PROBE: '1' },
    })
  })

  it('shows the pinned CLI placement guidance when the binary is missing', async () => {
    const api = service({
      getExternalAgentRuntimeStatus: vi.fn(async () => ({
        provider: 'antigravity-cli' as const,
        available: false,
        expected_path: 'H:/agent-shell/runtime/antigravity/1.2.4/agy.exe',
        version: '1.2.4',
        sha256: null,
        detail: 'The pinned Antigravity CLI executable is missing.',
        guidance: 'Copy it to that path.',
      })),
    })
    const wrapper = await mountPage(api)

    expect(api.getExternalAgentRuntimeStatus).toHaveBeenCalledTimes(1)
    expect(wrapper.get('[data-testid="external-agent-runtime"]').text())
      .toContain('Copy it to that path.')
  })
})
