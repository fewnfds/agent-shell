import { effectScope, nextTick, ref } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { ValidationReport } from '@/domain/agents'

import { useConfigurationValidation } from './useConfigurationValidation'

function report(valid: boolean): ValidationReport {
  return { valid, stage: 'draft_validation', issues: valid ? [] : [{
    code: 'invalid',
    scope: 'main_agent',
    owner_id: '',
    owner_name: '',
    path: 'name',
    message: 'invalid',
  }] }
}

afterEach(() => {
  vi.useRealTimers()
})

describe('useConfigurationValidation', () => {
  it('debounces watched validation for 1000ms by default', async () => {
    vi.useFakeTimers()
    const draft = ref({ name: '' })
    const validate = vi.fn(async () => report(true))
    const scope = effectScope()
    const hook = scope.run(() => useConfigurationValidation({
      source: draft,
      buildRequest: () => ({ target: { kind: 'main_agent' }, payload: draft.value }),
      validate,
      immediate: false,
    }))
    if (!hook) throw new Error('validation hook was not created')

    draft.value.name = 'next'
    await nextTick()
    await vi.advanceTimersByTimeAsync(999)
    expect(validate).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1)
    expect(validate).toHaveBeenCalledOnce()
    scope.stop()
  })

  it('uses the configured interval and suppresses an older response', async () => {
    vi.useFakeTimers()
    const draft = ref({ name: '' })
    const pending: Array<(value: ValidationReport) => void> = []
    const validate = vi.fn(() => new Promise<ValidationReport>((resolve) => pending.push(resolve)))
    const scope = effectScope()
    const hook = scope.run(() => useConfigurationValidation({
      source: draft,
      buildRequest: () => ({ target: { kind: 'main_agent' }, payload: { ...draft.value } }),
      validate,
      debounceMs: 500,
      immediate: false,
    }))
    if (!hook) throw new Error('validation hook was not created')

    draft.value.name = 'first'
    await nextTick()
    await vi.advanceTimersByTimeAsync(500)
    draft.value.name = 'newer'
    await nextTick()
    await vi.advanceTimersByTimeAsync(500)

    pending[1]?.(report(true))
    await Promise.resolve()
    expect(hook.validation.value.status).toBe('valid')

    pending[0]?.(report(false))
    await Promise.resolve()
    expect(hook.validation.value.status).toBe('valid')
    scope.stop()
  })

  it('supports manual repository validation and authoritative report replacement', async () => {
    const validate = vi.fn(async () => report(true))
    const scope = effectScope()
    const hook = scope.run(() => useConfigurationValidation({
      buildRequest: () => ({}),
      validate,
      immediate: false,
    }))
    if (!hook) throw new Error('validation hook was not created')

    expect((await hook.validateNow()).status).toBe('valid')
    expect(hook.applyReport(report(false)).status).toBe('invalid')
    scope.stop()
  })
})
