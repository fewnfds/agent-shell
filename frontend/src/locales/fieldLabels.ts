export function normalizeFieldPath(path: string): string {
  return path
    .replace(/\[(\d+)]/g, '.$1')
    .split('.')
    .map((part) => /^\d+$/.test(part) ? 'item' : part)
    .filter(Boolean)
    .join('.')
}

export function fieldLabelKeys(path: string): string[] {
  const normalized = normalizeFieldPath(path)
  if (!normalized) return []
  const leaf = normalized.split('.').at(-1)
  const exact = `fields.${normalized}`
  const fallback = leaf ? `fields.${leaf}` : exact
  const candidates = [`${exact}.label`, exact]
  if (exact !== fallback) candidates.push(`${fallback}.label`, fallback)
  return candidates
}
