import { ref } from 'vue'

import type { CapabilityManifest, CatalogResponse, WorkflowComponentManifest } from '@/api'

export type ConfigurationCatalogManifest = CapabilityManifest | WorkflowComponentManifest

export function useConfigurationCatalog(
  loadCatalogRequest: () => Promise<CatalogResponse>,
  describeError: (error: unknown) => string,
) {
  const manifests = ref<ConfigurationCatalogManifest[]>([])
  const ready = ref(false)
  const error = ref('')

  async function load(): Promise<void> {
    error.value = ''
    ready.value = false
    try {
      const catalog = await loadCatalogRequest()
      manifests.value = [
        ...catalog.block_types,
        ...catalog.workflow_component_types,
      ].sort((left, right) => left.order - right.order)
    } catch (cause) {
      manifests.value = []
      error.value = describeError(cause)
    } finally {
      ready.value = true
    }
  }

  return { manifests, ready, error, load }
}

