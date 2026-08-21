import { onMounted, onScopeDispose, readonly, ref } from 'vue'

import { managementApi, type ManagementEvent } from '@/api'

export interface ManagementEventSource {
  watchApiServerEvents(
    onEvent: (event: ManagementEvent) => void,
    onError?: (error: unknown) => void,
  ): () => void
}

export function useManagementEvents(
  onEvent: (event: ManagementEvent) => void,
  source: ManagementEventSource = managementApi,
  onReconnect?: () => void,
) {
  const connected = ref(false)
  const error = ref('')
  let stop: (() => void) | null = null
  let hasConnected = false

  function start(): void {
    stop?.()
    stop = source.watchApiServerEvents((event) => {
      error.value = ''
      if (event.type === 'event_stream_connected') {
        connected.value = true
        if (hasConnected) onReconnect?.()
        else hasConnected = true
        return
      }
      onEvent(event)
    }, (reason) => {
      connected.value = false
      error.value = reason instanceof Error ? reason.message : String(reason)
    })
  }

  function disconnect(): void {
    stop?.()
    stop = null
    connected.value = false
  }

  onMounted(start)
  onScopeDispose(disconnect)

  return {
    connected: readonly(connected),
    error: readonly(error),
    reconnect: start,
    disconnect,
  }
}
