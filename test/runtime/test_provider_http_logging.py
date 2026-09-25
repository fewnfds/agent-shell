from __future__ import annotations

import asyncio
import gzip
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import warnings
from zipfile import ZipFile
import zlib

import httpx
import pytest

from agent_shell.provider_http import ProviderHttpClients, ProviderHttpSettings
from agent_shell.provider_http_logging import (
    GoogleObservedTransport,
    ObservedAsyncTransport,
    ObservedSyncTransport,
    ProviderHttpObserver,
    bind_provider_http_context,
)
from agent_shell.storage.database import SQLiteDatabase
from agent_shell.storage.environment import InstanceEnvironmentStore
from agent_shell.storage.file_config import FileConfigRepository
from agent_shell.storage.history_retention import HistoryRetentionStore
from agent_shell.storage.provider_http_logs import ProviderHttpLogStore


def _observer(tmp_path: Path) -> tuple[ProviderHttpObserver, SQLiteDatabase]:
    data_root = tmp_path / "data"
    database = SQLiteDatabase(data_root / "state" / "agent-shell.sqlite3")
    config = FileConfigRepository(data_root)
    store = ProviderHttpLogStore(
        database,
        data_root / "logs" / "provider-http",
        HistoryRetentionStore(config),
    )
    environment = InstanceEnvironmentStore(data_root / "config" / "agent-shell.env")
    return ProviderHttpObserver(store, environment), database


def _bundle(store: ProviderHttpLogStore, item_id: str) -> dict[str, bytes]:
    prepared = store.prepare_download(item_id)
    assert prepared is not None
    path, _filename = prepared
    try:
        with ZipFile(path) as archive:
            return {name: archive.read(name) for name in archive.namelist()}
    finally:
        store.release_download(path)


class _Chunks(httpx.SyncByteStream):
    def __init__(self, *chunks: bytes) -> None:
        self.chunks = chunks

    def __iter__(self):
        yield from self.chunks


class _InterruptedChunks(httpx.SyncByteStream):
    def __iter__(self):
        yield b"data: partial\n\n"
        raise httpx.ReadError("stream dropped")


@pytest.mark.parametrize("encoding", ["gzip", "deflate", "deflate-raw"])
def test_sync_capture_keeps_decoded_response_and_cross_chunk_credential(tmp_path: Path, encoding: str) -> None:
    observer, database = _observer(tmp_path)
    credential = "abc123secret"
    payload = b'{"message":"ok","key":"abc123secret"}'
    encoded = (
        gzip.compress(payload) if encoding == "gzip"
        else zlib.compress(payload, wbits=-zlib.MAX_WBITS if encoding == "deflate-raw" else zlib.MAX_WBITS)
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.read() == b'{"key":"abc123secret"}'
        return httpx.Response(
            429,
            headers={"Content-Encoding": encoding.replace("-raw", ""), "Content-Type": "application/json"},
            stream=_Chunks(encoded[:7], encoded[7:]),
        )

    transport = ObservedSyncTransport(httpx.MockTransport(handler), observer)
    with httpx.Client(transport=transport) as client:
        request = httpx.Request(
            "POST",
            "https://provider.example/v1/chat/completions",
            headers={"Authorization": f"Bearer {credential}"},
            stream=_Chunks(b'{"key":"abc123', b'secret"}'),
        )
        with bind_provider_http_context(request_id="request-from-agent-runtime", run_id="run-1"):
            response = client.send(request)
        assert response.status_code == 429
        assert response.content == payload

    records = observer.store.records()
    assert len(records) == 1
    assert records[0]["level"] == "error"
    assert records[0]["request_id"] == "request-from-agent-runtime"
    bundle = _bundle(observer.store, str(records[0]["id"]))
    metadata = json.loads(bundle["metadata.json"])
    assert metadata["response"]["status"] == 429
    assert metadata["response"]["headers"][0][0].lower() == "content-encoding"
    assert bundle["request.body"] == b'{"key":"[REDACTED]"}'
    assert bundle["response.body"] == b'{"message":"ok","key":"[REDACTED]"}'
    assert credential.encode() not in b"".join(bundle.values())
    asyncio.run(database.close())


def test_async_capture_records_transport_failure_and_decoded_curl_body(tmp_path: Path) -> None:
    observer, database = _observer(tmp_path)

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/fail":
            raise httpx.ConnectError("upstream refused", request=request)
        await request.aread()
        return httpx.Response(
            200,
            headers={"Content-Encoding": "gzip"},
            stream=httpx.ByteStream(b"data: ok\n\n"),
        )

    async def scenario() -> None:
        transport = ObservedAsyncTransport(httpx.MockTransport(handler), observer, already_decoded=True)
        response = await transport.handle_async_request(
            httpx.Request("POST", "https://provider.example/stream", content=b"hello")
        )
        assert b"".join([chunk async for chunk in response.stream]) == b"data: ok\n\n"
        await response.aclose()
        try:
            await transport.handle_async_request(httpx.Request("GET", "https://provider.example/fail"))
        except httpx.ConnectError:
            pass
        else:
            raise AssertionError("connection error must reach the caller")
        await transport.aclose()

    asyncio.run(scenario())
    records = observer.store.records()
    assert len(records) == 2
    by_path = {str(row["url"]).split("/")[-1]: row for row in records}
    success = _bundle(observer.store, str(by_path["stream"]["id"]))
    failure = _bundle(observer.store, str(by_path["fail"]["id"]))
    assert success["response.body"] == b"data: ok\n\n"
    assert b"upstream refused" in failure["transport-error.txt"]
    assert json.loads(failure["metadata.json"])["response"] is None
    asyncio.run(database.close())


def test_read_error_keeps_prefix_and_startup_recovers_active_exchange(tmp_path: Path) -> None:
    observer, database = _observer(tmp_path)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_InterruptedChunks())

    with httpx.Client(transport=ObservedSyncTransport(httpx.MockTransport(handler), observer)) as client:
        with pytest.raises(httpx.ReadError, match="stream dropped"):
            client.get("https://provider.example/stream")

    active = observer.store.begin(
        method="GET", url="https://provider.example/pending", headers=[],
        secrets=(), request_id="request-pending",
    )
    observer.store.append_request(active, b"partial upload")
    recovered = ProviderHttpLogStore(
        database,
        tmp_path / "data" / "logs" / "provider-http",
        HistoryRetentionStore(FileConfigRepository(tmp_path / "data")),
    )
    rows = recovered.records()
    assert {row["state"] for row in rows} == {"read_error", "interrupted"}
    failed = next(row for row in rows if row["state"] == "read_error")
    prefix = _bundle(recovered, str(failed["id"]))
    assert prefix["response.body"] == b"data: partial\n\n"
    assert b"stream dropped" in prefix["transport-error.txt"]
    interrupted = _bundle(recovered, active.id)
    assert interrupted["request.body"] == b"partial upload"
    assert json.loads(interrupted["metadata.json"])["capture_complete"] is False
    asyncio.run(database.close())


@pytest.mark.parametrize("route", ["httpx", "curl_cffi"])
def test_shared_provider_clients_capture_real_sync_and_async_requests(
    tmp_path: Path, route: str,
) -> None:
    observer, database = _observer(tmp_path)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers["Content-Length"])
            assert self.rfile.read(length) == b'{"hello":"world"}'
            encoded = gzip.compress(b"data: hello\n\n")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, _format: str, *_args: object) -> None:
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    clients = ProviderHttpClients(
        ProviderHttpSettings(transport=route, http_version="http1"),
        observer=observer,
    )
    url = f"http://127.0.0.1:{server.server_port}/v1/chat/completions"

    async def scenario() -> None:
        assert clients.sync_client.post(url, content=b'{"hello":"world"}').content == b"data: hello\n\n"
        assert (await clients.async_client.post(url, content=b'{"hello":"world"}')).content == b"data: hello\n\n"
        await clients.aclose()

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            asyncio.run(scenario())
    finally:
        server.shutdown()
        server.server_close()
        thread.join()

    records = observer.store.records()
    assert len(records) == 2
    assert all(row["state"] == "eof" and row["status_code"] == 200 for row in records)
    for row in records:
        bundle = _bundle(observer.store, str(row["id"]))
        assert bundle["request.body"] == b'{"hello":"world"}'
        assert bundle["response.body"] == b"data: hello\n\n"
    asyncio.run(database.close())


@pytest.mark.parametrize("phase", ["begin", "response_headers", "append_response"])
def test_async_cancellation_finishes_capture_after_pending_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str,
) -> None:
    observer, database = _observer(tmp_path)
    release = threading.Event()
    response_closed = False

    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        entered = asyncio.Event()
        original = getattr(observer.store, phase)

        def blocked(*args, **kwargs):
            loop.call_soon_threadsafe(entered.set)
            release.wait()
            return original(*args, **kwargs)

        monkeypatch.setattr(observer.store, phase, blocked)

        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b"data: received\n\n"

            async def aclose(self) -> None:
                nonlocal response_closed
                response_closed = True

        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, stream=Stream())

        async with httpx.AsyncClient(
            transport=ObservedAsyncTransport(httpx.MockTransport(handler), observer)
        ) as client:
            request = asyncio.create_task(client.post("https://provider.example/stream", content=b"request"))
            try:
                await entered.wait()
                request.cancel()
                release.set()
                with pytest.raises(asyncio.CancelledError):
                    await request
            finally:
                release.set()

    try:
        asyncio.run(scenario())
        row, = observer.store.records()
        assert row["state"] == "cancelled"
        assert row["level"] == "warning"
        bundle = _bundle(observer.store, str(row["id"]))
        assert json.loads(bundle["metadata.json"])["capture_complete"] is False
        if phase == "append_response":
            assert bundle["response.body"] == b"data: received\n\n"
        if phase != "begin":
            assert response_closed
    finally:
        release.set()
        asyncio.run(database.close())


def test_google_public_transport_captures_generate_and_stream(tmp_path: Path) -> None:
    from langchain_google_genai import ChatGoogleGenerativeAI

    observer, database = _observer(tmp_path)
    payload = json.dumps({
        "candidates": [{
            "content": {"role": "model", "parts": [{"text": "OK"}]},
            "finishReason": "STOP",
        }],
    }).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            streaming = "streamGenerateContent" in self.path
            self.send_header("Content-Type", "text/event-stream" if streaming else "application/json")
            self.end_headers()
            self.wfile.write(b"data: " + payload + b"\n\n" if streaming else payload)

        def log_message(self, _format: str, *_args: object) -> None:
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    transport = GoogleObservedTransport(observer)
    model = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        api_key="local-mock-only",
        vertexai=False,
        base_url=f"http://127.0.0.1:{server.server_port}",
        client_args={"transport": transport},
    )

    async def stream() -> str:
        chunks = [chunk.text async for chunk in model.astream("hello")]
        return "".join(chunks)

    try:
        assert model.invoke("hello").text == "OK"
        assert asyncio.run(stream()) == "OK"
    finally:
        transport.close()
        asyncio.run(transport.aclose())
        server.shutdown()
        server.server_close()
        thread.join()

    rows = observer.store.records()
    assert len(rows) == 2
    assert all(row["status_code"] == 200 for row in rows)
    assert any("streamGenerateContent" in str(row["url"]) for row in rows)
    assert any(b"data: " in _bundle(observer.store, str(row["id"]))["response.body"] for row in rows)
    asyncio.run(database.close())


def test_google_observed_transport_keeps_environment_proxy_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    observer, database = _observer(tmp_path)
    observed: list[str] = []

    class ProxyHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            observed.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"through proxy")

        def log_message(self, _format: str, *_args: object) -> None:
            return None

    proxy = ThreadingHTTPServer(("127.0.0.1", 0), ProxyHandler)
    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{proxy.server_port}")
    monkeypatch.setenv("http_proxy", f"http://127.0.0.1:{proxy.server_port}")
    for name in ("ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, "")
    transport = GoogleObservedTransport(observer)
    url = "http://provider.example/through-proxy"

    async def async_request() -> None:
        async with httpx.AsyncClient(transport=transport, trust_env=False) as client:
            assert (await client.get(url)).content == b"through proxy"

    try:
        with httpx.Client(transport=transport, trust_env=False) as client:
            assert client.get(url).content == b"through proxy"
        asyncio.run(async_request())
    finally:
        proxy.shutdown()
        proxy.server_close()
        thread.join()

    assert observed == [url, url]
    assert len(observer.store.records()) == 2
    asyncio.run(database.close())
