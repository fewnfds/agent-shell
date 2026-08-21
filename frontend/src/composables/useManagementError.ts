import { useI18n } from 'vue-i18n'

import {
  ManagementApiError,
  ManagementAuthCancelledError,
  type JsonPrimitive,
} from '@/api'
import { useValidationIssuePresentation } from '@/composables/useValidationIssuePresentation'

export interface ManagementErrorPresentation {
  message: string
  validationIssues: string[]
  technicalDetail: string
  display: string
  messageKey: string
}

const frontendCodeKeys: Record<string, string> = {
  network_error: 'errors.network',
  invalid_json_response: 'errors.invalidJsonResponse',
  invalid_event_stream: 'errors.invalidEventStream',
  event_stream_unavailable: 'errors.eventStreamUnavailable',
}

export function useManagementError() {
  const { t } = useI18n()
  const issuePresentation = useValidationIssuePresentation()

  function messageKey(error: unknown, fallbackKey = 'errors.requestFailed'): string {
    if (error instanceof ManagementApiError) {
      return error.messageKey ?? frontendCodeKeys[error.code] ?? fallbackKey
    }
    if (error instanceof ManagementAuthCancelledError) return error.messageKey
    if (error instanceof DOMException && error.name === 'AbortError') return 'errors.requestCancelled'
    return fallbackKey
  }

  function messageArgs(error: unknown): Record<string, JsonPrimitive> {
    return error instanceof ManagementApiError ? error.messageArgs ?? {} : {}
  }

  function technicalDetail(error: unknown): string {
    if (!(error instanceof ManagementApiError)) return ''
    const details: string[] = []
    if (error.code) details.push(`${t('errors.codeLabel')}: ${error.code}`)
    if (error.requestId) details.push(`${t('errors.requestIdLabel')}: ${error.requestId}`)
    return details.join(t('common.itemSeparator'))
  }

  function validationIssues(error: unknown): string[] {
    if (!(error instanceof ManagementApiError) || !error.validation) return []
    return error.validation.issues.map((issue, index) => {
      const owner = issue.owner_name
        ? t('validation.location.namedOwner', {
            scope: t(`validation.scope.${issue.scope}`),
            name: issue.owner_name,
          })
        : t(`validation.scope.${issue.scope}`)
      const resolution = issuePresentation.resolution(issue)
      const lines = [
        `${index + 1}. ${t('validation.location.owner')}${t('common.detailSeparator')}${owner}`,
        ...(issue.path
          ? [`${t('validation.location.technicalPath')}${t('common.detailSeparator')}${issue.path}`]
          : []),
        `${t('validation.location.reason')}${t('common.detailSeparator')}${issuePresentation.message(issue)}`,
        ...(resolution
          ? [`${t('validation.location.resolution')}${t('common.detailSeparator')}${resolution}`]
          : []),
      ]
      return lines.join('\n')
    })
  }

  function describe(
    error: unknown,
    fallbackKey = 'errors.requestFailed',
  ): ManagementErrorPresentation {
    const key = messageKey(error, fallbackKey)
    const message = t(key, messageArgs(error))
    const issues = validationIssues(error)
    const technical = technicalDetail(error)
    const details = [...issues, ...(technical ? [technical] : [])]
    return {
      message,
      validationIssues: issues,
      technicalDetail: technical,
      display: details.length ? [message, ...details].join('\n') : message,
      messageKey: key,
    }
  }

  return { describe }
}
