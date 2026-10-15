import { cleanName, clone, identity, type BlockDraftBase, type BlockPayloadBase } from './shared'

export type PiiStrategy = 'block' | 'redact' | 'mask' | 'hash'

export interface PiiRule {
  pii_type: string
  strategy: PiiStrategy
  detector: string | null
  apply_to_input: boolean
  apply_to_output: boolean
  apply_to_tool_results: boolean
}

export interface PiiDraft extends BlockDraftBase { rules: PiiRule[] }
export interface PiiPayload extends BlockPayloadBase { rules: PiiRule[] }
export interface PiiDefaults {
  pii_types: string[]
  strategies: PiiStrategy[]
  default_value: { rules: PiiRule[] }
}

export const piiAdapter = {
  blank(defaults: PiiDefaults): PiiDraft {
    return { id: '', name: '', ...clone(defaults.default_value) }
  },
  fromApi(value: PiiDraft): PiiDraft {
    return { ...identity(value), rules: clone(value.rules) }
  },
  toPayload(value: PiiDraft): PiiPayload {
    return { name: cleanName(value.name), rules: clone(value.rules) }
  },
}
