export function readBrowserStorage(key: string): string | null {
  try {
    return typeof window.localStorage.getItem === 'function'
      ? window.localStorage.getItem(key)
      : null
  } catch {
    return null
  }
}

export function writeBrowserStorage(key: string, value: string): void {
  try {
    if (typeof window.localStorage.setItem === 'function') {
      window.localStorage.setItem(key, value)
    }
  } catch {
    // Browser preferences are best-effort and must never block the application.
  }
}
