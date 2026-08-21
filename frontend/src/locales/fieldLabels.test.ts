import { describe, expect, it } from 'vitest'

import { fieldLabelKeys, normalizeFieldPath } from './fieldLabels'

describe('field label paths', () => {
  it('maps indexed validation paths to the shared item key', () => {
    expect(normalizeFieldPath('subagents[0].name')).toBe('subagents.item.name')
    expect(fieldLabelKeys('subagents.4.name')).toEqual([
      'fields.subagents.item.name.label',
      'fields.subagents.item.name',
      'fields.name.label',
      'fields.name',
    ])
  })

  it('uses the same key for a top-level form, validation issue, and library row', () => {
    expect(fieldLabelKeys('name')).toEqual(['fields.name.label', 'fields.name'])
  })
})
