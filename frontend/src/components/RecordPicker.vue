<script setup lang="ts">
import { LteInput } from '@adminlte/vue'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import FormField from '@/components/FormField.vue'

interface RecordOption {
  id: string
  name: string
}

const props = withDefaults(defineProps<{
  disabled?: boolean
  modelValue: string
  name: string
  records: readonly RecordOption[]
}>(), {
  disabled: false,
})

const emit = defineEmits<{
  select: [value: string]
  'update:name': [value: string]
}>()

const { t } = useI18n()
const nameMissing = computed(() => !props.disabled && !props.name.trim())
const nameError = computed(() => nameMissing.value ? ' ' : '')

function selectRecord(event: Event): void {
  emit('select', (event.target as HTMLSelectElement).value)
}

function updateName(value: string | number | undefined): void {
  emit('update:name', String(value ?? ''))
}
</script>

<template>
  <section class="row g-3">
    <div class="col-md-6">
      <FormField field-path="id" label-key="common.recordPicker.load">
        <select
          class="form-select"
          data-testid="record-picker-select"
          :disabled="disabled"
          :value="modelValue"
          @change="selectRecord"
        >
          <option value="">{{ t('common.recordPicker.newOption') }}</option>
          <option v-for="record in records" :key="record.id" :value="record.id">
            {{ record.name }}
          </option>
        </select>
      </FormField>
    </div>
    <div class="col-md-6">
      <LteInput
        autocomplete="off"
        data-field="record-name"
        :aria-invalid="nameMissing || undefined"
        :disabled="disabled"
        :error="nameError"
        fgroup-class="record-picker-name-field"
        :label="t('common.recordPicker.name')"
        :model-value="name"
        required
        @update:model-value="updateName"
      />
    </div>
  </section>
</template>
