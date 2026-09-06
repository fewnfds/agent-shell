import { describe, expect, it } from 'vitest'

import {
  blankMainAgent,
  blankSubagent,
  normalizeSubagentReference,
  overrideSelection,
  mainAgentPayload,
  setOverrideSelection,
  setReference,
  subagentPayload,
} from './agents'

describe('agent profile adapters', () => {
  it('keeps explicit UUID references and never derives them from names', () => {
    const draft = blankMainAgent()
    draft.name = 'Repeated display name'
    setReference(draft, 'model', '00000000-0000-0000-0000-000000000001')
    draft.subagents.push({ subagent_id: '00000000-0000-0000-0000-000000000020' })
    draft.async_subagents.push({
      main_agent_id: '00000000-0000-0000-0000-000000000030',
      name: ' researcher ',
      description: ' Research a topic. ',
    })

    expect(mainAgentPayload(draft)).toEqual({
      name: 'Repeated display name',
      is_model_entry: false,
      durability: 'async',
      on_disconnect: 'cancel',
      checkpoint_mode: 'enabled',
      capability_refs: [{
        type: 'model',
        block_id: '00000000-0000-0000-0000-000000000001',
      }],
      tool_refs: [],
      middleware_refs: [],
      mcp_refs: [],
      subagents: [{ subagent_id: '00000000-0000-0000-0000-000000000020' }],
      async_subagents: [{
        main_agent_id: '00000000-0000-0000-0000-000000000030',
        name: 'researcher',
        description: 'Research a topic.',
      }],
    })
  })

  it('stores only explicit replace or disabled override entries in settings', () => {
    const draft = blankSubagent()
    setOverrideSelection(draft, 'model', 'replace', '00000000-0000-0000-0000-000000000002')
    expect(overrideSelection(draft, 'model').mode).toBe('replace')

    setOverrideSelection(draft, 'model', 'inherit')
    expect(overrideSelection(draft, 'model').mode).toBe('inherit')
    expect(subagentPayload(draft).settings).toEqual({
      capability_overrides: [],
      tool_refs: [],
      middleware_refs: [],
      mcp_refs: [],
    })
  })

  it('projects component identity without nested Subagent references', () => {
    const draft = blankSubagent()
    draft.component_name = ' Research component '
    draft.name = ' researcher '
    draft.description = 'Research delegated topics.'
    expect(subagentPayload(draft)).toEqual({
      component_name: 'Research component',
      name: 'researcher',
      description: 'Research delegated topics.',
      settings: {
        capability_overrides: [],
        tool_refs: [],
        middleware_refs: [],
        mcp_refs: [],
      },
    })
  })

  it('normalizes only the current Subagent reference field', () => {
    expect(normalizeSubagentReference({
      subagent_id: '00000000-0000-0000-0000-000000000020',
      name: 'legacy field',
    })).toEqual({
      subagent_id: '00000000-0000-0000-0000-000000000020',
    })
  })
})
