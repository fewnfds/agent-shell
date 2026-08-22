<script setup lang="ts">
import { LteButton } from '@adminlte/vue'

import ModalHost from '@/components/ModalHost.vue'

withDefaults(defineProps<{
  open: boolean
  title: string
  description: string
  confirmLabel: string
  cancelLabel: string
  dangerous?: boolean
  busy?: boolean
}>(), {
  dangerous: false,
  busy: false,
})

const emit = defineEmits<{
  cancel: []
  confirm: []
}>()
</script>

<template>
  <ModalHost
    :description="description"
    :open="open"
    :title="title"
    @close="emit('cancel')"
  >
    <slot />
    <template #footer>
      <LteButton
        class="action-button"
        data-action="cancel"
        :disabled="busy"
        @click="emit('cancel')"
      >
        <i class="bi bi-x-lg" aria-hidden="true" />
        {{ cancelLabel }}
      </LteButton>
      <LteButton
        v-if="dangerous"
        class="action-button"
        data-action="delete"
        :disabled="busy"
        @click="emit('confirm')"
      >
        <i class="bi bi-trash" aria-hidden="true" />
        {{ confirmLabel }}
      </LteButton>
      <LteButton
        v-else
        class="action-button"
        data-action="confirm"
        :disabled="busy"
        @click="emit('confirm')"
      >
        <i class="bi bi-check-lg" aria-hidden="true" />
        {{ confirmLabel }}
      </LteButton>
    </template>
  </ModalHost>
</template>
