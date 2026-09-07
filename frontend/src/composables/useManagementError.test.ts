import { describe, expect, it, vi } from 'vitest'

import { ManagementApiError, ManagementAuthCancelledError } from '@/api'

import { useManagementError } from './useManagementError'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    locale: { value: 'en' },
    t: (key: string, args?: Record<string, unknown>) => {
      if (key === 'common.itemSeparator') return '、'
      if (key === 'common.detailSeparator') return '：'
      return args && Object.keys(args).length
        ? `${key}:${JSON.stringify(args)}`
        : key
    },
    te: (key: string) => key.startsWith('validation.issue.') || ['fields.name'].includes(key),
  }),
}))

describe('useManagementError', () => {
  it('keeps the localized heading, backend reason, and complete technical payload', () => {
    const error = new ManagementApiError({
      status: 409,
      code: 'configuration_in_use',
      message: 'raw backend text remains visible',
      messageKey: 'backend.configurationInUse',
      messageArgs: { name: 'Main Agent' },
      requestId: 'request-123',
      payload: { traceback: 'complete traceback' },
    })

    const result = useManagementError().describe(error)
    expect(result.message).toBe('backend.configurationInUse:{"name":"Main Agent"}')
    expect(result.display).toContain('configuration_in_use')
    expect(result.display).toContain('request-123')
    expect(result.reason).toBe('raw backend text remains visible')
    expect(result.display).toContain('raw backend text remains visible')
    expect(result.display).toContain('traceback')
    expect(result.display).toContain('complete traceback')
  })

  it('renders every structured validation issue with its backend reason', () => {
    const error = new ManagementApiError({
      status: 422,
      code: 'configuration_validation_failed',
      message: 'raw backend validation text',
      messageKey: 'validation.failure.configuration',
      requestId: 'request-validation',
      validation: {
        valid: false,
        stage: 'api_start',
        issues: [
          {
            code: 'configuration.reference_not_found',
            scope: 'main_agent',
            owner_id: 'main-agent-id',
            owner_name: 'Main Agent A',
            path: 'capability_refs.model',
            message: 'raw issue text',
            message_key: 'validation.issue.configuration.referenceNotFound',
            message_args: { expected_type: 'model', reference_id: 'missing-model-id' },
          },
          {
            code: 'contract.unknown_field',
            scope: 'block',
            owner_id: 'block-id',
            owner_name: 'Old output',
            path: 'legacy_field',
            message: 'raw issue text 2',
            message_key: 'validation.issue.contract.unknownField',
            message_args: {},
          },
        ],
      },
    })

    const result = useManagementError().describe(error)

    expect(result.validationIssues).toHaveLength(2)
    expect(result.display).toContain('validation.location.namedOwner')
    expect(result.display).toContain('capability_refs.model')
    expect(result.display).toContain('raw issue text')
    expect(result.display).toContain('legacy_field')
    expect(result.display).toContain('raw issue text 2')
    expect(result.display.indexOf('request-validation'))
      .toBeGreaterThan(result.display.indexOf('legacy_field'))
    expect(result.display).toContain('raw backend validation text')
  })

  it('uses stable frontend headings without discarding raw error messages', () => {
    const network = new ManagementApiError({
      status: 0,
      code: 'network_error',
      message: 'host details',
    })
    expect(useManagementError().describe(network).message).toBe('errors.network')
    expect(useManagementError().describe(network).display).toContain('host details')
    const generic = useManagementError().describe(new Error('concrete failure'))
    expect(generic.message).toBe('errors.requestFailed')
    expect(generic.display).toContain('concrete failure')
    expect(useManagementError().describe(new ManagementAuthCancelledError()).message)
      .toBe('errors.authenticationCancelled')
  })
})
