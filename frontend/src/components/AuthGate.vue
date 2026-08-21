<script setup lang="ts">
import { LteButton } from '@adminlte/vue'
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { managementAuth, type ManagementAuthSnapshot } from '@/api'
import ModalHost from '@/components/ModalHost.vue'

const { t } = useI18n()
const snapshot = ref<ManagementAuthSnapshot>(managementAuth.getSnapshot())
const token = ref('')
const emptySubmission = ref(false)
const input = ref<HTMLInputElement | null>(null)
let unsubscribe: (() => void) | null = null
let receivedInitialSnapshot = false

const messageKey = computed(() => snapshot.value.reason === 'invalid'
  ? 'auth.invalidMessage'
  : 'auth.requiredMessage')

async function focusInput(): Promise<void> {
  await nextTick()
  input.value?.focus()
}

function submit(): void {
  if (!managementAuth.submit(token.value)) {
    emptySubmission.value = true
    void focusInput()
    return
  }
  token.value = ''
  emptySubmission.value = false
}

function cancel(): void {
  token.value = ''
  emptySubmission.value = false
  managementAuth.cancel()
}

onMounted(() => {
  unsubscribe = managementAuth.subscribe((nextSnapshot) => {
    const shouldFocus = nextSnapshot.open
      && (
        !receivedInitialSnapshot
        || !snapshot.value.open
        || snapshot.value.reason !== nextSnapshot.reason
      )
    receivedInitialSnapshot = true
    snapshot.value = nextSnapshot
    if (shouldFocus) void focusInput()
  })
})

onUnmounted(() => unsubscribe?.())
</script>

<template>
  <ModalHost
    :open="snapshot.open"
    :title="t('auth.title')"
    @close="cancel"
  >
    <p class="mb-3 text-body-secondary">
      {{ t(messageKey) }}
    </p>
    <form @submit.prevent="submit">
      <div class="mb-3">
        <label class="form-label" for="management-auth-token">
          {{ t('auth.tokenLabel') }}
        </label>
        <input
          id="management-auth-token"
          ref="input"
          v-model="token"
          :aria-invalid="emptySubmission"
          autocomplete="off"
          class="form-control"
          spellcheck="false"
          type="password"
        >
        <div v-if="emptySubmission" class="d-block invalid-feedback">
          {{ t('auth.emptyToken') }}
        </div>
        <div class="form-text">
          {{ t('auth.memoryOnlyHint') }}
        </div>
      </div>
    </form>
    <template #footer>
      <LteButton theme="warning" @click="cancel">
        {{ t('auth.cancel') }}
      </LteButton>
      <LteButton theme="primary" @click="submit">
        {{ t('auth.submit') }}
      </LteButton>
    </template>
  </ModalHost>
</template>
