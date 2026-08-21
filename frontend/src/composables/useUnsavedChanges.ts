import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'

import { useConfirmation } from '@/composables/useConfirmation'

interface UnsavedChangesLabels {
  title: string
  description: string
  confirmLabel: string
  cancelLabel: string
}

function serialize(value: unknown): string {
  return JSON.stringify(value)
}

export function useUnsavedChanges(
  snapshot: () => unknown,
  labels: () => UnsavedChangesLabels,
) {
  const { confirm } = useConfirmation()
  const baseline = ref('')
  const tracking = ref(false)
  let allowNextNavigation = false

  const isDirty = computed(() => (
    tracking.value && serialize(snapshot()) !== baseline.value
  ))

  function markClean(): void {
    baseline.value = serialize(snapshot())
    tracking.value = true
  }

  async function confirmDiscard(): Promise<boolean> {
    if (!isDirty.value) return true
    const copy = labels()
    return confirm({
      title: copy.title,
      description: copy.description,
      confirmLabel: copy.confirmLabel,
      cancelLabel: copy.cancelLabel,
      dangerous: true,
    })
  }

  async function runAfterDiscard(action: () => void | Promise<void>): Promise<boolean> {
    if (!await confirmDiscard()) return false
    allowNextNavigation = true
    try {
      await action()
      return true
    } finally {
      allowNextNavigation = false
    }
  }

  async function guardRoute(): Promise<boolean> {
    if (allowNextNavigation) return true
    return confirmDiscard()
  }

  function guardUnload(event: BeforeUnloadEvent): void {
    if (!isDirty.value) return
    event.preventDefault()
    event.returnValue = ''
  }

  onBeforeRouteUpdate(guardRoute)
  onBeforeRouteLeave(guardRoute)
  onMounted(() => window.addEventListener('beforeunload', guardUnload))
  onBeforeUnmount(() => window.removeEventListener('beforeunload', guardUnload))

  return { isDirty, markClean, runAfterDiscard }
}
