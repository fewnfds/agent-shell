import {
  getCurrentInstance,
  inject,
  provide,
  readonly,
  ref,
  type DeepReadonly,
  type InjectionKey,
  type Ref,
} from 'vue'

import type { ConfigurationValidationSettings } from '@/api'

const DEFAULT_VALIDATION_DEBOUNCE_MS = 1000

interface ConfigurationValidationSettingsApi {
  getValidationSettings(): Promise<ConfigurationValidationSettings>
}

export interface ConfigurationValidationSettingsController {
  debounceMs: DeepReadonly<Ref<number>>
  load: () => Promise<void>
  apply: (settings: ConfigurationValidationSettings) => void
}

const configurationValidationSettingsKey: InjectionKey<ConfigurationValidationSettingsController> = Symbol(
  'configuration-validation-settings',
)

const fallbackDebounceMs = ref(DEFAULT_VALIDATION_DEBOUNCE_MS)
const fallbackController: ConfigurationValidationSettingsController = {
  debounceMs: readonly(fallbackDebounceMs),
  load: async () => undefined,
  apply: (settings) => {
    fallbackDebounceMs.value = settings.debounce_ms
  },
}

export function provideConfigurationValidationSettings(
  api: ConfigurationValidationSettingsApi,
): ConfigurationValidationSettingsController {
  const debounceMs = ref(DEFAULT_VALIDATION_DEBOUNCE_MS)
  let loadSequence = 0

  function apply(settings: ConfigurationValidationSettings): void {
    debounceMs.value = settings.debounce_ms
  }

  async function load(): Promise<void> {
    const sequence = ++loadSequence
    try {
      const settings = await api.getValidationSettings()
      if (sequence === loadSequence) apply(settings)
    } catch {
      // Keep the existing one-second default while management auth is unavailable.
    }
  }

  const controller: ConfigurationValidationSettingsController = {
    debounceMs: readonly(debounceMs),
    load,
    apply,
  }
  provide(configurationValidationSettingsKey, controller)
  return controller
}

export function useConfigurationValidationSettings(): ConfigurationValidationSettingsController {
  if (!getCurrentInstance()) return fallbackController
  return inject(configurationValidationSettingsKey, fallbackController)
}
