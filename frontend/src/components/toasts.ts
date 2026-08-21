export type ToastTone = 'info' | 'success' | 'warning' | 'danger'

export interface ToastMessage {
  id: string
  tone: ToastTone
  title: string
  message?: string
}
