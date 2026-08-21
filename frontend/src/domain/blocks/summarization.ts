import {
  cleanName,
  clone,
  identity,
  isRecord,
  stringValue,
  type BlockDraftBase,
  type BlockPayloadBase,
} from './shared'

export type SummarizationThresholdType = 'auto' | 'fraction' | 'tokens' | 'messages'
export interface SummarizationThresholdDraft {
  type: SummarizationThresholdType
  value: number | string | null
}
export interface SummarizationDraft extends BlockDraftBase {
  trigger: SummarizationThresholdDraft
  keep: SummarizationThresholdDraft
  truncate_args_enabled: boolean
  truncate_args_trigger: SummarizationThresholdDraft
  truncate_args_keep: SummarizationThresholdDraft
  truncate_args_max_length: number | string
  truncate_args_text: string
  trim_tokens_to_summarize: number | string | null
  summary_prompt_override: string
}

export type SummarizationDefaults = Omit<SummarizationDraft, 'id' | 'name'> & {
  summary_prompt_default: string
}

interface SummarizationApiRecord extends BlockDraftBase {
  trigger?: unknown
  keep?: unknown
  truncate_args_enabled?: unknown
  truncate_args_trigger?: unknown
  truncate_args_keep?: unknown
  truncate_args_max_length?: unknown
  truncate_args_text?: unknown
  trim_tokens_to_summarize?: unknown
  summary_prompt_override?: unknown
}
interface SummarizationPayload extends BlockPayloadBase,
  Omit<SummarizationDraft, 'id' | 'name' | 'summary_prompt_override'> {
  summary_prompt_override: string | null
}

function normalizeTokenLimit(value: unknown, fallback: number | null): number | string | null {
  if (value === undefined) return fallback
  if (value === null) return null
  if (typeof value === 'string') {
    if (!value.trim()) return null
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : value
  }
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function summarizationThresholdDraft(
  value: unknown,
  fallback: SummarizationThresholdDraft,
): SummarizationThresholdDraft {
  const source = isRecord(value) ? value : {}
  const type = ['auto', 'fraction', 'tokens', 'messages'].includes(String(source.type))
    ? source.type as SummarizationThresholdType
    : fallback.type
  return {
    type,
    value: type === 'auto' ? null : normalizeTokenLimit(source.value, fallback.value as number | null),
  }
}

export const summarizationAdapter = {
  blank(defaults: SummarizationDefaults): SummarizationDraft {
    return {
      id: '',
      name: '',
      ...clone(defaults),
      summary_prompt_override: defaults.summary_prompt_default,
    }
  },
  fromApi(value: SummarizationApiRecord, defaults: SummarizationDefaults): SummarizationDraft {
    return {
      ...identity(value),
      trigger: summarizationThresholdDraft(value.trigger, defaults.trigger),
      keep: summarizationThresholdDraft(value.keep, defaults.keep),
      truncate_args_enabled: typeof value.truncate_args_enabled === 'boolean'
        ? value.truncate_args_enabled
        : defaults.truncate_args_enabled,
      truncate_args_trigger: summarizationThresholdDraft(
        value.truncate_args_trigger,
        defaults.truncate_args_trigger,
      ),
      truncate_args_keep: summarizationThresholdDraft(
        value.truncate_args_keep,
        defaults.truncate_args_keep,
      ),
      truncate_args_max_length: normalizeTokenLimit(
        value.truncate_args_max_length,
        Number(defaults.truncate_args_max_length),
      ) ?? defaults.truncate_args_max_length,
      truncate_args_text: stringValue(value.truncate_args_text, defaults.truncate_args_text),
      trim_tokens_to_summarize: normalizeTokenLimit(
        value.trim_tokens_to_summarize,
        defaults.trim_tokens_to_summarize as number | null,
      ),
      summary_prompt_override: stringValue(
        value.summary_prompt_override,
        defaults.summary_prompt_default,
      ),
    }
  },
  toPayload(value: SummarizationDraft, defaults: SummarizationDefaults): SummarizationPayload {
    const threshold = (item: SummarizationThresholdDraft): SummarizationThresholdDraft => ({
      type: item.type,
      value: item.type === 'auto' ? null : normalizeTokenLimit(item.value, null),
    })
    return {
      name: cleanName(value.name),
      trigger: threshold(value.trigger),
      keep: threshold(value.keep),
      truncate_args_enabled: value.truncate_args_enabled,
      truncate_args_trigger: threshold(value.truncate_args_trigger),
      truncate_args_keep: threshold(value.truncate_args_keep),
      truncate_args_max_length: normalizeTokenLimit(value.truncate_args_max_length, null)
        ?? value.truncate_args_max_length,
      truncate_args_text: value.truncate_args_text,
      trim_tokens_to_summarize: normalizeTokenLimit(value.trim_tokens_to_summarize, null),
      summary_prompt_override: value.summary_prompt_override === defaults.summary_prompt_default
        ? null
        : value.summary_prompt_override || null,
    }
  },
}
