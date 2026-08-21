import { glossaryEntries } from './entries'
import type { GlossaryEntry } from './types'
import { matchesSearchText } from '@/utils/search'

export function searchGlossary(
  query: string,
  entries: readonly GlossaryEntry[] = glossaryEntries,
): GlossaryEntry[] {
  return entries.filter((entry) => matchesSearchText(query, [
    entry.english,
    entry.zh,
    entry.descriptionZh,
    entry.descriptionEn,
    ...entry.variants,
  ]))
}

const entriesByKey = new Map(glossaryEntries.map((entry) => [entry.key, entry]))

export function glossaryEntry(key: string): GlossaryEntry | undefined {
  return entriesByKey.get(key)
}
