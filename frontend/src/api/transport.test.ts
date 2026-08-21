import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  managementAuth,
  managementNamedDownload,
  ManagementApiError,
  managementRequest,
  managementUpload,
  SseJsonParser,
} from './transport'

async function until(predicate: () => boolean): Promise<void> {
  await vi.waitFor(() => expect(predicate()).toBe(true))
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((accept) => {
    resolve = accept
  })
  return { promise, resolve }
}

afterEach(() => {
  managementAuth.clear()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('management transport', () => {
  it('challenges in memory and retries 401 with a replacement token', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        error: { code: 'invalid_api_key', message: 'Rejected.' },
      }), { status: 401 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ block_types: [] }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }))
    vi.stubGlobal('fetch', fetchMock)

    const request = managementRequest<{ block_types: unknown[] }>('/api/catalog')
    expect(managementAuth.getSnapshot()).toEqual({ open: true, reason: 'required' })
    expect(fetchMock).not.toHaveBeenCalled()

    managementAuth.submit('rejected-token')
    await until(() => managementAuth.getSnapshot().reason === 'invalid')
    managementAuth.submit('accepted-token')

    await expect(request).resolves.toEqual({ block_types: [] })
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(new Headers(fetchMock.mock.calls[0]?.[1]?.headers).get('Authorization'))
      .toBe('Bearer rejected-token')
    expect(new Headers(fetchMock.mock.calls[1]?.[1]?.headers).get('Authorization'))
      .toBe('Bearer accepted-token')
  })

  it('does not let a stale concurrent 401 clear a newer token', async () => {
    const firstFailure = deferred<Response>()
    const secondFailure = deferred<Response>()
    const fetchMock = vi.fn()
      .mockImplementationOnce(() => firstFailure.promise)
      .mockImplementationOnce(() => secondFailure.promise)
      .mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })))
    vi.stubGlobal('fetch', fetchMock)

    const firstRequest = managementRequest<{ ok: boolean }>('/api/catalog')
    const secondRequest = managementRequest<{ ok: boolean }>('/api/readiness')
    managementAuth.submit('old-token')
    await until(() => fetchMock.mock.calls.length === 2)

    firstFailure.resolve(new Response(JSON.stringify({
      error: { code: 'invalid_api_key', message: 'Rejected.' },
    }), { status: 401 }))
    await until(() => managementAuth.getSnapshot().reason === 'invalid')
    managementAuth.submit('new-token')
    await until(() => fetchMock.mock.calls.length === 3)

    secondFailure.resolve(new Response(JSON.stringify({
      error: { code: 'invalid_api_key', message: 'Rejected.' },
    }), { status: 401 }))

    await expect(Promise.all([firstRequest, secondRequest])).resolves.toEqual([
      { ok: true },
      { ok: true },
    ])
    expect(fetchMock).toHaveBeenCalledTimes(4)
    expect(managementAuth.getSnapshot()).toEqual({ open: false, reason: 'required' })
    expect(new Headers(fetchMock.mock.calls[2]?.[1]?.headers).get('Authorization'))
      .toBe('Bearer new-token')
    expect(new Headers(fetchMock.mock.calls[3]?.[1]?.headers).get('Authorization'))
      .toBe('Bearer new-token')
  })

  it('normalizes validation errors and request metadata', async () => {
    managementAuth.submit('management-token')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: {
        code: 'configuration_validation_failed',
        message: 'Configuration failed.',
        validation: {
          valid: false,
          stage: 'mainAgent_save',
          issues: [{
            code: 'contract.field_required',
            scope: 'main_agent',
            owner_id: '',
            owner_name: '',
            path: 'name',
            message: 'Required.',
          }],
        },
      },
    }), {
      status: 422,
      headers: { 'X-Request-ID': 'req-test' },
    })))

    const request = managementRequest('/api/main-agents', {
      method: 'POST',
      body: JSON.stringify({}),
    })

    await expect(request).rejects.toMatchObject<Partial<ManagementApiError>>({
      status: 422,
      code: 'configuration_validation_failed',
      message: 'Configuration failed.',
      requestId: 'req-test',
      validation: {
        valid: false,
        stage: 'mainAgent_save',
        issues: [expect.objectContaining({ path: 'name' })],
      },
    })
  })

  it('returns the server-supplied download filename with the response body', async () => {
    managementAuth.submit('management-token')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('bundle', {
      status: 200,
      headers: {
        'Content-Disposition': 'attachment; filename="portable.agent-shell-config.zip"',
      },
    })))

    const download = await managementNamedDownload('/api/configuration-bundles/export')

    expect(download.filename).toBe('portable.agent-shell-config.zip')
    await expect(download.blob.text()).resolves.toBe('bundle')
  })

  it('uploads a blob with progress and retries after an authentication challenge', async () => {
    class FakeUploadRequest {
      static readonly instances: FakeUploadRequest[] = []

      readonly headers = new Map<string, string>()
      readonly upload = {
        addEventListener: (_type: string, listener: (event: ProgressEvent) => void) => {
          this.progressListener = listener
        },
      }

      status = 0
      statusText = ''
      responseText = ''
      private progressListener: ((event: ProgressEvent) => void) | null = null
      private readonly listeners = new Map<string, () => void>()

      constructor() {
        FakeUploadRequest.instances.push(this)
      }

      open(): void {}

      setRequestHeader(name: string, value: string): void {
        this.headers.set(name, value)
      }

      addEventListener(type: string, listener: () => void): void {
        this.listeners.set(type, listener)
      }

      getAllResponseHeaders(): string {
        return 'Content-Type: application/json\r\n'
      }

      send(body: Blob): void {
        this.progressListener?.({
          lengthComputable: true,
          loaded: body.size,
          total: body.size,
        } as ProgressEvent)
        if (FakeUploadRequest.instances.length === 1) {
          this.status = 401
          this.statusText = 'Unauthorized'
          this.responseText = JSON.stringify({ detail: { code: 'invalid_api_key' } })
        } else {
          this.status = 200
          this.statusText = 'OK'
          this.responseText = JSON.stringify({ path: 'notes/readme.md' })
        }
        this.listeners.get('load')?.()
      }

      abort(): void {
        this.listeners.get('abort')?.()
      }
    }

    vi.stubGlobal('XMLHttpRequest', FakeUploadRequest)
    const progress = vi.fn()
    const upload = managementUpload<{ path: string }>(
      '/api/file-manager/files/upload?path=notes%2Freadme.md',
      new Blob(['hello']),
      { onProgress: progress },
    )
    managementAuth.submit('old-token')
    await until(() => managementAuth.getSnapshot().reason === 'invalid')
    managementAuth.submit('new-token')

    await expect(upload).resolves.toEqual({ path: 'notes/readme.md' })
    expect(FakeUploadRequest.instances).toHaveLength(2)
    expect(FakeUploadRequest.instances[0]?.headers.get('Authorization'))
      .toBe('Bearer old-token')
    expect(FakeUploadRequest.instances[1]?.headers.get('Authorization'))
      .toBe('Bearer new-token')
    expect(progress).toHaveBeenLastCalledWith(5, 5)
  })

  it('parses comments, split CRLF boundaries, and multi-line data blocks', () => {
    const parser = new SseJsonParser()

    expect(parser.push(': connected\r\n\r\ndata: {"type":\r\n')).toEqual([])
    expect(parser.push('data: "settings_changed"}\r\n\r\n')).toEqual([
      { type: 'settings_changed' },
    ])
    expect(parser.push(': keepalive\n\ndata: {"type":"history_changed"}\n\n')).toEqual([
      { type: 'history_changed' },
    ])
  })

  it('assigns stable locale keys to frontend transport failures', async () => {
    managementAuth.submit('management-token')
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('host details')))

    await expect(managementRequest('/api/catalog')).rejects.toMatchObject({
      code: 'network_error',
      messageKey: 'errors.network',
    })

    const parser = new SseJsonParser()
    expect(() => parser.push('data: not-json\n\n')).toThrowError(expect.objectContaining({
      code: 'invalid_event_stream',
      messageKey: 'errors.invalidEventStream',
    }))
  })
})
