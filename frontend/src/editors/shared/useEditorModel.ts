import { reactive, watch } from 'vue'

function clone<T>(value: T): T {
  if (Array.isArray(value)) return value.map((item) => clone(item)) as T
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value).map(([key, child]) => [key, clone(child)]),
    ) as T
  }
  return value
}

function replaceObject<T extends object>(target: T, source: T): void {
  for (const key of Object.keys(target) as Array<keyof T>) delete target[key]
  Object.assign(target, clone(source))
}

export function useEditorModel<T extends object>(
  readModel: () => T,
  onUpdate: (value: T) => void,
): T {
  const draft = reactive(clone(readModel())) as T
  let syncing = false

  watch(readModel, (value) => {
    syncing = true
    replaceObject(draft, value)
    syncing = false
  }, { deep: true, flush: 'sync' })

  watch(draft, (value) => {
    if (!syncing) onUpdate(clone(value as T))
  }, { deep: true, flush: 'sync' })

  return draft
}
