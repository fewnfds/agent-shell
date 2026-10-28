import { mount, type VueWrapper } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { describe, expect, it } from 'vitest'
import type { Component } from 'vue'

import {
  agentEventOutputAdapter,
  customToolAdapter,
  exceptionRetryAdapter,
  filesystemAdapter,
  filesystemToolsAdapter,
  modelCallLimitAdapter,
  modelAdapter,
  skillAdapter,
  subagentAdapter,
  summarizationAdapter,
  systemPromptAdapter,
  todoListAdapter,
  toolCallLimitAdapter,
  type ExceptionRetryDefaults,
  type FilesystemDefaults,
  type FilesystemToolsDefaults,
  workflowEventOutputAdapter,
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
  ModelCallLimitEditor,
  SkillEditor,
  SubagentCapabilityEditor,
  SummarizationEditor,
  SystemPromptEditor,
  TodoListEditor,
  ToolCallLimitEditor,
  WorkflowEventOutputEditor,
} from './index'

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
  it('switches retry strategy and emits its editable policy', async () => {
    const editor = mountEditor(ExceptionRetryEditor, {
      modelValue: exceptionRetryAdapter.blank(exceptionRetryDefaults),
      defaults: exceptionRetryDefaults,
    })
    const provider = editor.get('[data-testid="retry-owner"] fieldset')
    const middleware = editor.get('[data-testid="middleware-policy"] fieldset')
    expect((provider.element as HTMLFieldSetElement).disabled).toBe(false)
    expect((middleware.element as HTMLFieldSetElement).disabled).toBe(true)

    await editor.get('#retry-strategy-model_retry_middleware').setValue(true)
    expect((provider.element as HTMLFieldSetElement).disabled).toBe(true)
    expect((middleware.element as HTMLFieldSetElement).disabled).toBe(false)
    await editor.get('#max-retries-model_retry_middleware').setValue('4')
    await editor.get('#retry-authentication_error').setValue(true)
    expect(editor.emitted('update:modelValue')?.at(-1)?.[0]).toMatchObject({
      strategy: 'model_retry_middleware',
      max_retries: 4,
      retry_on: ['transport_error', 'timeout', 'rate_limit', 'server_error', 'authentication_error'],
    })
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
    const mappedRow = filesystem.get('[data-testid="mapped-directory-row"] .row')
    expect(mappedRow.find('#mapped-directory-local-path-0').exists()).toBe(true)
    expect(mappedRow.find('#mapped-directory-path-origin-0').exists()).toBe(true)
    expect(mappedRow.find('#mapped-directory-virtual-path-0').exists()).toBe(true)
    expect(mappedRow.find('#mapped-directory-permission-0').exists()).toBe(true)
    expect(mappedRow.find('#mapped-directory-lifecycle-mode-0').exists()).toBe(true)
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

  it.each([
    {
      name: 'Filesystem', component: FilesystemToolsEditor,
      props: { modelValue: filesystemToolsAdapter.blank(filesystemToolsDefaults), defaults: filesystemToolsDefaults },
      changed: { tool_configs: { ls: { description_override: 'custom description' } } },
      restored: { tool_configs: { ls: { description_override: 'ls default' } } },
    },
    {
      name: 'Todo', component: TodoListEditor,
      props: { modelValue: todoListAdapter.blank(todoListDefaults), defaults: todoListDefaults },
      changed: { tool_description_override: 'custom description' },
      restored: { tool_description_override: 'write_todos default description' },
    },
    {
      name: 'Subagent', component: SubagentCapabilityEditor,
      props: { modelValue: subagentAdapter.blank(subagentDefaults), defaults: subagentDefaults },
      changed: { task_description_override: 'custom description' },
      restored: { task_description_override: 'task default description' },
    },
  ])('edits and restores the $name tool description', async ({ component, props, changed, restored }) => {
    const editor = mountEditor(component, props)
    const item = editor.get('[data-testid="tool-description-item"]')
    await item.get('textarea').setValue('custom description')
    expect(editor.emitted('update:modelValue')?.at(-1)?.[0]).toMatchObject(changed)
    await item.get('[data-action="restore-default"]').trigger('click')
    expect(editor.emitted('update:modelValue')?.at(-1)?.[0]).toMatchObject(restored)
  })

  it('keeps required tool variables concise and visible', () => {
    const synchronous = mount(SubagentCapabilityEditor, {
      props: {
        modelValue: subagentAdapter.blank(subagentDefaults),
        defaults: subagentDefaults,
      },
      global: { plugins: [localizedI18n] },
    })
    expect(synchronous.get('[data-testid="tool-description-card"] .form-text').text())
      .toBe('必要变量 {available_agents}')
  })

  it.each([
    {
      name: 'Filesystem', component: FilesystemEditor,
      props: { modelValue: filesystemAdapter.blank(filesystemDefaults), defaults: filesystemDefaults },
      field: 'system_prompt_override', value: 'filesystem default',
    },
    {
      name: 'Skill', component: SkillEditor,
      props: { modelValue: skillAdapter.blank(skillDefaults), defaults: skillDefaults },
      field: 'instruction_override', value: 'skill default',
    },
    {
      name: 'Subagent', component: SubagentCapabilityEditor,
      props: { modelValue: subagentAdapter.blank(subagentDefaults), defaults: subagentDefaults },
      field: 'instruction_override', value: 'subagent default prompt',
    },
    {
      name: 'Todo', component: TodoListEditor,
      props: { modelValue: todoListAdapter.blank(todoListDefaults), defaults: todoListDefaults },
      field: 'system_prompt_override', value: 'todo default prompt',
    },
  ])('edits and restores the $name system prompt', async ({ component, props, field, value }) => {
    const editor = mountEditor(component, props)
    const prompt = editor.get('[data-testid="system-prompt-card"]')
    await prompt.get('textarea').setValue('custom prompt')
    expect(editor.emitted('update:modelValue')?.at(-1)?.[0]).toMatchObject({ [field]: 'custom prompt' })
    await prompt.get('[data-action="restore-default"]').trigger('click')
    expect(editor.emitted('update:modelValue')?.at(-1)?.[0]).toMatchObject({ [field]: value })
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
      provider: 'openai', baseUrl: '', credential: '', blockId: '', apiVersion: '',
    }])

    const tools = mountEditor(CustomToolEditor, { modelValue: customToolAdapter.blank() })
    await tools.get('button').trigger('click')
    expect(tools.emitted('refresh')).toHaveLength(1)
  })

  it('emits tool choice and structured model request settings without altering JSON text', async () => {
    const editor = mountEditor(ModelEditor, { modelValue: modelAdapter.blank() })
    const responseFormat = '{"type":"object","properties":{"answer":{"type":"string"}}}'
    const modelSettings = '{"parallel_tool_calls":false}'
    await editor.get('[data-request-setting="tool_choice"] input').setValue('required')
    await editor.get('[data-request-setting="response_format"] textarea').setValue(responseFormat)
    await editor.get('[data-request-setting="model_settings"] textarea').setValue(modelSettings)
    expect(editor.emitted('update:modelValue')?.at(-1)?.[0]).toMatchObject({
      tool_choice: 'required', response_format: responseFormat, model_settings: modelSettings,
    })
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
          provider: 'google_genai',
          package: 'langchain-google-genai',
          class_name: 'ChatGoogleGenerativeAI',
          installed: true,
          version: '4.4.0',
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
      'google_genai',
    ])
    expect(select.findAll('option').map((option) => option.text())).toEqual([
      'editors.model.providerPlaceholder',
      'langchain-openai',
      'langchain-deepseek',
      'langchain-google-genai',
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
    expect(editor.find('[data-testid="openai-connection-type"]').exists()).toBe(false)

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

    await select.setValue('google_genai')
    expect(editor.get('[data-provider-setting="api_version"]').exists()).toBe(true)
    expect(editor.get('[data-provider-setting="top_k"]').exists()).toBe(true)
    expect(editor.get('[data-provider-setting="reasoning_effort"] option[value="high"]').exists()).toBe(true)
    expect(editor.find('[data-provider-setting="max_completion_tokens"]').exists()).toBe(false)
    expect(editor.find('[data-provider-setting="use_responses_api"]').exists()).toBe(false)
  })

  it('queries the model catalog with the Gemini connection api version', async () => {
    const draft = modelAdapter.blank()
    draft.provider = 'google_genai'
    const editor = mountEditor(ModelEditor, { modelValue: draft })

    await editor.get('[data-provider-setting="api_version"]').setValue('v1')
    await editor.get('[data-testid="model-fetch-group"]').trigger('submit')

    expect(editor.emitted('fetch-models')?.[0]).toEqual([{
      provider: 'google_genai',
      baseUrl: '',
      credential: '',
      blockId: '',
      apiVersion: 'v1',
    }])
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

  it('emits edited model and tool call limits', async () => {
    const modelEditor = mountEditor(ModelCallLimitEditor, {
      modelValue: modelCallLimitAdapter.blank(),
    })
    await modelEditor.get('#model-call-run-limit').setValue('6')
    expect(modelEditor.emitted('update:modelValue')?.at(-1)?.[0]).toMatchObject({ run_limit: 6 })

    const toolEditor = mountEditor(ToolCallLimitEditor, {
      modelValue: toolCallLimitAdapter.blank(),
    })
    await toolEditor.get('#tool-call-tool-name').setValue('search')
    expect(toolEditor.emitted('update:modelValue')?.at(-1)?.[0]).toMatchObject({ tool_name: 'search' })
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
