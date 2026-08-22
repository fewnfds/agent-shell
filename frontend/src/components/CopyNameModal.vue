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
      <LteButton :disabled="props.busy" theme="warning" type="button" @click="emit('close')">
        {{ t('common.cancel') }}
      </LteButton>
      <LteButton
        :disabled="props.busy"
        :form="props.formId"
        theme="primary"
        type="submit"
      >
        <span v-if="props.busy" class="spinner-border spinner-border-sm" aria-hidden="true" />
        {{ props.busy ? props.busyLabel : props.submitLabel }}
      </LteButton>
    </template>
  </ModalHost>
</template>
