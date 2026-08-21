import { mount, type VueWrapper } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { describe, expect, it } from 'vitest'
import type { Component } from 'vue'

import {
  agentEventOutputAdapter,
  customToolAdapter,
  exceptionRetryAdapter,
  filesystemAdapter,
  filesystemPermissionsAdapter,
  modelAdapter,
  promptCachingAdapter,
  skillAdapter,
  summarizationAdapter,
  systemPromptAdapter,
  type ExceptionRetryDefaults,
  type FilesystemDefaults,
  type FilesystemPermissionsDefaults,
  workflowEventOutputAdapter,
  type PromptCachingDefaults,
  type SkillDefaults,
  type SummarizationDefaults,
} from '@/domain/blocks'
import { zhCN } from '@/locales/zh-CN'

import {
  CustomToolEditor,
  AgentEventOutputEditor,
  ExceptionRetryEditor,
  FilesystemEditor,
  FilesystemPermissionsEditor,
  ModelEditor,
  PromptCachingEditor,
  SkillEditor,
  SummarizationEditor,
  SystemPromptEditor,
  WorkflowEventOutputEditor,
} from './index'

const filesystemDefaults: FilesystemDefaults = {
  system_prompt: 'filesystem default',
  tool_token_limit_before_evict: 20_000,
  tools: [
    { name: 'ls', configurable: true, visible: true, default_description: 'ls default' },
    { name: 'read_file', configurable: false, visible: true, default_description: 'read default' },
    { name: 'write_file', configurable: true, visible: true, default_description: 'write default' },
    { name: 'edit_file', configurable: true, visible: true, default_description: 'edit default' },
    { name: 'delete', configurable: true, visible: false, default_description: 'delete default' },
    { name: 'glob', configurable: true, visible: true, default_description: 'glob default' },
    { name: 'grep', configurable: true, visible: true, default_description: 'grep default' },
    { name: 'execute', configurable: false, visible: false, default_description: 'execute default' },
  ],
}
const filesystemPermissionsDefaults: FilesystemPermissionsDefaults = {
  system_prompt: filesystemDefaults.system_prompt,
  tools: filesystemDefaults.tools,
}
const skillDefaults: SkillDefaults = {
  system_prompt: 'skill default',
  required_placeholders: ['{skills_locations}', '{skills_load_warnings}', '{skills_list}'],
}
const summarizationDefaults: SummarizationDefaults = {
  summary_prompt_default: '<role>default summary</role>',
  trigger: { type: 'auto', value: null },
  keep: { type: 'auto', value: null },
  truncate_args_enabled: true,
  truncate_args_trigger: { type: 'auto', value: null },
  truncate_args_keep: { type: 'auto', value: null },
  truncate_args_max_length: 2_000,
  truncate_args_text: '...(argument truncated)',
  trim_tokens_to_summarize: 4_000,
  summary_prompt_override: '',
}
const promptCachingDefaults: PromptCachingDefaults = {
  type: 'ephemeral',
  ttl: '5m',
  min_messages_to_cache: 0,
}
const exceptionRetryDefaults: ExceptionRetryDefaults = {
  strategies: ['provider_native', 'model_retry_middleware'],
  conditions: ['transport_error', 'timeout', 'rate_limit', 'server_error', 'authentication_error'],
  default_value: {
    strategy: 'provider_native',
    force_non_streaming: true,
    max_retries: 2,
    retry_on: ['transport_error', 'timeout', 'rate_limit', 'server_error'],
  },
}
const i18n = createI18n({
  legacy: false,
  locale: 'en',
  missingWarn: false,
  fallbackWarn: false,
  messages: { en: {} },
})

const localizedI18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  missingWarn: false,
  fallbackWarn: false,
  messages: { 'zh-CN': zhCN },
})

function mountEditor(component: Component, props: Record<string, unknown>): VueWrapper {
  return mount(component, {
    props,
    global: { plugins: [i18n] },
  })
}

describe('dedicated block editors', () => {
  it('renders exception retry as two unnested responsive strategy cards', () => {
    const editor = mount(ExceptionRetryEditor, {
      props: {
        modelValue: exceptionRetryAdapter.blank(exceptionRetryDefaults),
        defaults: exceptionRetryDefaults,
      },
      global: { plugins: [localizedI18n] },
    })
    const columns = editor.get('[data-editor="exception-retry"]').findAll(':scope > .col-12')
    const cards = columns.map((column) => column.get(':scope > .card'))

    expect(columns).toHaveLength(2)
    expect(editor.findAll('.card')).toHaveLength(2)
    expect(columns.every((column) => column.classes().includes('col-lg-6'))).toBe(true)
    expect(cards.every((card) => card.find('.card').exists() === false)).toBe(true)
    expect(cards.map((card) => card.get('.card-header').text())).toEqual([
      'Provider 原生重试',
      'LangChain ModelRetryMiddleware',
    ])
    expect(cards.every((card) => card.text().includes('强制非流式'))).toBe(true)
    expect(cards.every((card) => card.find('input[type="number"]').exists())).toBe(true)
    expect(editor.findAll('input[name="exception-retry-strategy"]')).toHaveLength(2)
  })

  it('round-trips filesystem permission rules and atomic overrides', () => {
    const apiValue = {
      id: 'permissions-id',
      name: 'Review policy',
      permissions: [
        { path: '/source/**', permission: 'read-only' as const },
        { path: '/private/**', permission: 'no-access' as const },
      ],
      system_prompt_override: { value: '' },
      tool_overrides: {
        write_file: { visible: false, description_override: 'Policy write tool' },
      },
    }

    const draft = filesystemPermissionsAdapter.fromApi(
      apiValue,
      filesystemPermissionsDefaults,
    )

    expect(draft.system_prompt_override_enabled).toBe(true)
    expect(draft.system_prompt_use_default).toBe(false)
    expect(draft.system_prompt_value).toBe('')
    expect(draft.tool_overrides.write_file?.override).toBe(true)
    expect(filesystemPermissionsAdapter.toPayload(
      draft,
      filesystemPermissionsDefaults,
    )).toEqual({
      name: 'Review policy',
      permissions: apiValue.permissions,
      system_prompt_override: { value: '' },
      tool_overrides: {
        write_file: { visible: false, description_override: 'Policy write tool' },
      },
    })
  })

  it('quick-loads paths from multiple filesystems without adding duplicates', async () => {
    const editor = mountEditor(FilesystemPermissionsEditor, {
      modelValue: filesystemPermissionsAdapter.blank(filesystemPermissionsDefaults),
      defaults: filesystemPermissionsDefaults,
      filesystems: [
        {
          id: 'filesystem-a',
          name: 'Filesystem A',
          mapped_directories: [{ virtual_path: '/workspace/', local_path: 'C:/workspace' }],
          virtual_directories: [{ virtual_path: '/drafts/', source_path: 'C:/drafts' }],
          virtual_files: [{ virtual_path: '/README.md', source_path: 'C:/README.md' }],
        },
        {
          id: 'filesystem-b',
          name: 'Filesystem B',
          mapped_directories: [{ virtual_path: '/other/', local_path: 'C:/other' }],
        },
      ],
    })
    const selects = editor.findAll('select')
    await selects[0]?.setValue('filesystem-a')
    await editor.get('[data-action="import-filesystem-paths"]').trigger('click')
    await editor.get('[data-action="import-filesystem-paths"]').trigger('click')

    expect(editor.findAll('[data-testid="filesystem-permission-row"]')).toHaveLength(3)
    expect(editor.findAll('[data-testid="filesystem-permission-row"] input').map(
      (input) => (input.element as HTMLInputElement).value,
    )).toEqual(['/workspace/**', '/drafts/**', '/README.md'])
    expect(editor.findAll('[data-testid="filesystem-permission-row"] select').map(
      (select) => (select.element as HTMLSelectElement).value,
    )).toEqual(['read-write', 'read-write', 'read-write'])

    await selects[0]?.setValue('filesystem-b')
    await editor.get('[data-action="import-filesystem-paths"]').trigger('click')
    expect(editor.findAll('[data-testid="filesystem-permission-row"]')).toHaveLength(4)
    expect(editor.findAll('[data-testid="filesystem-permission-row"] input').at(-1)?.element)
      .toHaveProperty('value', '/other/**')

    await editor.findAll('[data-action="remove-filesystem-permission"]')[0]?.trigger('click')
    expect(editor.findAll('[data-testid="filesystem-permission-row"]')).toHaveLength(3)
  })

  it('keeps mapping labels product-facing and one add action available', async () => {
    const permissionsDraft = filesystemPermissionsAdapter.blank(filesystemPermissionsDefaults)
    permissionsDraft.permissions.push({ path: '/workspace/**', permission: 'read-write' })
    const permissions = mount(FilesystemPermissionsEditor, {
      props: {
        modelValue: permissionsDraft,
        defaults: filesystemPermissionsDefaults,
        filesystems: [],
      },
      global: { plugins: [localizedI18n] },
    })
    const permissionRow = permissions.get('[data-testid="filesystem-permission-row"]')
    expect(permissionRow.text()).not.toContain('permissions.0.path')
    expect(permissionRow.get('label[for="filesystem-permission-path-0"]').text()).toBe('路径')
    expect(permissions.findAll('[data-action="add-filesystem-permission"]')).toHaveLength(1)
    await permissions.get('[data-action="add-filesystem-permission"]').trigger('click')
    expect(permissions.findAll('[data-testid="filesystem-permission-row"]')).toHaveLength(2)

    const filesystemDraft = filesystemAdapter.blank(filesystemDefaults)
    filesystemDraft.mapped_directories.push({
      virtual_path: '/workspace',
      local_path: 'C:/workspace',
      path_origin: 'absolute',
      lifecycle_mode: 'fixed',
    })
    const filesystem = mount(FilesystemEditor, {
      props: { modelValue: filesystemDraft, defaults: filesystemDefaults },
      global: { plugins: [localizedI18n] },
    })
    expect(filesystem.get('#mapped-directory-path-origin-absolute-0').element).toHaveProperty('checked', true)
    expect(filesystem.get('#mapped-directory-lifecycle-fixed-0').element).toHaveProperty('checked', true)
    expect(filesystem.findAll('[data-action="add-mapped-directory"]')).toHaveLength(1)
    expect(filesystem.findAll('[data-action="add-virtual-directory"]')).toHaveLength(1)
    expect(filesystem.findAll('[data-action="add-virtual-file"]')).toHaveLength(1)
    const constraints = filesystem.get('[data-testid="filesystem-tool-constraints"]')
    expect(constraints.get('.card-title').text()).toBe('文件工具约束')
    expect(constraints.findAll('label')).toHaveLength(4)
    expect(constraints.findAll('input')).toHaveLength(4)
    expect(constraints.findAll('.input-group-text').map((unit) => unit.text())).toEqual([
      'tokens', 'tokens', '条', '秒',
    ])
    expect(constraints.find('[data-testid="filesystem-tool-card"]').exists()).toBe(false)
    expect(filesystem.findAll('[data-testid="filesystem-tool-card"]')).toHaveLength(
      filesystemDefaults.tools.length,
    )
    expect(filesystem.text()).not.toContain('内置文件工具')

  })

  it('loads configuration-owned Python package templates for both event output editors', async () => {
    const agentOutput = mount(AgentEventOutputEditor, {
      props: {
        modelValue: agentEventOutputAdapter.blank(),
        catalog: [{
          key: 'agent-default',
          format_version: 1,
          family: 'event-output',
          adapter: 'agent-event-output',
          name: 'Agent default',
          revision: 'agent-revision',
          files: [{ path: 'main.py', content: 'def output(event):\n    return ""\n', exists: true }],
        }],
      },
      global: { plugins: [localizedI18n] },
    })
    await agentOutput.get('select').setValue('agent-default')
    expect(agentOutput.emitted('update:modelValue')?.at(-1)?.[0]).toMatchObject({
      python_package_template: {
        key: 'agent-default',
        revision: 'agent-revision',
      },
    })

    const workflowOutput = mount(WorkflowEventOutputEditor, {
      props: {
        modelValue: workflowEventOutputAdapter.blank(),
        catalog: [{
          key: 'workflow-default',
          format_version: 1,
          family: 'event-output',
          adapter: 'workflow-event-output',
          name: 'Workflow default',
          revision: 'workflow-revision',
          files: [{ path: 'main.py', content: 'def output(event):\n    return ""\n', exists: true }],
        }],
      },
      global: { plugins: [localizedI18n] },
    })
    await workflowOutput.get('select').setValue('workflow-default')
    expect(workflowOutput.emitted('update:modelValue')?.at(-1)?.[0]).toMatchObject({
      python_package_template: {
        key: 'workflow-default',
        revision: 'workflow-revision',
      },
    })
  })

  it('emits model queries and resource refresh requests instead of calling APIs', async () => {
    const model = mountEditor(ModelEditor, { modelValue: modelAdapter.blank() })
    await model.get('[data-testid="model-fetch-group"]').trigger('submit')
    expect(model.emitted('fetch-models')?.[0]).toEqual([{
      provider: 'openai', baseUrl: '', credential: '', blockId: '',
    }])

    const tools = mountEditor(CustomToolEditor, { modelValue: customToolAdapter.blank() })
    await tools.get('button').trigger('click')
    expect(tools.emitted('refresh')).toHaveLength(1)
  })

  it('renders all three LangChain model request settings with their distinct input forms', () => {
    const editor = mount(ModelEditor, {
      props: { modelValue: modelAdapter.blank() },
      global: { plugins: [localizedI18n] },
    })
    const settings = editor.findAll('[data-request-setting]')

    expect(settings.map((field) => field.attributes('data-request-setting'))).toEqual([
      'tool_choice',
      'response_format',
      'model_settings',
    ])
    expect(settings[0]?.find('input[list="tool-choice-options"]').exists()).toBe(true)
    expect(settings[1]?.find('textarea').exists()).toBe(true)
    expect(settings[2]?.find('textarea').exists()).toBe(true)
  })

  it('selects OpenAI-compatible Chat Completions by default and can opt into Responses', async () => {
    const editor = mountEditor(ModelEditor, { modelValue: modelAdapter.blank() })
    const connectionType = editor.get('[data-testid="openai-connection-type"]')

    expect((connectionType.element as HTMLSelectElement).value).toBe('compatible')
    await connectionType.setValue('responses')
    expect(editor.emitted('update:modelValue')?.at(-1)?.[0]).toMatchObject({
      provider_settings: { use_responses_api: true },
    })
  })

  it('emits an updated draft when a visible field changes', async () => {
    const editor = mountEditor(SystemPromptEditor, { modelValue: systemPromptAdapter.blank() })
    expect(editor.get('.card-header').text()).toBe('capabilities.system-prompt.label')
    await editor.get('textarea').setValue('System prompt')
    expect(editor.emitted('update:modelValue')?.at(-1)?.[0]).toMatchObject({
      system_prompt: 'System prompt',
    })
  })

  it('can disable the Skill system prompt without disabling the Skill component', async () => {
    const editor = mountEditor(SkillEditor, {
      modelValue: skillAdapter.blank(skillDefaults), defaults: skillDefaults,
    })
    const toggle = editor.get('[data-testid="skill-system-prompt-enabled"]')
    expect(editor.get('textarea').attributes('disabled')).toBeUndefined()

    await toggle.setValue(false)

    expect(editor.get('textarea').attributes('disabled')).toBeDefined()
    expect(editor.emitted('update:modelValue')?.at(-1)?.[0]).toMatchObject({
      system_prompt_enabled: false,
    })
  })

  it('keeps Template paths distinct while preventing duplicate private Skill names', async () => {
    const editor = mountEditor(SkillEditor, {
      modelValue: skillAdapter.blank(skillDefaults), defaults: skillDefaults,
      catalog: [
        { name: 'research', folder: 'research', template_path: 'team-a/research', description: 'First' },
        { name: 'research', folder: 'research', template_path: 'team-b/research', description: 'Second' },
      ],
    })
    const templateRows = editor.findAll('[data-testid="skill-template-item"]')
    expect(templateRows.map((row) => row.text())).toEqual([
      expect.stringContaining('team-a/research'),
      expect.stringContaining('team-b/research'),
    ])
    expect(templateRows[0]!.get('details').attributes('open')).toBeUndefined()
    await templateRows[0]!.get('button').trigger('click')

    expect(editor.findAll('[data-testid="private-skill-item"]')).toHaveLength(1)
    expect(templateRows[1]!.get('button').attributes('disabled')).toBeDefined()
    expect(editor.emitted('update:modelValue')?.at(-1)?.[0]).toMatchObject({
      skill_template_paths: ['team-a/research'],
    })
  })

  it('renders queried models as selectable cards', async () => {
    const editor = mountEditor(ModelEditor, {
      modelValue: modelAdapter.blank(),
      models: ['model-a', 'model-b'],
    })

    const cards = editor.findAll('[data-testid="model-option"]')
    expect(cards).toHaveLength(2)
    const fetchGroup = editor.get('[data-testid="model-fetch-group"]')
    expect(fetchGroup.element.tagName).toBe('FORM')
    const fetchButton = fetchGroup.get('[data-action="fetch-models"]')
    expect(fetchButton.attributes('type')).toBe('submit')
    await cards[1]?.trigger('click')

    const updatedCards = editor.findAll('[data-testid="model-option"]')
    expect(updatedCards[1]?.attributes('aria-pressed')).toBe('true')
    expect(editor.emitted('update:modelValue')?.at(-1)?.[0]).toMatchObject({ model: 'model-b' })
  })

  it('lists installed Providers and resets provider-specific settings on selection', async () => {
    const draft = modelAdapter.blank()
    draft.provider_settings = { max_completion_tokens: 200 }
    const editor = mountEditor(ModelEditor, {
      modelValue: draft,
      providers: [
        {
          provider: 'openai',
          package: 'langchain-openai',
          class_name: 'ChatOpenAI',
          installed: true,
          version: '1.4.1',
          documentation_url: 'https://docs.langchain.com/providers',
        },
        {
          provider: 'google_vertexai',
          package: 'langchain-google-vertexai',
          class_name: 'ChatVertexAI',
          installed: true,
          version: '3.2.4',
          documentation_url: 'https://docs.langchain.com/providers',
        },
      ],
    })
    const select = editor.get('[data-testid="model-provider-input"]')
    expect(select.element.tagName).toBe('SELECT')
    expect(select.findAll('option').map((option) => option.attributes('value'))).toEqual([
      '',
      'openai',
      'google_vertexai',
    ])
    expect(select.findAll('option').map((option) => option.text())).toEqual([
      'editors.model.providerPlaceholder',
      'langchain-openai',
      'langchain-google-vertexai',
    ])

    await select.setValue('google_vertexai')
    expect(editor.find('[data-testid="openai-connection-type"]').exists()).toBe(false)
    expect(editor.find('[data-provider-setting="max_completion_tokens"]').exists()).toBe(false)
    expect(editor.find('[data-provider-setting="max_tokens"]').exists()).toBe(true)
    expect(editor.find('[data-provider-setting="thinking_budget"]').exists()).toBe(true)
    expect(editor.emitted('update:modelValue')?.at(-1)?.[0]).toMatchObject({
      provider: 'google_vertexai',
      provider_settings: {},
    })
  })

  it('switches all summarization threshold units without carrying incompatible values', async () => {
    const editor = mountEditor(SummarizationEditor, {
      modelValue: summarizationAdapter.blank(summarizationDefaults),
      defaults: summarizationDefaults,
    })
    const selects = editor.findAll('[data-editor="summarization"] select')
    const summaryPrompt = editor.findAll('textarea').at(-1)

    expect(editor.find('#summarization-enabled').exists()).toBe(false)
    expect(editor.findAll('[data-summarization-section]')).toHaveLength(3)
    expect(editor.find('[data-summarization-section] [data-summarization-section]').exists()).toBe(false)
    expect(selects).toHaveLength(4)
    expect(editor.findAll('[data-editor="summarization"] input[type="number"]')).toHaveLength(2)
    expect(summaryPrompt?.element).toHaveProperty('value', summarizationDefaults.summary_prompt_default)
    const valueLabels = [
      'editors.summarization.triggerValue',
      'editors.summarization.keepValue',
      'editors.summarization.truncateTriggerValue',
      'editors.summarization.truncateKeepValue',
    ]
    for (const [index, select] of selects.entries()) {
      await select?.setValue('tokens')
      const valueInput = editor.get(`input[aria-label="${valueLabels[index]}"]`)
      expect(valueInput.element).toHaveProperty('value', '')
      expect(valueInput.attributes('step')).toBe('1')
    }
    await editor.get('#summarization-truncate-args-enabled').setValue(false)
    expect(editor.find('[data-summarization-section="tool-arguments"] .card-body').exists()).toBe(false)
    expect(editor.findAll('[data-editor="summarization"] select')).toHaveLength(2)
    await summaryPrompt?.setValue('custom summary prompt')
    await editor.get('[data-action="restore-summary-prompt"]').trigger('click')
    expect(summaryPrompt?.element).toHaveProperty('value', summarizationDefaults.summary_prompt_default)
  })

  it('edits Prompt Caching independently from summarization', async () => {
    const editor = mountEditor(PromptCachingEditor, {
      modelValue: promptCachingAdapter.blank(promptCachingDefaults),
      defaults: promptCachingDefaults,
    })

    expect(editor.find('[data-editor="summarization"]').exists()).toBe(false)
    await editor.findAll('select')[1]!.setValue('1h')
    expect(editor.emitted('update:modelValue')?.at(-1)?.[0]).toMatchObject({ ttl: '1h' })
  })

  it('applies a Custom Tool Python package template', async () => {
    const editor = mountEditor(CustomToolEditor, {
      modelValue: customToolAdapter.blank(),
      catalog: [
        {
          format_version: 1,
          key: 'word-count',
          family: 'tool',
          adapter: 'agent-tool',
          name: 'word-count',
          files: [
            { path: 'main.py', content: 'def create_tool():\n    return tool\n' },
            { path: 'requirements.txt', content: '' },
          ],
          revision: 'tool-revision',
        },
      ],
    })

    await editor.get('select').setValue('word-count')

    expect(editor.emitted('update:modelValue')?.at(-1)?.[0]).toMatchObject({
      python_package_template: {
        key: 'word-count',
        revision: 'tool-revision',
      },
    })
  })

  it('localizes structured resource scan errors without a string fallback', () => {
    const editor = mountEditor(CustomToolEditor, {
      modelValue: customToolAdapter.blank(),
      errors: {
        unsafe: {
          message_key: 'resource.error.pythonPackage.syntax',
          message_args: { line: 1 },
        },
      },
    })

    expect(editor.text()).toContain('resource.error.pythonPackage.syntax')
    expect(editor.text()).toContain('unsafe')
  })
})
