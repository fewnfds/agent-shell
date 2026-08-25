import {
  onScopeDispose,
  readonly,
  ref,
  watch,
  type DeepReadonly,
  type Ref,
  type WatchSource,
} from 'vue'

import type { ValidationReport } from '@/domain/agents'
import { useConfigurationValidationSettings } from './useConfigurationValidationSettings'

type ConfigurationValidationStatus = 'unavailable' | 'validating' | 'valid' | 'invalid'

export interface ConfigurationValidationState {
  status: ConfigurationValidationStatus
  report: ValidationReport | null
  error: string
}

interface ConfigurationValidationOptions<Request> {
  buildRequest: () => Request | null
  validate: (request: Request) => Promise<ValidationReport>
  source?: WatchSource<unknown>
  debounceMs?: number
  immediate?: boolean
  errorMessage?: (error: unknown) => string
  onSourceChange?: () => void
}

function state(
  status: ConfigurationValidationStatus,
  report: ValidationReport | null = null,
  error = '',
): ConfigurationValidationState {
  return { status, report, error }
}

function defaultErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

export function useConfigurationValidation<Request>(
  options: ConfigurationValidationOptions<Request>,
): {
  validation: DeepReadonly<Ref<ConfigurationValidationState>>
  schedule: (delay?: number) => void
  validateNow: () => Promise<ConfigurationValidationState>
  applyReport: (report: ValidationReport) => ConfigurationValidationState
} {
  const settings = useConfigurationValidationSettings()
  const errorMessage = options.errorMessage ?? defaultErrorMessage
  const validation = ref<ConfigurationValidationState>(state('unavailable'))
  let timer: ReturnType<typeof setTimeout> | undefined
  let sequence = 0

  function cancelPending(): number {
    sequence += 1
    if (timer !== undefined) {
      clearTimeout(timer)
      timer = undefined
    }
    return sequence
  }

  function applyReport(report: ValidationReport): ConfigurationValidationState {
    cancelPending()
    validation.value = state(report.valid ? 'valid' : 'invalid', report)
    return validation.value
  }

  async function run(currentSequence: number): Promise<ConfigurationValidationState> {
    let request: Request | null
    try {
      request = options.buildRequest()
      if (request === null) {
        if (currentSequence === sequence) validation.value = state('unavailable')
        return validation.value
      }
    } catch (error) {
      if (currentSequence === sequence) {
        validation.value = state('unavailable', null, errorMessage(error))
      }
      return validation.value
    }

    try {
      const report = await options.validate(request)
      if (currentSequence === sequence) {
        validation.value = state(report.valid ? 'valid' : 'invalid', report)
      }
    } catch (error) {
      if (currentSequence === sequence) {
        validation.value = state('unavailable', null, errorMessage(error))
      }
    }
    return validation.value
  }

  function schedule(delay = options.debounceMs ?? settings.debounceMs.value): void {
    const currentSequence = cancelPending()
    validation.value = state('validating')
    timer = setTimeout(() => {
      timer = undefined
      void run(currentSequence)
    }, delay)
  }

  async function validateNow(): Promise<ConfigurationValidationState> {
    const currentSequence = cancelPending()
    validation.value = state('validating')
    return run(currentSequence)
  }

  if (options.source) {
    watch(options.source, () => {
      options.onSourceChange?.()
      schedule()
    }, {
      deep: true,
      immediate: options.immediate ?? true,
    })
  } else if (options.immediate ?? true) {
    schedule(0)
  }

  onScopeDispose(() => {
    cancelPending()
  })

  return {
    validation: readonly(validation),
    schedule,
    validateNow,
    applyReport,
  }
}
