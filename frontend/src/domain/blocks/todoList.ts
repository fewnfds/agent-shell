import {
  cleanName,
  editableText,
  identity,
  overrideValue,
  type BlockDraftBase,
  type BlockPayloadBase,
} from './shared'

export interface TodoListDraft extends BlockDraftBase {
  system_prompt_override: string
  tool_description_override: string
}

interface TodoListApiRecord extends BlockDraftBase {
  system_prompt_override: string | null
  tool_description_override: string | null
}

interface TodoListPayload extends BlockPayloadBase {
  system_prompt_override: string | null
  tool_description_override: string | null
}

export interface TodoListDefaults {
  system_prompt: string
  tool_description: string
}

export const todoListAdapter = {
  blank(defaults: TodoListDefaults): TodoListDraft {
    return {
      id: '', name: '',
      system_prompt_override: defaults.system_prompt,
      tool_description_override: defaults.tool_description,
    }
  },
  fromApi(value: TodoListApiRecord, defaults: TodoListDefaults): TodoListDraft {
    return {
      ...identity(value),
      system_prompt_override: editableText(value.system_prompt_override, defaults.system_prompt),
      tool_description_override: editableText(value.tool_description_override, defaults.tool_description),
    }
  },
  toPayload(value: TodoListDraft, defaults: TodoListDefaults): TodoListPayload {
    return {
      name: cleanName(value.name),
      system_prompt_override: overrideValue(value.system_prompt_override, defaults.system_prompt),
      tool_description_override: overrideValue(value.tool_description_override, defaults.tool_description),
    }
  },
}
