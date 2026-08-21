<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { fieldLabelKeys } from '@/locales/fieldLabels'

const props = defineProps<{
  controlId?: string
  error?: string
  fieldPath: string
  hint?: string
  labelKey?: string
  technical?: boolean
}>()

const { locale, t, te } = useI18n()

const label = computed(() => {
  if (locale.value === 'debug') return props.fieldPath
  if (props.technical) return props.fieldPath.split('.').at(-1) ?? props.fieldPath
  const keys = props.labelKey ? [props.labelKey] : fieldLabelKeys(props.fieldPath)
  const key = keys.find((candidate) => te(candidate))
  return key ? t(key) : props.fieldPath
})
const technicalLabel = computed(() => props.technical || locale.value === 'debug')
const hintId = computed(() => props.controlId && props.hint ? `${props.controlId}-help` : undefined)
const errorId = computed(() => props.controlId && props.error ? `${props.controlId}-error` : undefined)
const describedBy = computed(() => [hintId.value, errorId.value].filter(Boolean).join(' ') || undefined)
</script>

<template>
  <div class="mb-3" data-ui-pattern="form-field">
    <label v-if="controlId && technicalLabel" class="form-label d-block font-monospace" data-ui-slot="label" :for="controlId">
      {{ label }}
    </label>
    <label v-else-if="controlId" class="form-label d-block" data-ui-slot="label" :for="controlId">
      {{ label }}
    </label>
    <span v-else-if="technicalLabel" class="form-label d-block font-monospace" data-ui-slot="label">
      {{ label }}
    </span>
    <span v-else class="form-label d-block" data-ui-slot="label">
      {{ label }}
    </span>
    <slot :control-id="controlId" :described-by="describedBy" :invalid="Boolean(error)" />
    <div v-if="hint" :id="hintId" class="form-text" data-ui-slot="help">{{ hint }}</div>
    <div v-if="error" :id="errorId" class="invalid-feedback d-block" data-ui-slot="error">{{ error }}</div>
  </div>
</template>
