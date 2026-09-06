import { mount, type VueWrapper } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { describe, expect, it } from 'vitest'
import type { Component } from 'vue'

import {
  agentEventOutputAdapter,
  asyncSubagentAdapter,
  customToolAdapter,
  exceptionRetryAdapter,
  filesystemAdapter,
  filesystemToolsAdapter,
  modelAdapter,
  promptCachingAdapter,
  skillAdapter,
  subagentAdapter,
  summarizationAdapter,
  systemPromptAdapter,
  todoListAdapter,
  type AsyncSubagentDefaults,
  type ExceptionRetryDefaults,
  type FilesystemDefaults,
  type FilesystemToolsDefaults,
  workflowEventOutputAdapter,
  type PromptCachingDefaults,
  type SkillDefaults,
  type SubagentDefaults,
  type SummarizationDefaults,
  type TodoListDefaults,
} from '@/domain/blocks'
import { zhCN } from '@/locales/zh-CN'

import {
  CustomToolEditor,
  AgentEventOutputEditor,
  ExceptionRetryEditor,
  FilesystemEditor,
  FilesystemToolsEditor,
  ModelEditor,
  PromptCachingEditor,
  SkillEditor,
  SubagentCapabilityEditor,
  SummarizationEditor,
  SystemPromptEditor,
  TodoListEditor,
  WorkflowEventOutputEditor,
} from './index'
import AsyncSubagentEditor from './AsyncSubagentEditor.vue'

const filesystemDefaults: FilesystemDefaults = {
  system_prompt: 'filesystem default',
}
const filesystemToolsDefaults: FilesystemToolsDefaults = {
  tool_token_limit_before_evict: 20_000,
  tools: [
    { name: 'ls', configurable: true, visible: true, default_description: 'ls default' },
    { name: 'read_file', configurable: false, visible: true, default_description: 'read default' },
    { name: 'write_file', configurable: true, visible: true, default_description: 'write default' },
    { name: 'edit_file', configurable: true, visible: true, default_description: 'edit default' },
    { name: 'delete', configurable: true, visible: false, default_description: 'delete default' },
    { name: 'glob', configurable: true, visible: true, default_description: 'glob default' },
    { name: 'grep', configurable: true, visible: true, default_description: 'grep default' },
    { name: 'execute', configurable: true, visible: false, default_description: 'execute default' },
  ],
}
const skillDefaults: SkillDefaults = {
  system_prompt: 'skill default',
  required_placeholders: ['{skills_locations}', '{skills_load_warnings}', '{skills_list}'],
}
const subagentDefaults: SubagentDefaults = {
  system_prompt: 'subagent default prompt',
  tool_description: 'task default description',
}
const asyncSubagentDefaults: AsyncSubagentDefaults = {
  system_prompt: 'async subagent default prompt',
  tool_descriptions: {
    start_async_task: 'start default',
    check_async_task: 'check default',
    update_async_task: 'update default',
    cancel_async_task: 'cancel default',
    list_async_tasks: 'list default',
  },
}
const todoListDefaults: TodoListDefaults = {
  system_prompt: 'todo default prompt',
  tool_description: 'write_todos default description',
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

  it('switches between CompositeBackend and LocalShellBackend forms', async () => {
    const filesystemDraft = filesystemAdapter.blank(filesystemDefaults)
    filesystemDraft.mapped_directories.push({
      virtual_path: '/workspace/',
      local_path: 'C:/workspace',
      path_origin: 'absolute',
      lifecycle_mode: 'fixed',
      permission: 'read-write',
    })
    const filesystem = mount(FilesystemEditor, {
      props: { modelValue: filesystemDraft, defaults: filesystemDefaults },
      global: { plugins: [localizedI18n] },
    })
    expect(filesystem.findAll('[data-testid="mapped-directory-row"]')).toHaveLength(1)
    await filesystem.get('#filesystem-backend-local-shell').setValue(true)
    expect((filesystem.emitted('update:modelValue')?.at(-1)?.[0] as { backend_type: string }).backend_type).toBe('local-shell')
  })

  it('keeps a missing Skill package UUID visible until it is replaced or removed', () => {
    const filesystemDraft = filesystemAdapter.blank(filesystemDefaults)
    filesystemDraft.skill_package_id = '00000000-0000-4000-8000-000000000073'
    const filesystem = mount(FilesystemEditor, {
      props: { modelValue: filesystemDraft, defaults: filesystemDefaults, skillPackages: [] },
      global: { plugins: [localizedI18n] },
    })

    const selected = filesystem.get('#filesystem-skill-package')
    expect((selected.element as HTMLSelectElement).value).toBe(filesystemDraft.skill_package_id)
    expect(selected.text()).toContain(filesystemDraft.skill_package_id)
  })

  it('edits filesystem tool visibility separately from the backend', async () => {
    const tools = mount(FilesystemToolsEditor, {
      props: { modelValue: filesystemToolsAdapter.blank(filesystemToolsDefaults), defaults: filesystemToolsDefaults },
      global: { plugins: [localizedI18n] },
    })
    expect(tools.findAll('.list-group-item')).toHaveLength(filesystemToolsDefaults.tools.length)
    const execute = tools.get('#filesystem-tool-execute')
    expect((execute.element as HTMLInputElement).checked).toBe(false)
    await execute.setValue(true)
    expect((tools.emitted('update:modelValue')?.at(-1)?.[0] as { tool_configs: Record<string, { visible: boolean }> }).tool_configs.execute?.visible).toBe(true)
  })

  it('uses one list-group card for every built-in tool description set', () => {
    const scenarios = [
      {
        component: FilesystemToolsEditor,
        props: {
          modelValue: filesystemToolsAdapter.blank(filesystemToolsDefaults),
          defaults: filesystemToolsDefaults,
        },
        title: '文件系统工具',
        toolNames: filesystemToolsDefaults.tools.map((tool) => tool.name),
        switchCount: filesystemToolsDefaults.tools.filter((tool) => tool.configurable).length,
      },
      {
        component: TodoListEditor,
        props: {
          modelValue: todoListAdapter.blank(todoListDefaults),
          defaults: todoListDefaults,
        },
        title: '待办计划工具',
        toolNames: ['write_todos'],
        switchCount: 0,
      },
      {
        component: SubagentCapabilityEditor,
        props: {
          modelValue: subagentAdapter.blank(subagentDefaults),
          defaults: subagentDefaults,
        },
        title: '同步子代理工具',
        toolNames: ['task'],
        switchCount: 0,
      },
      {
        component: AsyncSubagentEditor,
        props: {
          modelValue: asyncSubagentAdapter.blank(asyncSubagentDefaults),
          defaults: asyncSubagentDefaults,
        },
        title: '异步子代理工具',
        toolNames: Object.keys(asyncSubagentDefaults.tool_descriptions),
        switchCount: 0,
      },
    ]

    for (const scenario of scenarios) {
      const editor = mount(scenario.component, {
        props: scenario.props,
        global: { plugins: [localizedI18n] },
      })
      const card = editor.get('[data-testid="tool-description-card"]')
      const items = card.findAll('[data-testid="tool-description-item"]')

      expect(card.get('.card-header').text()).toBe(scenario.title)
      expect(items).toHaveLength(scenario.toolNames.length)
      expect(items.map((item) => item.get('label').text())).toEqual(scenario.toolNames)
      expect(card.findAll('.form-switch')).toHaveLength(scenario.switchCount)
      expect(items.every((item) => item.get('[data-action="restore-default"]').classes().includes('ms-auto'))).toBe(true)
      expect(card.find('.card-body').exists()).toBe(false)
    }
  })

  it('keeps required tool variables concise and visible', () => {
    const synchronous = mount(SubagentCapabilityEditor, {
      props: {
        modelValue: subagentAdapter.blank(subagentDefaults),
        defaults: subagentDefaults,
      },
      global: { plugins: [localizedI18n] },
    })
    const asynchronous = mount(AsyncSubagentEditor, {
      props: {
        modelValue: asyncSubagentAdapter.blank(asyncSubagentDefaults),
        defaults: asyncSubagentDefaults,
      },
      global: { plugins: [localizedI18n] },
    })

    expect(synchronous.get('[data-testid="tool-description-card"] .form-text').text())
      .toBe('必要变量 {available_agents}')
    expect(asynchronous.get('[data-testid="tool-description-card"] .form-text').text())
      .toBe('必要变量 {available_agents}')
  })

  it('places system prompt controls in the card body with only the Skill switch', () => {
    const scenarios = [
      {
        component: FilesystemEditor,
        props: {
          modelValue: filesystemAdapter.blank(filesystemDefaults),
          defaults: filesystemDefaults,
        },
        title: '文件系统提示词',
        switchCount: 0,
      },
      {
        component: SkillEditor,
        props: {
          modelValue: skillAdapter.blank(skillDefaults),
          defaults: skillDefaults,
        },
        title: 'Skill 系统提示词',
        switchCount: 1,
      },
      {
        component: SubagentCapabilityEditor,
        props: {
          modelValue: subagentAdapter.blank(subagentDefaults),
          defaults: subagentDefaults,
        },
        title: '同步子代理系统提示词',
        switchCount: 0,
      },
      {
        component: AsyncSubagentEditor,
        props: {
          modelValue: asyncSubagentAdapter.blank(asyncSubagentDefaults),
          defaults: asyncSubagentDefaults,
        },
        title: '异步子代理系统提示词',
        switchCount: 0,
      },
      {
        component: TodoListEditor,
        props: {
          modelValue: todoListAdapter.blank(todoListDefaults),
          defaults: todoListDefaults,
        },
        title: '待办计划系统提示词',
        switchCount: 0,
      },
    ]

    for (const scenario of scenarios) {
      const editor = mount(scenario.component, {
        props: scenario.props,
        global: { plugins: [localizedI18n] },
      })
      const card = editor.get('[data-testid="system-prompt-card"]')

      expect(card.get('.card-header').text()).toBe(scenario.title)
      expect(card.findAll('.form-switch')).toHaveLength(scenario.switchCount)
      expect(card.get('.card-body > .d-flex [data-action="restore-default"]').classes()).toContain('ms-auto')
      expect(card.find('.card-header [data-action="restore-default"]').exists()).toBe(false)
    }
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

  it('renders model parameters in one card with the requested grid widths', () => {
    const editor = mount(ModelEditor, {
      props: { modelValue: modelAdapter.blank() },
      global: { plugins: [localizedI18n] },
    })
    const card = editor.get('[data-testid="model-parameters-card"]')
    const providerFields = card.findAll('[data-testid="provider-parameter-field"]')
    const settings = card.findAll('[data-request-setting]')

    expect(card.get('.card-title').text()).toBe('模型参数')
    expect(providerFields.length).toBeGreaterThan(0)
    expect(providerFields.every((field) => field.classes().includes('col-md-4'))).toBe(true)
    expect(settings.map((field) => field.attributes('data-request-setting'))).toEqual([
      'tool_choice',
      'response_format',
      'model_settings',
    ])
    expect(settings[0]?.classes()).toContain('col-md-4')
    expect(settings[1]?.classes()).toContain('col-md-6')
    expect(settings[2]?.classes()).toContain('col-md-6')
    expect(settings[0]?.find('input[list="tool-choice-options"]').exists()).toBe(true)
    expect(settings[1]?.find('textarea').exists()).toBe(true)
    expect(settings[2]?.find('textarea').exists()).toBe(true)
  })

  it('labels the default stream settings as Default', () => {
    const editor = mount(ModelEditor, {
      props: { modelValue: modelAdapter.blank() },
      global: { plugins: [localizedI18n] },
    })

    for (const key of ['stream_usage', 'streaming', 'logprobs']) {
      expect(editor.get(`[data-provider-setting="${key}"] option`).text()).toBe('默认')
    }
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

  it('keeps Template paths distinct while preventing duplicate packaged Skill names', async () => {
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

  it('lists installed Providers and applies supported Provider defaults on selection', async () => {
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
          provider: 'deepseek',
          package: 'langchain-deepseek',
          class_name: 'ChatDeepSeek',
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
      'deepseek',
      'google_vertexai',
    ])
    expect(select.findAll('option').map((option) => option.text())).toEqual([
      'editors.model.providerPlaceholder',
      'langchain-openai',
      'langchain-deepseek',
      'langchain-google-vertexai',
    ])

    await select.setValue('deepseek')
    expect(editor.emitted('update:modelValue')?.at(-1)?.[0]).toMatchObject({
      provider: 'deepseek',
      provider_settings: {
        temperature: 1,
        top_p: 1,
        presence_penalty: 0,
        frequency_penalty: 0,
      },
    })

    await select.setValue('google_vertexai')
    expect(editor.find('[data-testid="openai-connection-type"]').exists()).toBe(false)
    expect(editor.find('[data-provider-setting="max_completion_tokens"]').exists()).toBe(false)
    expect(editor.find('[data-provider-setting="max_tokens"]').exists()).toBe(true)
    expect(editor.find('[data-provider-setting="thinking_budget"]').exists()).toBe(true)
    expect(editor.emitted('update:modelValue')?.at(-1)?.[0]).toMatchObject({
      provider: 'google_vertexai',
      provider_settings: {},
    })

    await select.setValue('openai')
    expect(editor.emitted('update:modelValue')?.at(-1)?.[0]).toMatchObject({
      provider: 'openai',
      provider_settings: {
        temperature: 1,
        top_p: 1,
        presence_penalty: 0,
        frequency_penalty: 0,
      },
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
