import { cleanName, identity, type BlockDraftBase, type BlockPayloadBase } from './shared'

export type ModelCallLimitExitBehavior = 'end' | 'error'

export interface ModelCallLimitDraft extends BlockDraftBase {
  run_limit: number | ''
  thread_limit: number | ''
  exit_behavior: ModelCallLimitExitBehavior
}

export interface ModelCallLimitApiRecord extends BlockDraftBase {
  run_limit?: unknown
  thread_limit?: unknown
  exit_behavior?: unknown
}

export interface ModelCallLimitPayload extends BlockPayloadBase {
  run_limit: number | null
  thread_limit: number | null
  exit_behavior: ModelCallLimitExitBehavior
}

function limitValue(value: unknown): number | '' {
  return typeof value === 'number' && Number.isFinite(value) ? value : ''
}

export const modelCallLimitAdapter = {
  blank(): ModelCallLimitDraft {
    return { id: '', name: '', run_limit: '', thread_limit: '', exit_behavior: 'end' }
  },
  fromApi(value: ModelCallLimitApiRecord): ModelCallLimitDraft {
    return {
      ...identity(value),
      run_limit: limitValue(value.run_limit),
      thread_limit: limitValue(value.thread_limit),
      exit_behavior: value.exit_behavior === 'error' ? 'error' : 'end',
    }
  },
  toPayload(value: ModelCallLimitDraft): ModelCallLimitPayload {
    return {
      name: cleanName(value.name),
      run_limit: value.run_limit === '' ? null : value.run_limit,
      thread_limit: value.thread_limit === '' ? null : value.thread_limit,
      exit_behavior: value.exit_behavior,
    }
  },
}
