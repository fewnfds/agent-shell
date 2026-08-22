<script setup lang="ts">
import { LteButton, LteModal } from '@adminlte/vue'
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps<{
  open: boolean
  title: string
  description?: string
  size?: 'default' | 'wide'
}>()

const emit = defineEmits<{
  close: []
}>()
const { t } = useI18n()

const visible = ref(false)
const modalSize = computed<'lg' | 'xl'>(() => props.size === 'wide' ? 'xl' : 'lg')

watch(() => props.open, async (open) => {
  if (!open) {
    visible.value = false
    return
  }
  await nextTick()
  if (props.open) visible.value = true
}, { immediate: true })

function close(): void {
  visible.value = false
  if (props.open) emit('close')
}
</script>

<template>
  <LteModal
    centered
    :model-value="visible"
    :size="modalSize"
    scrollable
    :title="title"
    @close="close"
  >
    <template #header>
      <h5 class="modal-title">{{ title }}</h5>
      <LteButton
        class="icon-action-button ms-auto"
        :aria-label="t('common.close')"
        data-action="close-modal"
        :title="t('common.close')"
        size="sm"
        theme="secondary"
        type="button"
        @click="close"
      ><i class="bi bi-x-lg" aria-hidden="true" /></LteButton>
    </template>
    <p v-if="description" class="mb-3 text-body-secondary">
      {{ description }}
    </p>
    <slot />
    <template v-if="$slots.footer" #footer>
      <slot name="footer" />
    </template>
  </LteModal>
</template>
