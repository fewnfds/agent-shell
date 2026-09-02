import { describe, expect, it } from 'vitest'

import { router } from './index'

describe('configuration library routes', () => {
  it('keeps global configuration entries under the Configuration Library route', () => {
    const libraryRoute = router.resolve('/library/model-connection').matched.at(-1)
    const globalModelRoute = router.resolve('/library/model-connection').matched.at(-1)
    const repositoryRoute = router.resolve('/library/configuration-repositories').matched.at(-1)
    const systemRoute = router.resolve('/system/model-connections').matched.at(-1)
    const mcpConnectionRoute = router.resolve('/mcp/connections').matched.at(-1)
    const mcpMappingRoute = router.resolve('/mcp/mapping').matched.at(-1)

    expect(globalModelRoute?.components?.default).toBe(libraryRoute?.components?.default)
    expect(repositoryRoute?.components?.default).not.toBe(libraryRoute?.components?.default)
    expect(systemRoute?.name).toBeUndefined()
    expect(mcpConnectionRoute?.props.default).toEqual({ scope: 'mcp' })
    expect(mcpMappingRoute?.components?.default).not.toBe(mcpConnectionRoute?.components?.default)
  })

  it('resolves a Lifecycle monitoring detail route and preserves its Run query', () => {
    const route = router.resolve(
      '/system/workflow-lifecycles/lifecycle-1/monitoring?run_id=run-2',
    )

    expect(route.params.lifecycleId).toBe('lifecycle-1')
    expect(route.query.run_id).toBe('run-2')
    expect(route.meta.titleKey).toBe('runtimeMonitoring.title')
  })
})
