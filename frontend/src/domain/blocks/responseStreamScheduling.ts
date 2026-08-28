import type { ResponseQueueStrategy, ResponseStreamPolicy } from '@/api'

import {
  cleanName,
  clone,
  identity,
  isRecord,
  type BlockDraftBase,
  type BlockPayloadBase,
} from './shared'

export interface ResponseStreamSchedulingDraft extends BlockDraftBase, ResponseStreamPolicy {}
export type ResponseStreamSchedulingDefaults = ResponseStreamPolicy

interface ResponseStreamSchedulingPayload extends BlockPayloadBase, ResponseStreamPolicy {}

const STRATEGIES: ResponseQueueStrategy[] = ['request', 'node_invocation']

function numberValue(value: unknown, fallback: number): number {
  return typeof value === 'number' ? value : fallback
}

function queueValue(value: unknown, fallback: ResponseStreamPolicy['queue']): ResponseStreamPolicy['queue'] {
  const source = isRecord(value) ? value : {}
  return {
    strategy: STRATEGIES.includes(source.strategy as ResponseQueueStrategy)
      ? source.strategy as ResponseQueueStrategy
      : fallback.strategy,
    idle_timeout_seconds: numberValue(
      source.idle_timeout_seconds,
      fallback.idle_timeout_seconds,
    ),
    max_batch_kb: numberValue(source.max_batch_kb, fallback.max_batch_kb),
    send_interval_seconds: numberValue(
      source.send_interval_seconds,
      fallback.send_interval_seconds,
    ),
  }
}

export const responseStreamSchedulingAdapter = {
  blank(defaults: ResponseStreamSchedulingDefaults): ResponseStreamSchedulingDraft {
    return { id: '', name: '', ...clone(defaults) }
  },
  fromApi(
    value: unknown,
    defaults: ResponseStreamSchedulingDefaults,
  ): ResponseStreamSchedulingDraft {
    const source = isRecord(value) ? value : {}
    return {
      ...identity(source),
      queue: queueValue(source.queue, defaults.queue),
    }
  },
  toPayload(value: ResponseStreamSchedulingDraft): ResponseStreamSchedulingPayload {
    return {
      name: cleanName(value.name),
      queue: clone(value.queue),
    }
  },
}
