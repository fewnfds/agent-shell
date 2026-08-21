import {
  cleanName,
  identity,
  stringValue,
  type BlockDraftBase,
} from './shared'

export interface SystemPromptDraft extends BlockDraftBase {
  system_prompt: string
}

type SystemPromptApiRecord = SystemPromptDraft

interface SystemPromptPayload {
  name: string
  system_prompt: string
}

export const systemPromptAdapter = {
  blank(): SystemPromptDraft {
    return { id: '', name: '', system_prompt: '' }
  },
  fromApi(value: SystemPromptApiRecord): SystemPromptDraft {
    return { ...identity(value), system_prompt: stringValue(value.system_prompt) }
  },
  toPayload(value: SystemPromptDraft): SystemPromptPayload {
    return { name: cleanName(value.name), system_prompt: value.system_prompt.trim() }
  },
}
