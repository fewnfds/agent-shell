<script setup lang="ts">
import { LteAlert, LteButton } from '@adminlte/vue'
import { useI18n } from 'vue-i18n'

import FormField from '@/components/FormField.vue'
import ModalHost from '@/components/ModalHost.vue'

const props = withDefaults(defineProps<{
  open: boolean
  title: string
  formId: string
  name: string
  fieldPath?: string
  hint?: string
  description?: string
  error?: string
  errorTestId?: string
  busy?: boolean
  submitLabel: string
  busyLabel: string
}>(), {
  fieldPath: 'name',
  hint: '',
  description: '',
  error: '',
  errorTestId: undefined,
  busy: false,
})

const emit = defineEmits<{
  close: []
  submit: []
  'update:name': [value: string]
}>()

const { t } = useI18n()
</script>

<template>
  <ModalHost
    :description="props.description"
    :open="props.open"
    :title="props.title"
    @close="emit('close')"
  >
    <form :id="props.formId" novalidate @submit.prevent="emit('submit')">
      <FormField :field-path="props.fieldPath" :hint="props.hint">
        <input
          autocomplete="off"
          class="form-control"
          :value="props.name"
          @input="emit('update:name', ($event.target as HTMLInputElement).value)"
        >
      </FormField>
      <LteAlert
        v-if="props.error"
        :data-testid="props.errorTestId"
        theme="danger"
      >
        {{ props.error }}
      </LteAlert>
    </form>
    <template #footer>
      <LteButton class="action-button" :disabled="props.busy" type="button" @click="emit('close')">
        <i class="bi bi-x-lg" aria-hidden="true" />
        {{ t('common.cancel') }}
      </LteButton>
      <LteButton
        class="action-button"
        :disabled="props.busy"
        :form="props.formId"
        type="submit"
      >
        <span v-if="props.busy" class="spinner-border spinner-border-sm" aria-hidden="true" />
        <i v-else class="bi bi-copy" aria-hidden="true" />
        {{ props.busy ? props.busyLabel : props.submitLabel }}
      </LteButton>
    </template>
  </ModalHost>
</template>
