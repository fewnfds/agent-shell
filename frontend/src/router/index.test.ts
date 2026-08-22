import { describe, expect, it } from 'vitest'

import { router } from './index'

describe('configuration library routes', () => {
  it('reuses the generic Configuration Library list for both Model Connection entries', () => {
    const libraryRoute = router.resolve('/library/model-connection').matched.at(-1)
    const systemRoute = router.resolve('/system/model-connections').matched.at(-1)

    expect(systemRoute?.components?.default).toBe(libraryRoute?.components?.default)
    expect(systemRoute?.props.default).toEqual({ fixedCategory: 'model-connection' })
  })
})
