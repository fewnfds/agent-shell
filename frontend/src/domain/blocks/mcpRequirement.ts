import { cleanName, identity, stringValue, type BlockDraftBase, type BlockPayloadBase } from './shared'

export interface McpRequirementDraft extends BlockDraftBase {
  description: string
  namespace: string
}

interface McpRequirementApiRecord extends BlockDraftBase {
  description?: unknown
  namespace?: unknown
}

interface McpRequirementPayload extends BlockPayloadBase {
  description: string
  namespace: string
}

export const mcpRequirementAdapter = {
  blank(): McpRequirementDraft {
    return { id: '', name: '', description: '', namespace: '' }
  },
  fromApi(value: McpRequirementApiRecord): McpRequirementDraft {
    return {
      ...identity(value),
      description: stringValue(value.description),
      namespace: stringValue(value.namespace),
    }
  },
  toPayload(value: McpRequirementDraft): McpRequirementPayload {
    return {
      name: cleanName(value.name),
      description: value.description,
      namespace: value.namespace.trim(),
    }
  },
}
