export interface BlockDraftBase {
  id: string
  name: string
}

export interface BlockPayloadBase {
  name: string
}

export function cleanName(value: string): string {
  return value.trim()
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}

export function stringValue(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback
}

export function identity(value: unknown): BlockDraftBase {
  const source = isRecord(value) ? value : {}
  return { id: stringValue(source.id), name: stringValue(source.name) }
}

export function uniqueStrings(values: readonly string[]): string[] {
  const seen = new Set<string>()
  return values.flatMap((value) => {
    const cleaned = value.trim()
    if (!cleaned || seen.has(cleaned)) return []
    seen.add(cleaned)
    return [cleaned]
  })
}

export function clone<T>(value: T): T {
  if (Array.isArray(value)) return value.map((item) => clone(item)) as T
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value).map(([key, child]) => [key, clone(child)]),
    ) as T
  }
  return value
}

export function overrideValue(value: string, defaultValue: string): string | null {
  return value === defaultValue ? null : value
}

export function editableText(value: unknown, defaultValue: string): string {
  return typeof value === 'string' ? value : defaultValue
}

export function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string')
    : []
}
