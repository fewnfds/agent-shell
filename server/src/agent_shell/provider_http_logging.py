from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
import logging
from typing import TYPE_CHECKING, Callable, Iterator, ParamSpec, TypeVar
import zlib

import httpx

from agent_shell.request_context import current_request_id
if TYPE_CHECKING:
    from agent_shell.storage.environment import InstanceEnvironmentStore
    from agent_shell.storage.provider_http_logs import ProviderHttpCapture, ProviderHttpLogStore


_CONTEXT: ContextVar[dict[str, str]] = ContextVar("provider_http_log_context", default={})
_LOGGER = logging.getLogger("agent_shell.provider_http_logging")
_P = ParamSpec("_P")
_T = TypeVar("_T")


async def _capture_io(operation: Callable[_P, _T], *args: _P.args, **kwargs: _P.kwargs) -> _T:
    """Finish an in-flight disk operation before propagating cancellation."""
    task = asyncio.create_task(asyncio.to_thread(operation, *args, **kwargs))
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    result = task.result()
    if cancelled:
        raise asyncio.CancelledError
    return result


@contextmanager
def bind_provider_http_context(**values: str) -> Iterator[None]:
    merged = {**_CONTEXT.get(), **{key: value for key, value in values.items() if value}}
    token = _CONTEXT.set(merged)
    try:
        yield
    finally:
        _CONTEXT.reset(token)


def _credential_values(request: httpx.Request) -> tuple[str, ...]:
    """Known Provider authentication fields in the outgoing request."""
    authorization = request.headers.get("authorization", "")
    bearer = authorization[7:] if authorization.lower().startswith("bearer ") else ""
    return tuple(value for value in (bearer, request.headers.get("x-goog-api-key", "")) if value)


def _headers(headers: httpx.Headers) -> list[tuple[str, str]]:
    return [
        (name.decode("latin-1"), value.decode("latin-1"))
        for name, value in headers.raw
    ]


class _DeflateDecoder:
    """Accept the zlib-wrapped and raw deflate forms supported by HTTPX."""

    def __init__(self) -> None:
        self._decoder = zlib.decompressobj()
        self._first = True

    def decompress(self, chunk: bytes) -> bytes:
        first, self._first = self._first, False
        try:
            return self._decoder.decompress(chunk)
        except zlib.error:
            if not first:
                raise
            self._decoder = zlib.decompressobj(-zlib.MAX_WBITS)
            return self._decoder.decompress(chunk)

    def flush(self) -> bytes:
        return self._decoder.flush()

    @property
    def eof(self) -> bool:
        return self._decoder.eof


class _EntityDecoder:
    def __init__(self, encoding: str, *, already_decoded: bool) -> None:
        self.representation = "decoded HTTP entity body after credential projection"
        self._decoders: list[object] = []
        if already_decoded or not encoding or encoding.lower() == "identity":
            return
        for name in reversed([part.strip().lower() for part in encoding.split(",")]):
            if name == "gzip":
                self._decoders.append(zlib.decompressobj(16 + zlib.MAX_WBITS))
            elif name == "deflate":
                self._decoders.append(_DeflateDecoder())
            elif name == "br":
                import brotli
                self._decoders.append(brotli.Decompressor())
            elif name == "zstd":
                import zstandard
                self._decoders.append(zstandard.ZstdDecompressor().decompressobj())
            else:
                raise ValueError(f"unsupported Content-Encoding: {name}")

    def feed(self, chunk: bytes) -> bytes:
        for decoder in self._decoders:
            if hasattr(decoder, "decompress"):
                chunk = decoder.decompress(chunk)
            else:
                chunk = decoder.process(chunk)
        return chunk

    def finish(self) -> bytes:
        tail = b""
        for decoder in self._decoders:
            if tail:
                tail = decoder.decompress(tail) if hasattr(decoder, "decompress") else decoder.process(tail)
            flush = getattr(decoder, "flush", None)
            if callable(flush):
                tail += flush()
            if hasattr(decoder, "eof") and not decoder.eof:
                raise ValueError("compressed HTTP response ended before its final frame")
        return tail


class ProviderHttpObserver:
    def __init__(self, store: ProviderHttpLogStore, environment: InstanceEnvironmentStore) -> None:
        self.store = store
        self.environment = environment

    def begin(self, request: httpx.Request) -> tuple[ProviderHttpCapture | None, tuple[bytes, ...]]:
        try:
            secrets = self.environment.snapshot().provider_http_secrets(*_credential_values(request))
            context = dict(_CONTEXT.get())
            capture = self.store.begin(
                method=request.method,
                url=str(request.url),
                headers=_headers(request.headers),
                secrets=secrets,
                request_id=context.get("request_id") or current_request_id(),
                context=context,
            )
            return capture, secrets
        except Exception as exc:
            _LOGGER.warning("Provider HTTP capture begin failed: %s", type(exc).__name__)
            return None, ()

    def failure(self, capture: ProviderHttpCapture | None, exc: BaseException) -> None:
        if capture is not None:
            capture.capture_error = type(exc).__name__
        _LOGGER.warning("Provider HTTP capture write failed: %s", type(exc).__name__)

    def request_body(self, capture: ProviderHttpCapture | None, chunk: bytes) -> None:
        if capture is not None and not capture.capture_error:
            try:
                self.store.append_request(capture, chunk)
            except Exception as exc:
                self.failure(capture, exc)

    def finish(self, capture: ProviderHttpCapture | None, state: str, *, error: BaseException | None = None, secrets: tuple[bytes, ...] = ()) -> None:
        if capture is None:
            return
        try:
            detail = self.store._project(f"{type(error).__name__}: {error}", secrets) if error else ""
            self.store.finish(capture, state, error=detail)
        except Exception as exc:
            self.failure(capture, exc)

    def headers(
        self,
        capture: ProviderHttpCapture | None,
        response: httpx.Response,
        *,
        already_decoded: bool,
        secrets: tuple[bytes, ...],
    ) -> _EntityDecoder | None:
        if capture is None:
            return None
        try:
            decoder = _EntityDecoder(
                response.headers.get("content-encoding", ""),
                already_decoded=already_decoded,
            )
        except Exception as exc:
            self.failure(capture, exc)
            decoder = None
        try:
            version = response.extensions.get("http_version", b"")
            if isinstance(version, bytes):
                version = version.decode("ascii", errors="replace")
            self.store.response_headers(
                capture,
                status=response.status_code,
                http_version=str(version),
                headers=_headers(response.headers),
                representation=decoder.representation if decoder else "omitted: content encoding could not be decoded",
                secrets=secrets,
            )
            return decoder
        except Exception as exc:
            self.failure(capture, exc)
            return None


class _SyncRequestStream(httpx.SyncByteStream):
    def __init__(self, inner: httpx.SyncByteStream, observer: ProviderHttpObserver, capture: ProviderHttpCapture | None) -> None:
        self.inner, self.observer, self.capture = inner, observer, capture

    def __iter__(self) -> Iterator[bytes]:
        for chunk in self.inner:
            self.observer.request_body(self.capture, chunk)
            yield chunk

    def close(self) -> None:
        self.inner.close()


class _AsyncRequestStream(httpx.AsyncByteStream):
    def __init__(self, inner: httpx.AsyncByteStream, observer: ProviderHttpObserver, capture: ProviderHttpCapture | None) -> None:
        self.inner, self.observer, self.capture = inner, observer, capture

    async def __aiter__(self):
        async for chunk in self.inner:
            await _capture_io(self.observer.request_body, self.capture, chunk)
            yield chunk

    async def aclose(self) -> None:
        await self.inner.aclose()


class _SyncResponseStream(httpx.SyncByteStream):
    def __init__(self, inner: httpx.SyncByteStream, observer: ProviderHttpObserver, capture: ProviderHttpCapture | None, decoder: _EntityDecoder | None, secrets: tuple[bytes, ...]) -> None:
        self.inner, self.observer, self.capture, self.decoder, self.secrets = inner, observer, capture, decoder, secrets
        self.finished = False

    def _finish(self, state: str, error: BaseException | None = None) -> None:
        if not self.finished:
            self.finished = True
            self.observer.finish(self.capture, state, error=error, secrets=self.secrets)

    def __iter__(self) -> Iterator[bytes]:
        try:
            for chunk in self.inner:
                if self.capture is not None and self.decoder is not None and not self.capture.capture_error:
                    try:
                        self.observer.store.append_response(self.capture, self.decoder.feed(chunk))
                    except Exception as exc:
                        self.observer.failure(self.capture, exc)
                yield chunk
        except BaseException as exc:
            if isinstance(exc, GeneratorExit):
                self._finish("consumer_closed")
            else:
                self._finish("read_error", exc)
            raise
        else:
            if self.capture is not None and self.decoder is not None and not self.capture.capture_error:
                try:
                    self.observer.store.append_response(self.capture, self.decoder.finish())
                except Exception as exc:
                    self.observer.failure(self.capture, exc)
            self._finish("eof")

    def close(self) -> None:
        try:
            self.inner.close()
        finally:
            self._finish("consumer_closed")


class _AsyncResponseStream(httpx.AsyncByteStream):
    def __init__(self, inner: httpx.AsyncByteStream, observer: ProviderHttpObserver, capture: ProviderHttpCapture | None, decoder: _EntityDecoder | None, secrets: tuple[bytes, ...]) -> None:
        self.inner, self.observer, self.capture, self.decoder, self.secrets = inner, observer, capture, decoder, secrets
        self.finished = False

    async def _finish(self, state: str, error: BaseException | None = None) -> None:
        if not self.finished:
            self.finished = True
            await _capture_io(
                self.observer.finish, self.capture, state, error=error, secrets=self.secrets
            )

    async def __aiter__(self):
        try:
            async for chunk in self.inner:
                if self.capture is not None and self.decoder is not None and not self.capture.capture_error:
                    try:
                        await _capture_io(self.observer.store.append_response, self.capture, self.decoder.feed(chunk))
                    except Exception as exc:
                        self.observer.failure(self.capture, exc)
                yield chunk
            if self.capture is not None and self.decoder is not None and not self.capture.capture_error:
                try:
                    await _capture_io(
                        self.observer.store.append_response, self.capture, self.decoder.finish()
                    )
                except Exception as exc:
                    self.observer.failure(self.capture, exc)
        except BaseException as exc:
            if isinstance(exc, GeneratorExit):
                await self._finish("consumer_closed")
            else:
                await self._finish("cancelled" if isinstance(exc, asyncio.CancelledError) else "read_error", exc)
            raise
        else:
            await self._finish("eof")

    async def aclose(self) -> None:
        try:
            await self.inner.aclose()
        finally:
            await self._finish("consumer_closed")


class ObservedSyncTransport(httpx.BaseTransport):
    def __init__(self, inner: httpx.BaseTransport, observer: ProviderHttpObserver, *, already_decoded: bool = False) -> None:
        self.inner, self.observer, self.already_decoded = inner, observer, already_decoded

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        capture, secrets = self.observer.begin(request)
        try:
            content = request.content
        except httpx.RequestNotRead:
            request.stream = _SyncRequestStream(request.stream, self.observer, capture)
        else:
            # Buffered SDK requests may be sent directly from request.content.
            self.observer.request_body(capture, content)
        try:
            response = self.inner.handle_request(request)
        except BaseException as exc:
            self.observer.finish(capture, "transport_error", error=exc, secrets=secrets)
            raise
        decoder = self.observer.headers(capture, response, already_decoded=self.already_decoded, secrets=secrets)
        response.stream = _SyncResponseStream(response.stream, self.observer, capture, decoder, secrets)
        return response

    def close(self) -> None:
        self.inner.close()


class ObservedAsyncTransport(httpx.AsyncBaseTransport):
    def __init__(self, inner: httpx.AsyncBaseTransport, observer: ProviderHttpObserver, *, already_decoded: bool = False) -> None:
        self.inner, self.observer, self.already_decoded = inner, observer, already_decoded

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        capture, secrets = None, ()
        response = None

        def begin() -> None:
            nonlocal capture, secrets
            capture, secrets = self.observer.begin(request)

        try:
            await _capture_io(begin)
            try:
                content = request.content
            except httpx.RequestNotRead:
                request.stream = _AsyncRequestStream(request.stream, self.observer, capture)
            else:
                await _capture_io(self.observer.request_body, capture, content)
            response = await self.inner.handle_async_request(request)
            decoder = await _capture_io(self.observer.headers, capture, response, already_decoded=self.already_decoded, secrets=secrets)
        except BaseException as exc:
            try:
                if response is not None:
                    await response.aclose()
            finally:
                await _capture_io(
                    self.observer.finish, capture,
                    "cancelled" if isinstance(exc, asyncio.CancelledError) else "transport_error",
                    error=exc, secrets=secrets,
                )
            raise
        response.stream = _AsyncResponseStream(response.stream, self.observer, capture, decoder, secrets)
        return response

    async def aclose(self) -> None:
        await self.inner.aclose()


class GoogleObservedTransport(httpx.BaseTransport, httpx.AsyncBaseTransport):
    """Use Google's public client_args while preserving HTTPX environment routing."""

    def __init__(
        self,
        observer: ProviderHttpObserver,
        *,
        sync_client: httpx.Client | None = None,
        async_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._owns_clients = sync_client is None and async_client is None
        if (sync_client is None) != (async_client is None):
            raise ValueError("Google transport requires both clients or neither")
        self._sync_client = sync_client or httpx.Client()
        self._async_client = async_client or httpx.AsyncClient()
        self._sync = ObservedSyncTransport(_SyncClientTransport(self._sync_client), observer)
        self._async = ObservedAsyncTransport(_AsyncClientTransport(self._async_client), observer)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return self._sync.handle_request(request)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self._async.handle_async_request(request)

    def close(self) -> None:
        if self._owns_clients:
            self._sync_client.close()

    async def aclose(self) -> None:
        if self._owns_clients:
            await self._async_client.aclose()


class _SyncClientTransport(httpx.BaseTransport):
    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return self.client.send(request, stream=True)


class _AsyncClientTransport(httpx.AsyncBaseTransport):
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self.client.send(request, stream=True)
