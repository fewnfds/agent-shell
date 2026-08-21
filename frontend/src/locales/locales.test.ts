import { describe, expect, it } from 'vitest'

import { en } from './en'
import {
  assertLocaleParity,
  debugMessages,
  formattingLocale,
  messageKeys,
  messageValues,
  resolveInitialLocale,
} from './index'
import { zhCN } from './zh-CN'

describe('locale contract', () => {
  it('keeps zh-CN, en, and debug keys identical', () => {
    expect(() => assertLocaleParity()).not.toThrow()
    expect(messageKeys(zhCN)).toEqual(messageKeys(en))
    expect(messageKeys(zhCN)).toEqual(messageKeys(debugMessages))
    expect(messageValues(zhCN).every((value) => value.trim().length > 0)).toBe(true)
    expect(messageValues(en).every((value) => value.trim().length > 0)).toBe(true)
    expect(debugMessages.common.save).toBe('common.save')
    expect(debugMessages.fields.max_tokens).toBe('max_tokens')
    expect(debugMessages.capabilities['filesystem-permissions'].label)
      .toBe('filesystem-permissions')
    expect(debugMessages.validation.issue.contract.requiredText)
      .toBe('validation.issue.contract.requiredText')
  })

  it('uses a saved locale before browser language', () => {
    expect(resolveInitialLocale('en', ['zh-CN'])).toBe('en')
    expect(resolveInitialLocale('debug', ['zh-CN'])).toBe('debug')
    expect(resolveInitialLocale(null, ['zh-Hans', 'en'])).toBe('zh-CN')
    expect(resolveInitialLocale(null, ['fr'])).toBe('en')
  })

  it('uses a valid formatting locale in debug mode', () => {
    expect(formattingLocale('debug')).toBe('en')
    expect(() => new Intl.DateTimeFormat(formattingLocale('debug'))).not.toThrow()
  })
})
