import { describe, expect, it } from 'vitest'

import { router } from './index'

describe('configuration library routes', () => {
  it('keeps global configuration entries under the Configuration Library route', () => {
    const libraryRoute = router.resolve('/library/model-connection').matched.at(-1)
    const globalModelRoute = router.resolve('/library/model-connection').matched.at(-1)
    const repositoryRoute = router.resolve('/library/configuration-repositories').matched.at(-1)
    const systemRoute = router.resolve('/system/model-connections').matched.at(-1)

    expect(globalModelRoute?.components?.default).toBe(libraryRoute?.components?.default)
    expect(repositoryRoute?.components?.default).not.toBe(libraryRoute?.components?.default)
    expect(systemRoute?.name).toBeUndefined()
  })
})
