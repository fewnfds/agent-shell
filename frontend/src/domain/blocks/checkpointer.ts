import {
  cleanName,
  identity,
  isRecord,
  type BlockDraftBase,
  type BlockPayloadBase,
} from './shared'

export type CheckpointDurability = 'exit' | 'async' | 'sync'

export interface CheckpointerDraft extends BlockDraftBase {
  durability: CheckpointDurability
}

interface CheckpointerPayload extends BlockPayloadBase {
  durability: CheckpointDurability
}

const DURABILITY_VALUES: CheckpointDurability[] = ['exit', 'async', 'sync']

function durabilityValue(value: unknown): CheckpointDurability {
  return DURABILITY_VALUES.includes(value as CheckpointDurability)
    ? value as CheckpointDurability
    : 'async'
}

export const checkpointerAdapter = {
  blank(): CheckpointerDraft {
    return { id: '', name: '', durability: 'async' }
  },
  fromApi(value: unknown): CheckpointerDraft {
    const source = isRecord(value) ? value : {}
    return {
      ...identity(source),
      durability: durabilityValue(source.durability),
    }
  },
  toPayload(value: CheckpointerDraft): CheckpointerPayload {
    return {
      name: cleanName(value.name),
      durability: value.durability,
    }
  },
}
