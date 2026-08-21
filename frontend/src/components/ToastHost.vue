<script setup lang="ts">
import { LteToast, type BootstrapTheme } from '@adminlte/vue'
import { useI18n } from 'vue-i18n'

import type { ToastMessage } from '@/components/toasts'

defineProps<{
  items: readonly ToastMessage[]
}>()

const emit = defineEmits<{
  dismiss: [id: string]
}>()

const { t } = useI18n()

function toastTheme(tone: ToastMessage['tone']): BootstrapTheme {
  return tone
}
</script>

<template>
  <aside
    :aria-label="t('feedback.dismiss')"
    aria-live="polite"
    class="toast-container toast-host position-fixed end-0 p-3"
  >
    <LteToast
      v-for="item in items"
      :key="item.id"
      :autohide="false"
      :model-value="true"
      :theme="toastTheme(item.tone)"
      :title="item.title"
      @hidden="emit('dismiss', item.id)"
    >
      <span v-if="item.message">{{ item.message }}</span>
    </LteToast>
  </aside>
</template>
