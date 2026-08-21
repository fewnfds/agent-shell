import {
  cleanName,
  editableText,
  identity,
  overrideValue,
  type BlockDraftBase,
  type BlockPayloadBase,
} from './shared'

export interface SubagentDraft extends BlockDraftBase {
  instruction_override: string
  task_description_override: string
}

interface SubagentApiRecord extends BlockDraftBase {
  instruction_override: string | null
  task_description_override: string | null
}

interface SubagentPayload extends BlockPayloadBase {
  instruction_override: string | null
  task_description_override: string | null
}

export interface SubagentDefaults {
  system_prompt: string
  tool_description: string
}

export const subagentAdapter = {
  blank(defaults: SubagentDefaults): SubagentDraft {
    return {
      id: '', name: '',
      instruction_override: defaults.system_prompt,
      task_description_override: defaults.tool_description,
    }
  },
  fromApi(value: SubagentApiRecord, defaults: SubagentDefaults): SubagentDraft {
    return {
      ...identity(value),
      instruction_override: editableText(value.instruction_override, defaults.system_prompt),
      task_description_override: editableText(value.task_description_override, defaults.tool_description),
    }
  },
  toPayload(value: SubagentDraft, defaults: SubagentDefaults): SubagentPayload {
    return {
      name: cleanName(value.name),
      instruction_override: overrideValue(value.instruction_override, defaults.system_prompt),
      task_description_override: overrideValue(value.task_description_override, defaults.tool_description),
    }
  },
}
