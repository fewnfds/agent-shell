import { afterEach, describe, expect, it, vi } from 'vitest'

import { readBrowserStorage, writeBrowserStorage } from './browserStorage'

afterEach(() => {
  vi.restoreAllMocks()
})

describe('browser preference storage', () => {
  it('treats denied localStorage access as an empty preference', () => {
    vi.spyOn(window, 'localStorage', 'get').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError')
    })

    expect(readBrowserStorage('lte-theme')).toBeNull()
  })

  it('ignores storage write failures', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError')
    })

    expect(() => writeBrowserStorage('lte-theme', 'dark')).not.toThrow()
  })
})
