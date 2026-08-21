import type { JsonPrimitive, ManagementEvent, NamedDownload, ValidationReport } from './types'

type AuthChallengeReason = 'invalid' | 'required'

export interface ManagementAuthSnapshot {
  open: boolean
  reason: AuthChallengeReason
}

type AuthListener = (snapshot: ManagementAuthSnapshot) => void

interface PendingChallenge {
  promise: Promise<string>
  resolve: (token: string) => void
  reject: (error: ManagementAuthCancelledError) => void
}

export class ManagementAuthCancelledError extends Error {
  readonly messageKey = 'errors.authenticationCancelled'

  constructor() {
    super('Management authentication was cancelled.')
    this.name = 'ManagementAuthCancelledError'
  }
}

class ManagementAuthController {
  private token: string | null = null
  private generation = 0
  private pending: PendingChallenge | null = null
  private snapshot: ManagementAuthSnapshot = { open: false, reason: 'required' }
  private readonly listeners = new Set<AuthListener>()

  getSnapshot(): ManagementAuthSnapshot {
    return { ...this.snapshot }
  }

  subscribe(listener: AuthListener): () => void {
    this.listeners.add(listener)
    listener(this.getSnapshot())
    return () => this.listeners.delete(listener)
  }

  clear(): void {
    this.token = null
    this.generation += 1
  }

  credentialGeneration(): number {
    return this.generation
  }

  invalidate(generation: number): boolean {
    if (generation !== this.generation) return false
    this.clear()
    return true
  }

  challenge(reason: AuthChallengeReason = 'required'): Promise<string> {
    if (this.token !== null && reason === 'required') return Promise.resolve(this.token)
    if (reason === 'invalid' && this.token !== null) this.clear()
    if (this.pending === null) {
      let resolve!: (token: string) => void
      let reject!: (error: ManagementAuthCancelledError) => void
      const promise = new Promise<string>((accept, decline) => {
        resolve = accept
        reject = decline
      })
      this.pending = { promise, resolve, reject }
    }
    this.updateSnapshot({ open: true, reason })
    return this.pending.promise
  }

  submit(candidate: string): boolean {
    if (candidate.trim() === '') return false
    const pending = this.pending
    this.pending = null
    this.token = candidate
    this.generation += 1
    this.updateSnapshot({ open: false, reason: 'required' })
    pending?.resolve(candidate)
    return true
  }

  cancel(): void {
    const pending = this.pending
    this.pending = null
    this.clear()
    this.updateSnapshot({ open: false, reason: 'required' })
    pending?.reject(new ManagementAuthCancelledError())
  }

  private updateSnapshot(snapshot: ManagementAuthSnapshot): void {
    this.snapshot = snapshot
    for (const listener of this.listeners) listener(this.getSnapshot())
  }
}

export const managementAuth = new ManagementAuthController()

interface ManagementApiErrorOptions {
  status: number
  code: string
  message: string
  messageKey?: string
  messageArgs?: Record<string, JsonPrimitive>
  requestId?: string
  validation?: ValidationReport
  payload?: unknown
}

export class ManagementApiError extends Error {
  readonly status: number
  readonly code: string
  readonly messageKey: string | undefined
  readonly messageArgs: Record<string, JsonPrimitive> | undefined
  readonly requestId: string | undefined
  readonly validation: ValidationReport | undefined
  readonly payload: unknown

  constructor(options: ManagementApiErrorOptions) {
    super(options.message)
    this.name = 'ManagementApiError'
    this.status = options.status
    this.code = options.code
    this.messageKey = options.messageKey
    this.messageArgs = options.messageArgs
    this.requestId = options.requestId
    this.validation = options.validation
    this.payload = options.payload
  }
}

type QueryValue = boolean | number | string | null | undefined
type QueryParameters = Record<string, QueryValue | readonly QueryValue[]>

export function buildQuery(parameters: QueryParameters = {}): string {
  const search = new URLSearchParams()
  for (const [key, rawValue] of Object.entries(parameters)) {
    const values = Array.isArray(rawValue) ? rawValue : [rawValue]
    for (const value of values) {
      if (value !== '' && value !== null && value !== undefined) {
        search.append(key, String(value))
      }
    }
  }
  const query = search.toString()
  return query ? `?${query}` : ''
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function jsonPrimitiveRecord(value: unknown): Record<string, JsonPrimitive> | undefined {
  if (!isRecord(value)) return undefined
  const entries = Object.entries(value)
  if (entries.some(([, item]) => (
    item !== null && !['boolean', 'number', 'string'].includes(typeof item)
  ))) return undefined
  return Object.fromEntries(entries) as Record<string, JsonPrimitive>
}

function requestIdFrom(response: Response, payload: unknown): string | undefined {
  const header = response.headers.get('X-Request-ID')
  if (header) return header
  return isRecord(payload) && typeof payload.request_id === 'string'
    ? payload.request_id
    : undefined
}

function errorPayload(payload: unknown): unknown {
  if (!isRecord(payload)) return payload
  return payload.detail ?? payload.error ?? payload
}

function errorMessage(payload: unknown, fallback: string): string {
  if (typeof payload === 'string' && payload) return payload
  if (Array.isArray(payload)) {
    const messages = payload
      .map((item) => isRecord(item) && typeof item.msg === 'string' ? item.msg : '')
      .filter(Boolean)
    if (messages.length) return messages.join('\n')
  }
  if (isRecord(payload)) {
    if (typeof payload.message === 'string' && payload.message) return payload.message
    if (typeof payload.message_key === 'string' && payload.message_key) return payload.message_key
  }
  return fallback
}

function validationReport(payload: unknown): ValidationReport | undefined {
  if (!isRecord(payload) || !isRecord(payload.validation)) return undefined
  const report = payload.validation
  if (
    typeof report.valid !== 'boolean'
    || typeof report.stage !== 'string'
    || !Array.isArray(report.issues)
  ) return undefined
  return report as unknown as ValidationReport
}

async function responsePayload(response: Response): Promise<unknown> {
  const text = await response.text()
  if (!text) return null
  try {
    return JSON.parse(text) as unknown
  } catch {
    if (!response.ok) return text
    throw new ManagementApiError({
      status: response.status,
      code: 'invalid_json_response',
      message: 'The server returned an invalid JSON response.',
      messageKey: 'errors.invalidJsonResponse',
      requestId: response.headers.get('X-Request-ID') ?? undefined,
      payload: text,
    })
  }
}

async function parseManagementResponse<T>(response: Response): Promise<T> {
  const payload = await responsePayload(response)
  if (response.ok) return payload as T

  const detail = errorPayload(payload)
  const detailRecord = isRecord(detail) ? detail : undefined
  const messageKey = detailRecord && typeof detailRecord.message_key === 'string'
    ? detailRecord.message_key
    : undefined
  const code = detailRecord && typeof detailRecord.code === 'string'
    ? detailRecord.code
    : 'request_failed'
  const fallback = response.statusText || `HTTP ${response.status}`
  throw new ManagementApiError({
    status: response.status,
    code,
    message: errorMessage(detail, fallback),
    ...(messageKey ? { messageKey } : {}),
    ...(detailRecord?.message_args
      ? { messageArgs: jsonPrimitiveRecord(detailRecord.message_args) }
      : {}),
    ...(requestIdFrom(response, payload)
      ? { requestId: requestIdFrom(response, payload) }
      : {}),
    ...(validationReport(detail) ? { validation: validationReport(detail) } : {}),
    payload,
  })
}

function requiresManagementAuth(path: string): boolean {
  return (path === '/api' || path.startsWith('/api/')) && path !== '/api/health'
}

function abortError(): DOMException {
  return new DOMException('The operation was aborted.', 'AbortError')
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

function waitForToken(
  auth: ManagementAuthController,
  reason: AuthChallengeReason,
  signal: AbortSignal | null | undefined,
): Promise<string> {
  const challenge = auth.challenge(reason)
  if (!signal) return challenge
  if (signal.aborted) return Promise.reject(abortError())
  return new Promise<string>((resolve, reject) => {
    const onAbort = (): void => {
      cleanup()
      reject(abortError())
    }
    const cleanup = (): void => signal.removeEventListener('abort', onAbort)
    signal.addEventListener('abort', onAbort, { once: true })
    challenge.then(
      (token) => {
        cleanup()
        resolve(token)
      },
      (error: unknown) => {
        cleanup()
        reject(error)
      },
    )
  })
}

async function authenticatedFetch(
  path: string,
  init: RequestInit,
  accept: string,
): Promise<Response> {
  const needsAuth = requiresManagementAuth(path)
  let reason: AuthChallengeReason = 'required'
  while (true) {
    if (init.signal?.aborted) throw abortError()
    const headers = new Headers(init.headers)
    headers.set('Accept', accept)
    if (
      init.body !== null
      && init.body !== undefined
      && !(init.body instanceof FormData)
      && !headers.has('Content-Type')
    ) {
      headers.set('Content-Type', 'application/json')
    }
    let requestGeneration = -1
    if (needsAuth) {
      const token = await waitForToken(managementAuth, reason, init.signal)
      requestGeneration = managementAuth.credentialGeneration()
      headers.set('Authorization', `Bearer ${token}`)
    }
    let response: Response
    try {
      response = await fetch(path, { ...init, headers })
    } catch (error: unknown) {
      if (isAbortError(error)) throw error
      throw new ManagementApiError({
        status: 0,
        code: 'network_error',
        message: 'The management request could not reach the server.',
        messageKey: 'errors.network',
      })
    }
    if (needsAuth && (response.status === 401 || response.status === 403)) {
      reason = managementAuth.invalidate(requestGeneration) ? 'invalid' : 'required'
      await response.body?.cancel().catch(() => undefined)
      continue
    }
    return response
  }
}

export async function managementRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await authenticatedFetch(path, init, 'application/json')
  return parseManagementResponse<T>(response)
}

export async function managementDownload(
  path: string,
  init: RequestInit = {},
): Promise<Blob> {
  const response = await authenticatedFetch(path, init, 'application/octet-stream')
  if (!response.ok) await parseManagementResponse<never>(response)
  return response.blob()
}

function downloadFilename(response: Response): string {
  const disposition = response.headers.get('Content-Disposition') ?? ''
  const extended = /(?:^|;)\s*filename\*=UTF-8''([^;]+)/i.exec(disposition)?.[1]
  if (extended) {
    try {
      return decodeURIComponent(extended)
    } catch {
      // Fall through to the plain filename supplied by the same server response.
    }
  }
  const plain = /(?:^|;)\s*filename="([^"]+)"/i.exec(disposition)?.[1]
  if (plain) return plain
  throw new ManagementApiError({
    status: response.status,
    code: 'download_filename_missing',
    message: 'The download response did not include a filename.',
  })
}

export async function managementNamedDownload(
  path: string,
  init: RequestInit = {},
): Promise<NamedDownload> {
  const response = await authenticatedFetch(path, init, 'application/octet-stream')
  if (!response.ok) await parseManagementResponse<never>(response)
  return {
    blob: await response.blob(),
    filename: downloadFilename(response),
  }
}

function uploadResponse(xhr: XMLHttpRequest): Response {
  const headers = new Headers()
  for (const line of xhr.getAllResponseHeaders().trim().split(/\r?\n/)) {
    if (!line) continue
    const separator = line.indexOf(':')
    if (separator > 0) {
      headers.append(line.slice(0, separator).trim(), line.slice(separator + 1).trim())
    }
  }
  return new Response(xhr.responseText, {
    status: xhr.status,
    statusText: xhr.statusText,
    headers,
  })
}

function sendUpload(
  path: string,
  body: Blob,
  token: string,
  signal: AbortSignal | undefined,
  onProgress: ((loaded: number, total: number) => void) | undefined,
): Promise<Response> {
  return new Promise<Response>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    const abort = (): void => xhr.abort()
    const cleanup = (): void => signal?.removeEventListener('abort', abort)
    xhr.open('PUT', path)
    xhr.setRequestHeader('Accept', 'application/json')
    xhr.setRequestHeader('Authorization', `Bearer ${token}`)
    xhr.setRequestHeader('Content-Type', 'application/octet-stream')
    xhr.upload.addEventListener('progress', (event) => {
      onProgress?.(event.loaded, event.lengthComputable ? event.total : body.size)
    })
    xhr.addEventListener('load', () => {
      cleanup()
      resolve(uploadResponse(xhr))
    })
    xhr.addEventListener('error', () => {
      cleanup()
      reject(new ManagementApiError({
        status: 0,
        code: 'network_error',
        message: 'The management request could not reach the server.',
        messageKey: 'errors.network',
      }))
    })
    xhr.addEventListener('abort', () => {
      cleanup()
      reject(abortError())
    })
    if (signal?.aborted) {
      reject(abortError())
      return
    }
    signal?.addEventListener('abort', abort, { once: true })
    xhr.send(body)
  })
}

export async function managementUpload<T>(
  path: string,
  body: Blob,
  options: {
    signal?: AbortSignal
    onProgress?: (loaded: number, total: number) => void
  } = {},
): Promise<T> {
  let reason: AuthChallengeReason = 'required'
  while (true) {
    const token = await waitForToken(managementAuth, reason, options.signal)
    const generation = managementAuth.credentialGeneration()
    const response = await sendUpload(
      path,
      body,
      token,
      options.signal,
      options.onProgress,
    )
    if (response.status === 401 || response.status === 403) {
      reason = managementAuth.invalidate(generation) ? 'invalid' : 'required'
      continue
    }
    return parseManagementResponse<T>(response)
  }
}

function parseSseJsonBlock(block: string): ManagementEvent | null {
  const data = block
    .split(/\r\n|\r|\n/)
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).replace(/^ /, ''))
    .join('\n')
  if (!data) return null
  let event: unknown
  try {
    event = JSON.parse(data) as unknown
  } catch {
    throw new ManagementApiError({
      status: 0,
      code: 'invalid_event_stream',
      message: 'Management SSE data was not valid JSON.',
      messageKey: 'errors.invalidEventStream',
    })
  }
  if (!isRecord(event) || typeof event.type !== 'string') {
    throw new ManagementApiError({
      status: 0,
      code: 'invalid_event_stream',
      message: 'Management SSE data must be a JSON object with a type.',
      messageKey: 'errors.invalidEventStream',
    })
  }
  return event as ManagementEvent
}

export class SseJsonParser {
  private buffer = ''

  push(chunk: string): ManagementEvent[] {
    this.buffer += chunk
    const events: ManagementEvent[] = []
    let boundary = /\r\n\r\n|\n\n|\r\r/.exec(this.buffer)
    while (boundary) {
      const block = this.buffer.slice(0, boundary.index)
      this.buffer = this.buffer.slice(boundary.index + boundary[0].length)
      const event = parseSseJsonBlock(block)
      if (event) events.push(event)
      boundary = /\r\n\r\n|\n\n|\r\r/.exec(this.buffer)
    }
    return events
  }
}

async function streamManagementEventsOnce(
  path: string,
  onEvent: (event: ManagementEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const response = await authenticatedFetch(path, { signal }, 'text/event-stream')
  if (!response.ok) await parseManagementResponse<never>(response)
  if (!response.body) {
    throw new ManagementApiError({
      status: response.status,
      code: 'event_stream_unavailable',
      message: 'The management event stream is unavailable.',
      messageKey: 'errors.eventStreamUnavailable',
    })
  }
  onEvent({ type: 'event_stream_connected' })
  const parser = new SseJsonParser()
  const decoder = new TextDecoder()
  const reader = response.body.getReader()
  try {
    while (!signal.aborted) {
      const chunk = await reader.read()
      if (chunk.done) break
      for (const event of parser.push(decoder.decode(chunk.value, { stream: true }))) {
        onEvent(event)
      }
    }
  } finally {
    reader.releaseLock()
  }
}

function reconnectDelay(signal: AbortSignal, delayMs: number): Promise<void> {
  if (signal.aborted) return Promise.reject(abortError())
  return new Promise((resolve, reject) => {
    const timeoutId = globalThis.setTimeout(() => {
      cleanup()
      resolve()
    }, delayMs)
    const onAbort = (): void => {
      cleanup()
      reject(abortError())
    }
    const cleanup = (): void => {
      globalThis.clearTimeout(timeoutId)
      signal.removeEventListener('abort', onAbort)
    }
    signal.addEventListener('abort', onAbort, { once: true })
  })
}

interface ManagementEventWatchOptions {
  onError?: (error: unknown) => void
  reconnectDelayMs?: number
}

export function watchManagementEvents(
  path: string,
  onEvent: (event: ManagementEvent) => void,
  options: ManagementEventWatchOptions = {},
): () => void {
  const controller = new AbortController()
  const delayMs = options.reconnectDelayMs ?? 1_000
  void (async () => {
    while (!controller.signal.aborted) {
      try {
        await streamManagementEventsOnce(path, onEvent, controller.signal)
      } catch (error: unknown) {
        if (isAbortError(error) || error instanceof ManagementAuthCancelledError) return
        options.onError?.(error)
      }
      try {
        await reconnectDelay(controller.signal, delayMs)
      } catch (error: unknown) {
        if (isAbortError(error)) return
        throw error
      }
    }
  })()
  return () => controller.abort()
}
