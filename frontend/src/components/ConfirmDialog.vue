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
        :disabled="busy"
        theme="warning"
        @click="emit('cancel')"
      >
        {{ cancelLabel }}
      </LteButton>
      <LteButton
        v-if="dangerous"
        :disabled="busy"
        theme="danger"
        @click="emit('confirm')"
      >
        {{ confirmLabel }}
      </LteButton>
      <LteButton
        v-else
        :disabled="busy"
        theme="primary"
        @click="emit('confirm')"
      >
        {{ confirmLabel }}
      </LteButton>
    </template>
  </ModalHost>
</template>
