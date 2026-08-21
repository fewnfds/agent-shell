function normalizeSearchText(value: string): string {
  return value.normalize('NFKC').toLowerCase().trim()
}

export function matchesSearchText(query: string, values: readonly string[]): boolean {
  const needle = normalizeSearchText(query)
  return !needle || values.some((value) => normalizeSearchText(value).includes(needle))
}
