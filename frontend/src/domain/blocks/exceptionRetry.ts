import {
  cleanName,
  clone,
  identity,
  type BlockDraftBase,
  type BlockPayloadBase,
} from './shared'

type ExceptionRetryStrategy = 'provider_native' | 'model_retry_middleware'
export type ExceptionRetryCondition =
  | 'transport_error'
  | 'timeout'
  | 'rate_limit'
  | 'server_error'
  | 'authentication_error'

interface ExceptionRetryValue {
  strategy: ExceptionRetryStrategy
  force_non_streaming: boolean
  max_retries: number | string
  retry_on: ExceptionRetryCondition[]
}

export interface ExceptionRetryDraft extends BlockDraftBase, ExceptionRetryValue {}
type ExceptionRetryApiRecord = ExceptionRetryDraft
interface ExceptionRetryPayload extends BlockPayloadBase, ExceptionRetryValue {}

export interface ExceptionRetryDefaults {
  strategies: ExceptionRetryStrategy[]
  conditions: ExceptionRetryCondition[]
  default_value: ExceptionRetryValue
}

export const exceptionRetryAdapter = {
  blank(defaults: ExceptionRetryDefaults): ExceptionRetryDraft {
    return { id: '', name: '', ...clone(defaults.default_value) }
  },
  fromApi(
    value: ExceptionRetryApiRecord,
    defaults: ExceptionRetryDefaults,
  ): ExceptionRetryDraft {
    const fallback = defaults.default_value
    return {
      ...identity(value),
      strategy: defaults.strategies.includes(value.strategy)
        ? value.strategy
        : fallback.strategy,
      force_non_streaming: typeof value.force_non_streaming === 'boolean'
        ? value.force_non_streaming
        : fallback.force_non_streaming,
      max_retries: typeof value.max_retries === 'number'
        ? value.max_retries
        : fallback.max_retries,
      retry_on: Array.isArray(value.retry_on)
        ? defaults.conditions.filter((condition) => value.retry_on.includes(condition))
        : clone(fallback.retry_on),
    }
  },
  toPayload(value: ExceptionRetryDraft): ExceptionRetryPayload {
    return {
      name: cleanName(value.name),
      strategy: value.strategy,
      force_non_streaming: value.force_non_streaming,
      max_retries: value.max_retries,
      retry_on: [...new Set(value.retry_on)],
    }
  },
}
