import { readonly, ref } from 'vue'

import type { ToastMessage, ToastTone } from '@/components/toasts'

const items = ref<ToastMessage[]>([])
let sequence = 0

export interface ToastInput {
  tone?: ToastTone
  title: string
  message?: string
  timeoutMs?: number
}

export function useToasts() {
  function dismiss(id: string): void {
    items.value = items.value.filter((item) => item.id !== id)
  }

  function notify(input: ToastInput): string {
    const id = `toast-${++sequence}`
    const tone = input.tone ?? 'info'
    items.value.push({
      id,
      tone,
      title: input.title,
      ...(input.message ? { message: input.message } : {}),
    })
    const timeout = input.timeoutMs ?? (tone === 'success' || tone === 'info' ? 5000 : 0)
    if (timeout > 0) window.setTimeout(() => dismiss(id), timeout)
    return id
  }

  return {
    items: readonly(items),
    dismiss,
    notify,
  }
}
