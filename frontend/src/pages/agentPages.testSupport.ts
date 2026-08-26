import { flushPromises, mount } from '@vue/test-utils'
import { vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import type {
  AgentAuthoringService,
  CapabilityManifest,
  MainAgentProfile,
  SubagentProfile,
  ValidationReport,
} from '@/domain/agents'

import MainAgentPage from './MainAgentPage.vue'
import SubagentPage from './SubagentPage.vue'

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

const validReport: ValidationReport = {
  valid: true,
  stage: 'draft_validation',
  issues: [],
}

export function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((accept) => {
    resolve = accept
  })
  return { promise, resolve }
}

export const modelManifest: CapabilityManifest = {
  type: 'model',
  terminology_key: 'model',
  label: 'Model',
  order: 1,
  icon_key: 'bot',
  editor_key: 'model',
  subagent_overrideable: true,
  required: true,
  subagent_policy: 'inherit',
  tool_names: [],
}

export const promptManifest: CapabilityManifest = {
  ...modelManifest,
  type: 'system-prompt',
  terminology_key: 'system-prompt',
  order: 2,
  required: false,
}

export const filesystemManifest: CapabilityManifest = {
  ...modelManifest,
  type: 'filesystem',
  terminology_key: 'file-system',
  order: 3,
  subagent_overrideable: true,
  required: true,
  subagent_policy: 'inherit',
}

export const filesystemToolsManifest: CapabilityManifest = {
  ...modelManifest,
  type: 'filesystem-tools',
  terminology_key: 'filesystem-tools',
  order: 4,
  subagent_overrideable: true,
  required: true,
  subagent_policy: 'inherit',
}

export const middlewareManifest: CapabilityManifest = {
  ...modelManifest,
  type: 'custom-middleware',
  terminology_key: 'middleware',
  order: 8,
  subagent_overrideable: false,
  required: false,
  subagent_policy: 'force-remove',
}

export const toolManifest: CapabilityManifest = {
  ...modelManifest,
  type: 'custom-tool',
  terminology_key: 'custom-tool',
  order: 6,
  subagent_overrideable: false,
  required: false,
  subagent_policy: 'force-remove',
}

export const agentEventOutputManifest: CapabilityManifest = {
  ...modelManifest,
  type: 'agent-event-output',
  terminology_key: 'agent-event-output',
  order: 9,
  subagent_overrideable: false,
  subagent_policy: 'top-level-only',
}

export const subagentManifest: CapabilityManifest = {
  ...modelManifest,
  type: 'subagent',
  terminology_key: 'delegation',
  order: 10,
  subagent_overrideable: false,
  required: false,
  subagent_policy: 'top-level-only',
}

export function service(overrides: Partial<AgentAuthoringService> = {}): AgentAuthoringService {
  const mainAgent: MainAgentProfile = {
    id: '00000000-0000-0000-0000-000000000010',
    name: 'Shared name',
    capability_refs: [],
    tool_refs: [],
    middleware_refs: [],
    subagents: [],
  }
  const subagent: SubagentProfile = {
    id: '00000000-0000-0000-0000-000000000020',
    component_name: 'Worker component',
    name: 'worker',
    description: 'Handles delegated work.',
    settings: {
      capability_overrides: [],
      tool_refs: [],
      middleware_refs: [],
    },
  }
  const base: AgentAuthoringService = {
    getCatalog: vi.fn(async () => ({
      block_types: [modelManifest, promptManifest],
      workflow_component_types: [],
      editor_defaults: {},
    })),
    getConfigurationOptions: vi.fn(async () => ({
      repository_id: '00000000-0000-4000-8000-000000000099',
      repository_revision: 1,
      components: {
        model: [{ id: '00000000-0000-0000-0000-000000000001', name: 'model block' }],
        'system-prompt': [{ id: '00000000-0000-0000-0000-000000000002', name: 'system-prompt block' }],
        filesystem: [{ id: '00000000-0000-0000-0000-000000000002', name: 'filesystem block' }],
        'filesystem-tools': [{ id: '00000000-0000-0000-0000-000000000002', name: 'filesystem-tools block' }],
      },
      main_agents: [mainAgent],
      subagents: [subagent],
      workflows: [],
    })),
    getMainAgent: vi.fn(async () => mainAgent),
    createMainAgent: vi.fn(async (payload) => ({ ...mainAgent, ...payload, id: 'created-mainAgent' })),
    updateMainAgent: vi.fn(async (id, payload) => ({ ...mainAgent, ...payload, id })),
    copyMainAgent: vi.fn(async (_id, name) => ({ ...mainAgent, id: 'copied-mainAgent', name })),
    deleteMainAgent: vi.fn(async () => ({ ok: true })),
    getSubagent: vi.fn(async () => subagent),
    createSubagent: vi.fn(async (payload) => ({ ...subagent, ...payload, id: 'created-subagent' })),
    updateSubagent: vi.fn(async (id, payload) => ({ ...subagent, ...payload, id })),
    copySubagent: vi.fn(async (_id, componentName) => ({ ...subagent, id: 'copied-subagent', component_name: componentName })),
    deleteSubagent: vi.fn(async () => ({ ok: true })),
    validateDraft: vi.fn(async () => validReport),
  }
  return { ...base, ...overrides }
}

export function buttonByText(wrapper: ReturnType<typeof mount>, text: string) {
  const button = wrapper.findAll('button').find((item) => item.text() === text)
  if (!button) throw new Error(`Button not found: ${text}`)
  return button
}

export function resetAgentPageTestState() {
  toastNotify.mockReset()
}

export function getToastNotify() {
  return toastNotify
}

export async function mountMainAgentPage(
  api: AgentAuthoringService,
  path = '/agents/main',
) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/agents/main', component: MainAgentPage }],
  })
  await router.push(path)
  await router.isReady()
  const wrapper = mount(MainAgentPage, {
    props: { service: api },
    global: { plugins: [router] },
  })
  await flushPromises()
  return { router, wrapper }
}

export async function mountSubagentPage(
  api: AgentAuthoringService,
  path = '/agents/subagents',
) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/agents/subagents', component: SubagentPage }],
  })
  await router.push(path)
  await router.isReady()
  const wrapper = mount(SubagentPage, {
    props: { service: api },
    global: { plugins: [router] },
  })
  await flushPromises()
  return { router, wrapper }
}
