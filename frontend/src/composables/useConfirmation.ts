import { readonly, ref } from 'vue'

export interface ConfirmationRequest {
  title: string
  description: string
  confirmLabel: string
  cancelLabel: string
  dangerous?: boolean
}

const current = ref<ConfirmationRequest | null>(null)
let resolvePending: ((accepted: boolean) => void) | null = null

export function useConfirmation() {
  function settle(accepted: boolean): void {
    const resolve = resolvePending
    resolvePending = null
    current.value = null
    resolve?.(accepted)
  }

  function confirm(request: ConfirmationRequest): Promise<boolean> {
    if (resolvePending) settle(false)
    current.value = request
    return new Promise<boolean>((resolve) => {
      resolvePending = resolve
    })
  }

  return {
    current: readonly(current),
    confirm,
    accept: () => settle(true),
    cancel: () => settle(false),
  }
}
