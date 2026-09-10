import { cleanName, identity, type BlockDraftBase, type BlockPayloadBase } from './shared'

export type ToolCallLimitExitBehavior = 'continue' | 'error' | 'end'

export interface ToolCallLimitDraft extends BlockDraftBase {
  tool_name: string
  run_limit: number | ''
  thread_limit: number | ''
  exit_behavior: ToolCallLimitExitBehavior
}

interface ToolCallLimitApiRecord extends BlockDraftBase {
  tool_name?: unknown
  run_limit?: unknown
  thread_limit?: unknown
  exit_behavior?: unknown
}

interface ToolCallLimitPayload extends BlockPayloadBase {
  tool_name: string | null
  run_limit: number | null
  thread_limit: number | null
  exit_behavior: ToolCallLimitExitBehavior
}

function limitValue(value: unknown): number | '' {
  return typeof value === 'number' && Number.isFinite(value) ? value : ''
}

export const toolCallLimitAdapter = {
  blank(): ToolCallLimitDraft {
    return {
      id: '',
      name: '',
      tool_name: '',
      run_limit: '',
      thread_limit: '',
      exit_behavior: 'continue',
    }
  },
  fromApi(value: ToolCallLimitApiRecord): ToolCallLimitDraft {
    return {
      ...identity(value),
      tool_name: typeof value.tool_name === 'string' ? value.tool_name : '',
      run_limit: limitValue(value.run_limit),
      thread_limit: limitValue(value.thread_limit),
      exit_behavior: value.exit_behavior === 'error' || value.exit_behavior === 'end'
        ? value.exit_behavior
        : 'continue',
    }
  },
  toPayload(value: ToolCallLimitDraft): ToolCallLimitPayload {
    return {
      name: cleanName(value.name),
      tool_name: value.tool_name.trim() || null,
      run_limit: value.run_limit === '' ? null : value.run_limit,
      thread_limit: value.thread_limit === '' ? null : value.thread_limit,
      exit_behavior: value.exit_behavior,
    }
  },
}
