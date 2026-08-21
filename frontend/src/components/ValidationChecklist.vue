<script setup lang="ts">
import { LteAccordion, LteAccordionItem, LteAlert } from '@adminlte/vue'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { ConfigurationValidationState } from '@/composables/useConfigurationValidation'
import { useValidationIssuePresentation } from '@/composables/useValidationIssuePresentation'

const props = defineProps<{
  title: string
  validation: Readonly<ConfigurationValidationState>
}>()

const { t } = useI18n()
const issuePresentation = useValidationIssuePresentation()

const validationStatus = computed(() => props.validation.status)
const issueCount = computed(() => props.validation.report?.issues.length ?? 0)
const warningCount = computed(() => props.validation.report?.issues.filter(
  (issue) => issue.severity === 'warning',
).length ?? 0)
const hasWarnings = computed(() => warningCount.value > 0)
const detailSeparator = computed(() => {
  const separator = t('common.detailSeparator')
  return separator === 'common.detailSeparator' ? ': ' : separator
})
</script>

<template>
  <section
    v-if="validationStatus === 'invalid' || validationStatus === 'unavailable' || hasWarnings"
    class="card card-outline mb-3"
    aria-live="polite"
    :data-status="validationStatus"
    data-testid="validation-checklist"
  >
    <header class="card-header d-flex align-items-center gap-2">
      <i v-if="validationStatus === 'invalid' || validationStatus === 'unavailable'" class="bi bi-exclamation-triangle text-danger" aria-hidden="true" />
      <i v-else class="bi bi-info-circle" aria-hidden="true" />
      <div class="lh-sm">
        <h2 class="h5 mb-1 fw-semibold">{{ title }}</h2>
        <p v-if="validationStatus === 'invalid'" class="small text-body-secondary mb-0">
          {{ t('validation.issueSummary', { count: issueCount }) }}
        </p>
        <p v-else-if="hasWarnings" class="small text-body-secondary mb-0">
          {{ t('validation.warningSummary', { count: warningCount }) }}
        </p>
      </div>
    </header>

    <div v-if="validationStatus === 'unavailable'" class="card-body">
      <LteAlert
        theme="danger"
        :title="validation.error || t('validation.unavailableDetail')"
      />
    </div>
    <LteAccordion v-else always-open flush>
      <LteAccordionItem
        v-for="(issue, index) in validation.report?.issues ?? []"
        :id="`validation-issue-${index}`"
        :key="`${issue.scope}:${issue.owner_id}:${issue.path}:${issue.code}:${index}`"
        :title="issuePresentation.message(issue)"
        data-testid="validation-issue"
      >
        <div class="text-break">
          <p class="mb-2" data-testid="validation-owner-line">
            <span class="fw-semibold">{{ t('validation.location.owner') }}{{ detailSeparator }}</span><span data-testid="validation-owner">{{ issuePresentation.ownerLabel(issue) }}</span>
          </p>
          <p class="mb-2" data-testid="validation-location-line">
            <span class="fw-semibold">{{ t('validation.location.problemLocation') }}{{ detailSeparator }}</span><span data-testid="validation-location">{{ issuePresentation.location(issue) }}</span>
          </p>
          <p v-if="issue.path" class="mb-2" data-testid="validation-technical-path-line">
            <span class="fw-semibold">{{ t('validation.location.technicalPath') }}{{ detailSeparator }}</span><span class="font-monospace" data-testid="validation-technical-path">{{ issue.path }}</span>
          </p>
          <p class="mb-2" data-testid="validation-reason-line">
            <span class="fw-semibold">{{ t('validation.location.reason') }}{{ detailSeparator }}</span><span data-testid="validation-reason">{{ issuePresentation.message(issue) }}</span>
          </p>
          <p class="mb-0" data-testid="validation-resolution-line">
            <span class="fw-semibold">{{ t('validation.location.resolution') }}{{ detailSeparator }}</span><span data-testid="validation-resolution">{{ issuePresentation.resolution(issue) }}</span>
          </p>
          <div v-if="$slots['issue-actions']" class="d-flex flex-wrap gap-2 mt-3">
            <slot name="issue-actions" :issue="issue" />
          </div>
        </div>
      </LteAccordionItem>
    </LteAccordion>
  </section>

  <section
    v-else
    class="card mb-3"
    :aria-busy="validationStatus === 'validating'"
    aria-live="polite"
    :data-status="validationStatus"
    data-testid="validation-checklist"
  >
    <header class="card-header d-flex align-items-center gap-2">
      <i
        v-if="validationStatus === 'valid'"
        class="bi bi-check-circle text-success"
        aria-hidden="true"
      />
      <i v-else class="bi bi-arrow-clockwise" aria-hidden="true" />
      <h2 class="h5 mb-0 fw-semibold">{{ title }}</h2>
    </header>
    <div v-if="validationStatus === 'validating'" class="card-body">
      <LteAlert theme="info" :title="t('validation.validatingDetail')" />
    </div>
  </section>
</template>
