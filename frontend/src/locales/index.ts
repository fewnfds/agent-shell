import { createI18n } from 'vue-i18n'

import { readBrowserStorage, writeBrowserStorage } from '@/browserStorage'

import { en } from './en'
import { type MessageSchema, zhCN } from './zh-CN'

export type SupportedLocale = 'zh-CN' | 'en' | 'debug'

type DebugMessages<T> = {
  [K in keyof T]: T[K] extends object ? DebugMessages<T[K]> : string
}

function buildDebugMessages<T extends object>(value: T, prefix = ''): DebugMessages<T> {
  return Object.fromEntries(Object.entries(value).map(([key, child]) => {
    const path = prefix ? `${prefix}.${key}` : key
    return [key, child && typeof child === 'object'
      ? buildDebugMessages(child as object, path)
      : debugMessageValue(path, key, prefix)]
  })) as DebugMessages<T>
}

function debugMessageValue(path: string, key: string, prefix: string): string {
  if (path.startsWith('fields.')) {
    return key === 'label' ? (prefix.split('.').at(-1) ?? prefix) : key
  }
  if (path.startsWith('capabilities.') && (key === 'label' || key === 'description')) {
    return prefix.split('.').at(-1) ?? prefix
  }
  return path
}

export const debugMessages = buildDebugMessages(zhCN)

export function messageKeys(value: object, prefix = ''): string[] {
  return Object.entries(value).flatMap(([key, child]) => {
    const path = prefix ? `${prefix}.${key}` : key
    return child && typeof child === 'object' ? messageKeys(child as object, path) : [path]
  }).sort()
}

export function messageValues(value: object): string[] {
  return Object.values(value).flatMap((child) => child && typeof child === 'object'
    ? messageValues(child as object)
    : [String(child)])
}

export function assertLocaleParity(): void {
  const source = messageKeys(zhCN)
  const targets = [messageKeys(en), messageKeys(debugMessages)]
  if (targets.some((target) => source.join('\n') !== target.join('\n'))) {
    throw new Error('Locale message keys are not identical for zh-CN, en, and debug.')
  }
  if ([...messageValues(zhCN), ...messageValues(en), ...messageValues(debugMessages)]
    .some((value) => value.trim() === '')) {
    throw new Error('Locale messages must not be empty.')
  }
}

export function resolveInitialLocale(saved: string | null, browserLanguages: readonly string[]): SupportedLocale {
  if (saved === 'zh-CN' || saved === 'en' || saved === 'debug') return saved
  return browserLanguages.some((value) => value.toLowerCase().startsWith('zh')) ? 'zh-CN' : 'en'
}

export function formattingLocale(value: string): 'zh-CN' | 'en' {
  return value === 'zh-CN' ? 'zh-CN' : 'en'
}

function readSavedLocale(): string | null {
  return readBrowserStorage('agent-shell-locale')
}

assertLocaleParity()

const locale = resolveInitialLocale(
  readSavedLocale(),
  window.navigator.languages,
)
window.document.documentElement.lang = formattingLocale(locale)

export const i18n = createI18n<[MessageSchema], SupportedLocale>({
  legacy: false,
  globalInjection: true,
  locale,
  fallbackLocale: false,
  missingWarn: true,
  fallbackWarn: false,
  messages: {
    'zh-CN': zhCN,
    en,
    debug: debugMessages,
  },
})

export function setLocale(value: SupportedLocale): void {
  i18n.global.locale.value = value
  writeBrowserStorage('agent-shell-locale', value)
  window.document.documentElement.lang = formattingLocale(value)
}
