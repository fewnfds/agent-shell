import { describe, expect, it } from 'vitest'

import { glossaryEntries } from './entries'
import { glossaryEntry, searchGlossary } from './search'

describe('typed glossary data', () => {
  it('contains unique keys and complete bilingual source records', () => {
    expect(new Set(glossaryEntries.map((entry) => entry.key)).size).toBe(glossaryEntries.length)
    for (const entry of glossaryEntries) {
      expect(entry.english).not.toBe('')
      expect(entry.zh).not.toBe('')
      expect(entry.descriptionZh).not.toBe('')
      expect(entry.descriptionEn).not.toBe('')
      expect(entry.variants.length).toBeGreaterThan(0)
      expect(entry.sources.length).toBeGreaterThan(0)
      expect(entry.sources.every((source) => source.url.startsWith('https://'))).toBe(true)
    }
  })

  it('searches English, variants, Chinese, and both explanations', () => {
    expect(searchGlossary('Agent Loop').some((entry) => entry.key === 'agent-loop')).toBe(true)
    expect(searchGlossary('agent_loop').some((entry) => entry.key === 'agent-loop')).toBe(true)
    expect(searchGlossary('上下文工程').some((entry) => entry.key === 'context-engineering')).toBe(true)
    expect(searchGlossary('目标为导向').some((entry) => entry.key === 'agent')).toBe(true)
    expect(searchGlossary('goal-directed computational system').map((entry) => entry.key)).toEqual(['agent'])
    expect(glossaryEntry('agent')?.english).toBe('Agent')
  })
})
