import { ref } from 'vue'
import { describe, expect, it } from 'vitest'

import { useEditorModel } from './useEditorModel'

describe('useEditorModel', () => {
  it('keeps the local nested object when the parent echoes an emitted update', () => {
    const parent = ref({ nested: { value: 'initial' } })
    const draft = useEditorModel(
      () => parent.value,
      (value) => { parent.value = value },
    )
    const localNested = draft.nested

    draft.nested.value = 'edited'

    expect(parent.value).toEqual({ nested: { value: 'edited' } })
    expect(draft.nested).toBe(localNested)

    parent.value = { nested: { value: 'external' } }
    expect(draft.nested.value).toBe('external')
    expect(draft.nested).not.toBe(localNested)
  })
})
