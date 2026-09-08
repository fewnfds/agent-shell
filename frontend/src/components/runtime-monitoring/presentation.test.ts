import { describe, expect, it } from 'vitest'

import { monitoringShortId } from './presentation'

describe('runtime monitoring presentation', () => {
  it('uses the random UUID tail for compact Thread and Run identity', () => {
    expect(monitoringShortId('0199fca1-23ab-7000-8000-0123456789ab')).toBe('…456789ab')
    expect(monitoringShortId('0199fca1-23ab-7000-8000-fedcba987654')).toBe('…ba987654')
    expect(monitoringShortId('run-1')).toBe('run-1')
  })
})
