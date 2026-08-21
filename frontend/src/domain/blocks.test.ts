import { describe, expect, it } from 'vitest'

import {
  blockAdapters,
  managedComponentTypes,
  agentEventOutputAdapter,
  customMiddlewareAdapter,
  customToolAdapter,
  filesystemAdapter,
  modelAdapter,
  skillAdapter,
  subagentAdapter,
  systemPromptAdapter,
  todoListAdapter,
  type FilesystemDefaults,
  type ModelApiRecord,
  type SkillDefaults,
  type SubagentDefaults,
  type TodoListDefaults,
  workflowEventOutputAdapter,
} from './blocks'

const filesystemDefaults: FilesystemDefaults = {
  system_prompt: 'filesystem default',
  tool_token_limit_before_evict: 20_000,
  tools: [
    { name: 'read_file', configurable: false, visible: true, default_description: 'read default' },
    { name: 'delete', configurable: true, visible: false, default_description: 'delete default' },
    { name: 'execute', configurable: false, visible: false, default_description: 'execute default' },
  ],
}

const skillDefaults: SkillDefaults = { system_prompt: 'skill default' }
const subagentDefaults: SubagentDefaults = {
  system_prompt: 'subagent default',
  tool_description: 'task default',
}
const todoDefaults: TodoListDefaults = {
  system_prompt: 'todo default',
  tool_description: 'write_todos default',
}
function modelRecord(): ModelApiRecord {
  return {
    id: 'model-id', name: 'Model', provider: 'openai', base_url: 'https://example.test/v1', model: 'example-model',
    credential: { status: 'masked' }, provider_settings: { stop_sequences: ['END'] },
    tool_choice: 'auto', response_format: {
      title: 'Result', description: 'Structured result', type: 'object',
    },
    model_settings: { parallel_tool_calls: false },
  }
}

describe('block adapters', () => {
  it('registers exactly one explicit adapter for every current block type', () => {
    expect(Object.keys(blockAdapters)).toEqual(managedComponentTypes)
  })

  it('maps model credentials and nullable parameters without validating provider behavior', () => {
    const draft = modelAdapter.fromApi(modelRecord())
    expect(draft.credential_secret).toBe('')
    expect(draft.credential_status).toBe('masked')
    expect(draft.provider_settings.stop_sequences).toBe('["END"]')
    expect(draft.provider_settings.use_responses_api).toBeUndefined()

    draft.name = '  Updated model  '
    draft.credential_secret = 'secret'
    draft.provider_settings.temperature = ''
    draft.provider_settings.stop_sequences = 'not-json-yet'
    draft.provider_settings.use_responses_api = true
    const payload = modelAdapter.toPayload(draft)
    expect(payload).toMatchObject({
      name: 'Updated model', credential: 'secret', provider_settings: {
        stop_sequences: 'not-json-yet',
        use_responses_api: true,
      },
      tool_choice: 'auto', response_format: {
        title: 'Result', description: 'Structured result', type: 'object',
      },
      model_settings: { parallel_tool_calls: false },
    })
  })

  it('keeps the configuration extension reference and template selection mechanical', () => {
    const toolDraft = customToolAdapter.blank()
    toolDraft.name = ' Tools '
    toolDraft.python_package_template = { key: 'word-count', revision: 'revision' }
    expect(customToolAdapter.toPayload(toolDraft)).toEqual({
      name: 'Tools',
      python_package: { folder: '' },
      python_package_template: { key: 'word-count', revision: 'revision' },
    })

    const middlewareDraft = customMiddlewareAdapter.fromApi({
      id: 'middleware-id',
      name: 'Middleware',
      python_package: { folder: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa' },
    })
    const payload = customMiddlewareAdapter.toPayload(middlewareDraft)
    expect(payload).toEqual({
      name: 'Middleware',
      python_package: { folder: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa' },
    })
    expect(middlewareDraft.python_package_inspection).toBeNull()
  })

  it('uses the shared Python package draft contract for both event output owners', () => {
    for (const adapter of [agentEventOutputAdapter, workflowEventOutputAdapter]) {
      const draft = adapter.fromApi({
        id: 'output-id',
        name: 'Output',
        python_package: { folder: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa' },
      })
      expect(adapter.toPayload(draft)).toEqual({
        name: 'Output',
        python_package: { folder: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa' },
      })
    }
  })

  it('projects malformed saved components into repairable current drafts', () => {
    const model = modelAdapter.fromApi({
      ...modelRecord(),
      provider: undefined,
      provider_settings: ['invalid'],
      model_settings: ['invalid'],
      legacy_parameter: 'discarded',
    } as never)
    expect(model.provider).toBe('openai')
    expect(model.provider_settings).toEqual({})
    expect(model.model_settings).toBe('{}')
    expect(model).not.toHaveProperty('legacy_parameter')

    const malformedTool = customToolAdapter.fromApi({
      id: 'tools', name: 'Tools',
      python_package: { folder: 42 },
    } as never)
    expect(malformedTool.python_package).toEqual({ folder: '' })
    expect(malformedTool.python_package_inspection).toBeNull()

    const middleware = customMiddlewareAdapter.fromApi({
      id: 'middleware', name: 'Middleware',
      python_package: ['invalid'],
    } as never)
    expect(middleware.python_package).toEqual({ folder: '' })
    expect(middleware.python_package_inspection).toBeNull()

    const filesystem = filesystemAdapter.fromApi({
      id: 'files', name: 'Files',
      mapped_directories: [{ virtual_path: '/kept/', local_path: 'H:\\kept' }, 42],
      virtual_directories: 'invalid', virtual_files: [],
      system_prompt_override: 42, tool_token_limit_before_evict: {},
      tool_configs: {
        read_file: { visible: false, description_override: 42 },
      },
    } as never, filesystemDefaults)
    expect(filesystem.mapped_directories).toEqual([
      {
        virtual_path: '/kept/',
        local_path: 'H:\\kept',
        path_origin: 'absolute',
        lifecycle_mode: 'fixed',
      },
    ])
    expect(filesystem.virtual_directories).toEqual([])
    expect(filesystem.system_prompt_override).toBe(filesystemDefaults.system_prompt)
    expect(filesystem.tool_configs.read_file).toEqual({
      visible: true, description_override: 'read default',
    })
    expect(filesystem.tool_configs.delete).toEqual({
      visible: false, description_override: 'delete default',
    })

    expect(skillAdapter.fromApi({
      id: 'skill', name: 'Skill', skill_package: { folder: 'skill' },
      system_prompt_enabled: false, instruction_override: 42,
    } as never, skillDefaults)).toMatchObject({
      skill_package: { folder: 'skill' }, skill_template_paths: [],
      system_prompt_enabled: false, instruction_override: 'skill default',
    })
    expect(systemPromptAdapter.fromApi({
      id: 'system', name: 'System', system_prompt: 42,
    } as never).system_prompt).toBe('')
    expect(subagentAdapter.fromApi({
      id: 'subagent', name: 'Subagent', instruction_override: 42,
      task_description_override: 'kept',
    } as never, subagentDefaults)).toMatchObject({
      instruction_override: 'subagent default',
      task_description_override: 'kept',
    })
    expect(todoListAdapter.fromApi({
      id: 'todo', name: 'Todo', system_prompt_override: 42,
      tool_description_override: 'kept',
    } as never, todoDefaults)).toMatchObject({
      system_prompt_override: 'todo default', tool_description_override: 'kept',
    })
  })

  it('maps filesystem defaults and rows without enforcing path rules', () => {
    const blank = filesystemAdapter.blank(filesystemDefaults)
    expect(blank.tool_configs.read_file?.description_override).toBe('read default')
    expect(blank.tool_configs.execute?.visible).toBe(false)

    blank.name = ' Files '
    blank.mapped_directories.push(
      {
        virtual_path: '', local_path: '', path_origin: 'absolute', lifecycle_mode: 'fixed',
      },
      {
        virtual_path: ' /workspace/ ',
        local_path: ' workspaces ',
        path_origin: 'data-root-relative',
        lifecycle_mode: 'dynamic',
      },
    )
    const payload = filesystemAdapter.toPayload(blank, filesystemDefaults)
    expect(payload.mapped_directories).toEqual([
      {
        virtual_path: '/workspace/',
        local_path: 'workspaces',
        path_origin: 'data-root-relative',
        lifecycle_mode: 'dynamic',
      },
    ])
    expect(payload.system_prompt_override).toBeNull()
    blank.tool_configs.read_file.visible = false
    blank.tool_configs.execute.visible = true
    expect(payload.tool_configs.read_file?.description_override).toBeNull()
    const repairedPayload = filesystemAdapter.toPayload(blank, filesystemDefaults)
    expect(repairedPayload.tool_configs.read_file?.visible).toBe(true)
    expect(repairedPayload.tool_configs.delete?.visible).toBe(false)
    expect(repairedPayload.tool_configs.execute?.visible).toBe(false)
  })

  it('round-trips the remaining simple editors and removes displayed defaults', () => {
    const skill = skillAdapter.blank(skillDefaults)
    skill.name = ' Skill '
    skill.skill_template_paths = ['group/alpha']
    expect(skillAdapter.toPayload(skill, skillDefaults)).toEqual({
      name: 'Skill', skill_template_paths: ['group/alpha'], system_prompt_enabled: true, instruction_override: null,
    })
    skill.system_prompt_enabled = false
    skill.instruction_override = 'Custom but disabled'
    expect(skillAdapter.toPayload(skill, skillDefaults)).toEqual({
      name: 'Skill', skill_template_paths: ['group/alpha'], system_prompt_enabled: false, instruction_override: null,
    })

    const systemPrompt = systemPromptAdapter.blank()
    systemPrompt.name = ' System '
    systemPrompt.system_prompt = ' Prompt body '
    expect(systemPromptAdapter.toPayload(systemPrompt)).toEqual({
      name: 'System', system_prompt: 'Prompt body',
    })

    const subagent = subagentAdapter.blank(subagentDefaults)
    subagent.name = ' Subagent '
    expect(subagentAdapter.toPayload(subagent, subagentDefaults)).toEqual({
      name: 'Subagent',
      instruction_override: null,
      task_description_override: null,
    })

    const todo = todoListAdapter.blank(todoDefaults)
    todo.name = ' Todos '
    expect(todoListAdapter.toPayload(todo, todoDefaults)).toEqual({
      name: 'Todos', system_prompt_override: null, tool_description_override: null,
    })

  })
})
