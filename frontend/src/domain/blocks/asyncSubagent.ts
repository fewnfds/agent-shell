import {
  cleanName,
  editableText,
  identity,
  overrideValue,
  type BlockDraftBase,
  type BlockPayloadBase,
} from './shared'

export const asyncSubagentToolNames = [
  'start_async_task',
  'check_async_task',
  'update_async_task',
  'cancel_async_task',
  'list_async_tasks',
] as const

export type AsyncSubagentToolName = typeof asyncSubagentToolNames[number]
export type AsyncSubagentDescriptionField = `${AsyncSubagentToolName}_description_override`

export interface AsyncSubagentDraft extends BlockDraftBase {
  system_prompt_override: string
  start_async_task_description_override: string
  check_async_task_description_override: string
  update_async_task_description_override: string
  cancel_async_task_description_override: string
  list_async_tasks_description_override: string
}

interface AsyncSubagentApiRecord extends BlockDraftBase {
  system_prompt_override: string | null
  start_async_task_description_override: string | null
  check_async_task_description_override: string | null
  update_async_task_description_override: string | null
  cancel_async_task_description_override: string | null
  list_async_tasks_description_override: string | null
}

interface AsyncSubagentPayload extends BlockPayloadBase {
  system_prompt_override: string | null
  start_async_task_description_override: string | null
  check_async_task_description_override: string | null
  update_async_task_description_override: string | null
  cancel_async_task_description_override: string | null
  list_async_tasks_description_override: string | null
}

export interface AsyncSubagentDefaults {
  system_prompt: string
  tool_descriptions: Record<AsyncSubagentToolName, string>
}

function descriptionField(toolName: AsyncSubagentToolName): AsyncSubagentDescriptionField {
  return `${toolName}_description_override`
}

function descriptions(
  source: Partial<AsyncSubagentApiRecord>,
  defaults: AsyncSubagentDefaults,
): Pick<AsyncSubagentDraft, AsyncSubagentDescriptionField> {
  return Object.fromEntries(asyncSubagentToolNames.map((toolName) => {
    const field = descriptionField(toolName)
    return [field, editableText(source[field], defaults.tool_descriptions[toolName])]
  })) as Pick<AsyncSubagentDraft, AsyncSubagentDescriptionField>
}

export const asyncSubagentAdapter = {
  blank(defaults: AsyncSubagentDefaults): AsyncSubagentDraft {
    return {
      id: '',
      name: '',
      system_prompt_override: defaults.system_prompt,
      ...descriptions({}, defaults),
    }
  },
  fromApi(
    value: AsyncSubagentApiRecord,
    defaults: AsyncSubagentDefaults,
  ): AsyncSubagentDraft {
    return {
      ...identity(value),
      system_prompt_override: editableText(
        value.system_prompt_override,
        defaults.system_prompt,
      ),
      ...descriptions(value, defaults),
    }
  },
  toPayload(
    value: AsyncSubagentDraft,
    defaults: AsyncSubagentDefaults,
  ): AsyncSubagentPayload {
    const payload: AsyncSubagentPayload = {
      name: cleanName(value.name),
      system_prompt_override: overrideValue(
        value.system_prompt_override,
        defaults.system_prompt,
      ),
      start_async_task_description_override: null,
      check_async_task_description_override: null,
      update_async_task_description_override: null,
      cancel_async_task_description_override: null,
      list_async_tasks_description_override: null,
    }
    for (const toolName of asyncSubagentToolNames) {
      const field = descriptionField(toolName)
      payload[field] = overrideValue(value[field], defaults.tool_descriptions[toolName])
    }
    return payload
  },
}
