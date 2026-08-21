import { cleanName, identity, stringValue, type BlockDraftBase, type BlockPayloadBase } from './shared'

export interface ModelRequirementDraft extends BlockDraftBase {
  description: string
}

interface ModelRequirementApiRecord extends BlockDraftBase {
  description?: unknown
}

interface ModelRequirementPayload extends BlockPayloadBase {
  description: string
}

export const modelRequirementAdapter = {
  blank(): ModelRequirementDraft {
    return { id: '', name: '', description: '' }
  },
  fromApi(value: ModelRequirementApiRecord): ModelRequirementDraft {
    return { ...identity(value), description: stringValue(value.description) }
  },
  toPayload(value: ModelRequirementDraft): ModelRequirementPayload {
    return { name: cleanName(value.name), description: value.description }
  },
}
