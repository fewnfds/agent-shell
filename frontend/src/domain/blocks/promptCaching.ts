import {
  cleanName,
  clone,
  identity,
  type BlockDraftBase,
  type BlockPayloadBase,
} from './shared'

export interface PromptCachingDraft extends BlockDraftBase {
  type: 'ephemeral'
  ttl: '5m' | '1h'
  min_messages_to_cache: number | string
}

export type PromptCachingDefaults = Omit<PromptCachingDraft, 'id' | 'name'>

interface PromptCachingApiRecord extends BlockDraftBase {
  type?: unknown
  ttl?: unknown
  min_messages_to_cache?: unknown
}
interface PromptCachingPayload extends BlockPayloadBase, Omit<PromptCachingDraft, 'id' | 'name'> {}

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

export const promptCachingAdapter = {
  blank(defaults: PromptCachingDefaults): PromptCachingDraft {
    return { id: '', name: '', ...clone(defaults) }
  },
  fromApi(value: PromptCachingApiRecord, defaults: PromptCachingDefaults): PromptCachingDraft {
    return {
      ...identity(value),
      type: 'ephemeral',
      ttl: value.ttl === '1h' || value.ttl === '5m' ? value.ttl : defaults.ttl,
      min_messages_to_cache: normalizeTokenLimit(
        value.min_messages_to_cache,
        Number(defaults.min_messages_to_cache),
      ) ?? defaults.min_messages_to_cache,
    }
  },
  toPayload(value: PromptCachingDraft): PromptCachingPayload {
    return {
      name: cleanName(value.name),
      type: value.type,
      ttl: value.ttl,
      min_messages_to_cache: normalizeTokenLimit(value.min_messages_to_cache, null)
        ?? value.min_messages_to_cache,
    }
  },
}
