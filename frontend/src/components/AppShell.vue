<script setup lang="ts">
import { LteSidebarNav, provideColorMode, type ColorMode, type MenuNode } from '@adminlte/vue'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink, RouterView, useRoute } from 'vue-router'

import {
  managementApi,
  type ApiServerSettings,
  type ConfigurationValidationSettings,
  type ManagementEvent,
} from '@/api'
import { provideConfigurationValidationSettings } from '@/composables/useConfigurationValidationSettings'
import {
  useManagementEvents,
  type ManagementEventSource,
} from '@/composables/useManagementEvents'
import { useManagementError } from '@/composables/useManagementError'
import { useToasts } from '@/composables/useToasts'
import { setLocale, type SupportedLocale } from '@/locales'
import { navigationItems } from '@/navigation'

interface AppShellApi extends ManagementEventSource {
  getApiServer(): Promise<ApiServerSettings>
  getValidationSettings(): Promise<ConfigurationValidationSettings>
  startApiServer(): Promise<ApiServerSettings>
  stopApiServer(): Promise<ApiServerSettings>
}

const props = defineProps<{ api?: AppShellApi }>()
const { locale, t } = useI18n()
const route = useRoute()
const { colorMode, setColorMode } = provideColorMode({ initialMode: 'auto' })
const api = props.api ?? managementApi
const validationSettings = provideConfigurationValidationSettings(api)
const managementError = useManagementError()
const { notify } = useToasts()
const mainContent = ref<HTMLElement | null>(null)
const apiServerSettings = ref<ApiServerSettings | null>(null)
const apiServerLoading = ref(true)
const lifecycleAction = ref<'start' | 'stop' | ''>('')
const menuItems = computed<MenuNode[]>(() => navigationItems.map((item) => ({
  type: 'item',
  text: t(item.labelKey),
  href: item.path,
  icon: item.icon,
})))
const pageTitle = computed(() => {
  const titleKey = route.meta.titleKey
  return typeof titleKey === 'string' ? t(titleKey) : ''
})

const themeOrder: ColorMode[] = ['light', 'dark', 'auto']
const nextColorMode = computed<ColorMode>(() => {
  const index = themeOrder.indexOf(colorMode.value)
  return themeOrder[(index + 1) % themeOrder.length] ?? 'light'
})
const themeButtonLabel = computed(() => t('preferences.themeToggle', {
  current: t(`preferences.themes.${colorMode.value}`),
  next: t(`preferences.themes.${nextColorMode.value}`),
}))
const localeOrder: SupportedLocale[] = ['zh-CN', 'en', 'debug']
const localeSwitchKeys: Record<SupportedLocale, string> = {
  'zh-CN': 'preferences.switchToChinese',
  en: 'preferences.switchToEnglish',
  debug: 'preferences.switchToVariables',
}
const nextLocale = computed<SupportedLocale>(() => {
  const index = localeOrder.indexOf(locale.value as SupportedLocale)
  return localeOrder[(index + 1) % localeOrder.length] ?? 'zh-CN'
})
const localeButtonLabel = computed(() => t(localeSwitchKeys[nextLocale.value]))
const apiServerRunning = computed(() => (
  apiServerSettings.value?.enabled === true
  && apiServerSettings.value.status === 'running'
))
const apiServerStatusLabel = computed(() => {
  if (!apiServerSettings.value) return t('apiServer.navbar.unavailable')
  return t(apiServerRunning.value
    ? 'apiServer.navbar.runningAction'
    : 'apiServer.navbar.stoppedAction')
})

function toggleLocale(): void {
  setLocale(nextLocale.value)
}

function toggleTheme(): void {
  setColorMode(nextColorMode.value)
}

async function loadApiServer(): Promise<void> {
  apiServerLoading.value = true
  try {
    apiServerSettings.value = await api.getApiServer()
  } catch {
    apiServerSettings.value = null
  } finally {
    apiServerLoading.value = false
  }
}

async function changeLifecycle(action: 'start' | 'stop'): Promise<void> {
  lifecycleAction.value = action
  try {
    apiServerSettings.value = action === 'start'
      ? await api.startApiServer()
      : await api.stopApiServer()
    notify({
      tone: 'success',
      title: t(action === 'start' ? 'apiServer.started' : 'apiServer.stopped'),
    })
  } catch (error) {
    notify({
      tone: 'danger',
      title: t(action === 'start' ? 'apiServer.startFailed' : 'apiServer.stopFailed'),
      message: managementError.describe(error).display,
    })
  } finally {
    lifecycleAction.value = ''
  }
}

function onManagementEvent(event: ManagementEvent): void {
  if (
    event.type === 'settings_changed'
    || event.type === 'message_interception_changed'
  ) {
    void loadApiServer()
  }
  if (event.type === 'settings_changed') {
    void validationSettings.load()
  }
}

function isNarrow(): boolean {
  return window.matchMedia('(max-width: 991.98px)').matches
}

function toggleSidebar(): void {
  if (isNarrow()) {
    document.body.classList.toggle('sidebar-open')
    return
  }
  document.body.classList.toggle('sidebar-collapse')
}

function closeNarrowSidebar(): void {
  if (isNarrow()) document.body.classList.remove('sidebar-open')
}

watch(() => route.fullPath, async () => {
  closeNarrowSidebar()
  await nextTick()
  mainContent.value?.focus({ preventScroll: true })
})

useManagementEvents(onManagementEvent, api, () => {
  void loadApiServer()
  void validationSettings.load()
})

onMounted(() => {
  document.body.classList.add('layout-fixed', 'sidebar-expand-lg', 'sidebar-mini', 'bg-body-tertiary')
  void loadApiServer()
  void validationSettings.load()
})

onBeforeUnmount(() => {
  document.body.classList.remove('sidebar-open', 'sidebar-collapse')
})
</script>

<template>
  <div class="app-wrapper">
    <a class="visually-hidden-focusable" href="#main-content">
      {{ t('navigation.skipToContent') }}
    </a>

    <header class="app-header navbar navbar-expand bg-body border-bottom">
      <div class="container-fluid">
        <ul class="navbar-nav">
          <li class="nav-item">
            <button
              type="button"
              class="nav-link"
              :aria-label="t('navigation.toggleSidebar')"
              @click="toggleSidebar"
            >
              <i class="bi bi-list" aria-hidden="true" />
            </button>
          </li>
        </ul>
        <h1 class="app-page-title mb-0">
          {{ pageTitle }}
        </h1>

        <ul class="navbar-nav ms-auto">
          <li class="nav-item me-2">
            <button
              id="app-language"
              type="button"
              class="nav-link"
              :aria-label="localeButtonLabel"
              :title="localeButtonLabel"
              @click="toggleLocale"
            >
              <i class="bi bi-translate" aria-hidden="true" />
            </button>
          </li>

          <li class="nav-item me-2">
            <button
              id="app-theme"
              class="nav-link"
              type="button"
              :aria-label="themeButtonLabel"
              :title="themeButtonLabel"
              @click="toggleTheme"
            >
              <i v-if="colorMode === 'light'" class="bi bi-sun-fill" aria-hidden="true" />
              <i v-else-if="colorMode === 'dark'" class="bi bi-moon-fill" aria-hidden="true" />
              <i v-else class="bi bi-circle-half" aria-hidden="true" />
            </button>
          </li>

          <li class="nav-item">
            <button
              v-if="apiServerRunning && apiServerSettings?.message_interception_enabled"
              id="app-api-server-status"
              class="nav-link api-status-indicator api-status-indicator--intercepting"
              type="button"
              :aria-label="apiServerStatusLabel"
              :title="apiServerStatusLabel"
              :disabled="apiServerLoading || Boolean(lifecycleAction)"
              @click="changeLifecycle('stop')"
            >
              <span v-if="lifecycleAction" class="spinner-border spinner-border-sm" aria-hidden="true" />
              <i v-else class="bi bi-play-fill" aria-hidden="true" />
            </button>
            <button
              v-else-if="apiServerRunning"
              id="app-api-server-status"
              class="nav-link api-status-indicator api-status-indicator--running"
              type="button"
              :aria-label="apiServerStatusLabel"
              :title="apiServerStatusLabel"
              :disabled="apiServerLoading || Boolean(lifecycleAction)"
              @click="changeLifecycle('stop')"
            >
              <span v-if="lifecycleAction" class="spinner-border spinner-border-sm" aria-hidden="true" />
              <i v-else class="bi bi-play-fill" aria-hidden="true" />
            </button>
            <button
              v-else
              id="app-api-server-status"
              class="nav-link api-status-indicator api-status-indicator--stopped"
              type="button"
              :aria-label="apiServerStatusLabel"
              :title="apiServerStatusLabel"
              :disabled="apiServerLoading || !apiServerSettings || Boolean(lifecycleAction)"
              @click="changeLifecycle('start')"
            >
              <span v-if="apiServerLoading || lifecycleAction" class="spinner-border spinner-border-sm" aria-hidden="true" />
              <i v-else class="bi bi-stop-fill" aria-hidden="true" />
            </button>
          </li>
        </ul>
      </div>
    </header>

    <aside class="app-sidebar bg-body-secondary shadow">
      <div class="sidebar-brand">
        <RouterLink class="brand-link" to="/">
          <strong class="brand-text">{{ t('app.name') }}</strong>
        </RouterLink>
      </div>
      <div class="sidebar-wrapper">
        <LteSidebarNav
          :current-path="route.path"
          :items="menuItems"
          link-component="RouterLink"
        />
      </div>
    </aside>

    <main
      id="main-content"
      ref="mainContent"
      class="app-main"
      tabindex="-1"
    >
      <RouterView />
    </main>

    <div class="sidebar-overlay" role="presentation" @click="closeNarrowSidebar" />
  </div>
</template>
