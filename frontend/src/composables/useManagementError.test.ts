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
  it('localizes backend keys and exposes only code and request id as technical detail', () => {
    const error = new ManagementApiError({
      status: 409,
      code: 'configuration_in_use',
      message: 'raw backend text must stay hidden',
      messageKey: 'backend.configurationInUse',
      messageArgs: { name: 'Main Agent' },
      requestId: 'request-123',
      payload: { traceback: 'hidden' },
    })

    const result = useManagementError().describe(error)
    expect(result.message).toBe('backend.configurationInUse:{"name":"Main Agent"}')
    expect(result.display).toContain('configuration_in_use')
    expect(result.display).toContain('request-123')
    expect(result.display).not.toContain('raw backend text')
    expect(result.display).not.toContain('traceback')
  })

  it('renders every safe structured validation issue before technical details', () => {
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
            code: 'assembly.reference_not_found',
            scope: 'main_agent',
            owner_id: 'main-agent-id',
            owner_name: 'Main Agent A',
            path: 'capability_refs.model',
            message: 'raw issue text',
            message_key: 'validation.issue.assembly.referenceNotFound',
            message_args: {},
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
    expect(result.display).toContain('validation.issue.assembly.referenceNotFound')
    expect(result.display).toContain('legacy_field')
    expect(result.display).toContain(
      'validation.issue.contract.unknownField:{"field":"legacy_field"}',
    )
    expect(result.display.indexOf('request-validation'))
      .toBeGreaterThan(result.display.indexOf('legacy_field'))
    expect(result.display).not.toContain('raw issue text')
  })

  it('uses stable frontend keys and a generic fallback instead of raw messages', () => {
    const network = new ManagementApiError({
      status: 0,
      code: 'network_error',
      message: 'host details',
    })
    expect(useManagementError().describe(network).message).toBe('errors.network')
    expect(useManagementError().describe(new Error('secret text')).message)
      .toBe('errors.requestFailed')
    expect(useManagementError().describe(new ManagementAuthCancelledError()).message)
      .toBe('errors.authenticationCancelled')
  })
})
