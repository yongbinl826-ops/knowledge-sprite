"""Offline bounded compressed metadata transport; never contacts a live site."""
import asyncio
import gzip
import hashlib
import zlib
from dataclasses import replace

import httpx
import pytest

from backend.app.fetcher import FetcherConfig, FetchStopped, NETWORK_OBSERVER, PinnedHTTPClient


URL = "https://www.bilibili.com/video/BV1TESTONLY00"
ADDRESS = "9.9.9.9"
REAL_ASYNC_CLIENT = httpx.AsyncClient


class Chunks(httpx.AsyncByteStream):
    def __init__(self, values):
        self.values = values
        self.closed = False
        self.reads = 0

    async def __aiter__(self):
        for pause, chunk in self.values:
            await asyncio.sleep(pause)
            self.reads += 1
            yield chunk

    async def aclose(self):
        self.closed = True


def install(monkeypatch, stream, encoding, *, length=None, status=200):
    from backend.app import fetcher as module
    requests = []

    async def handler(request):
        requests.append(request)
        assert request.method == "GET"
        assert request.url.host == ADDRESS
        assert request.headers["host"] == "www.bilibili.com"
        assert request.extensions["sni_hostname"] == "www.bilibili.com"
        assert request.headers["accept-encoding"] == "identity"
        assert "cookie" not in request.headers and "authorization" not in request.headers
        headers = {"content-type": "text/html; charset=utf-8", "content-encoding": encoding}
        if length is not None:
            headers["content-length"] = str(length)
        return httpx.Response(status, headers=headers, stream=stream)

    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        # Default TLS certificate verification is retained; no verify=False.
        assert kwargs.get("verify", True) is not False
        return REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(module.httpx, "AsyncClient", client)
    return requests


def encode(body, encoding):
    return gzip.compress(body, mtime=0) if encoding == "gzip" else zlib.compress(body)


def config(**kwargs):
    return replace(FetcherConfig(phased_timeouts=True, timeout_seconds=1,
        body_idle_timeout_seconds=0.1, body_timeout_cap_seconds=1,
        body_min_bytes_per_second=1000), **kwargs)


async def request(cap=4096, **kwargs):
    return await PinnedHTTPClient(config(**kwargs)).request(URL, [ADDRESS], cap)


@pytest.fixture
def traces():
    values = []
    token = NETWORK_OBSERVER.set({"transport_trace": values.append})
    try:
        yield values
    finally:
        NETWORK_OBSERVER.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("encoding", ["gzip", "deflate"])
@pytest.mark.parametrize("phased", [False, True])
async def test_decodes_incremental_body_and_records_wire_and_entity_hashes(monkeypatch, traces, encoding, phased):
    body = ("<html><title>课程</title><p>Python 列表</p></html>" * 5).encode()
    packed = encode(body, encoding)
    stream = Chunks([(0, packed[i:i + 7]) for i in range(0, len(packed), 7)])
    requests = install(monkeypatch, stream, encoding, length=len(packed))
    result = await request(phased_timeouts=phased)
    assert result.body == body and result.url == URL and stream.closed and len(requests) == 1
    assert "content-encoding" not in result.headers
    assert result.headers["content-length"] == str(len(body))
    assert result.headers["content-type"] == "text/html; charset=utf-8"
    row = traces[0]
    assert row["content_encoding"] == encoding and row["body_complete"]
    assert row["bytes_read"] == row["encoded_bytes_read"] == len(packed)
    assert row["decoded_bytes_read"] == len(body)
    assert row["body_sha256"] == hashlib.sha256(body).hexdigest()
    assert row["encoded_body_sha256"] == hashlib.sha256(packed).hexdigest()
    assert row["body_sha256_basis"] == "decoded_entity_prefix"
    assert row["encoded_body_sha256_basis"] == "wire_body_prefix"


@pytest.mark.asyncio
@pytest.mark.parametrize("encoding", ["gzip", "deflate"])
async def test_decoded_budget_accepts_exact_limit_and_rejects_zip_bomb_with_one_extra_byte(monkeypatch, traces, encoding):
    cap = 1024
    packed = encode(b"x" * cap, encoding)
    stream = Chunks([(0, packed)])
    install(monkeypatch, stream, encoding)
    assert (await request(cap)).body == b"x" * cap
    bomb = encode(b"x" * 1_000_000, encoding)
    assert len(bomb) <= cap
    stream = Chunks([(0, bomb)])
    install(monkeypatch, stream, encoding)
    with pytest.raises(FetchStopped) as caught:
        await request(cap)
    assert caught.value.status == "too_large" and stream.closed
    row = traces[-1]
    assert row["encoded_bytes_read"] == len(bomb)
    assert row["decoded_bytes_read"] == cap + 1
    assert row["body_complete"] is False and row["status"] == "failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("declared", [True, False])
async def test_encoded_budget_is_independent_of_decoded_size(monkeypatch, traces, declared):
    body = bytes(range(256))
    packed = encode(body, "gzip")
    assert len(packed) > len(body)
    stream = Chunks([(0, packed)])
    install(monkeypatch, stream, "gzip", length=len(packed) if declared else None)
    with pytest.raises(FetchStopped) as caught:
        await request(len(body))
    assert caught.value.status == "too_large" and stream.closed
    assert traces[0]["encoded_bytes_read"] == (0 if declared else len(packed))
    assert traces[0]["decoded_bytes_read"] == 0 and not traces[0]["body_complete"]


@pytest.mark.asyncio
@pytest.mark.parametrize("encoding", ["gzip", "deflate"])
@pytest.mark.parametrize("damage", ["truncated", "checksum", "garbage", "empty"])
async def test_rejects_truncated_corrupt_and_trailing_data(monkeypatch, traces, encoding, damage):
    packed = encode(b"<html>real public metadata</html>", encoding)
    if damage == "truncated":
        packed = packed[:-1]
    elif damage == "checksum":
        packed = packed[:-1] + bytes([packed[-1] ^ 255])
    elif damage == "garbage":
        packed += b"not another valid stream"
    else:
        packed = b""
    stream = Chunks([(0, packed)])
    install(monkeypatch, stream, encoding)
    with pytest.raises(FetchStopped) as caught:
        await request()
    assert caught.value.status == "invalid_encoding" and stream.closed
    assert traces[0]["status"] == "failed" and not traces[0]["body_complete"]


@pytest.mark.asyncio
@pytest.mark.parametrize("split", [False, True])
async def test_all_gzip_members_are_decoded_and_count_toward_the_same_cap(monkeypatch, traces, split):
    chunks = [encode(b"first", "gzip"), encode(b"second", "gzip")]
    stream = Chunks([(0, chunk) for chunk in chunks] if split else [(0, b"".join(chunks))])
    install(monkeypatch, stream, "gzip")
    assert (await request()).body == b"firstsecond"
    assert traces[0]["encoded_bytes_read"] == sum(map(len, chunks))
    assert traces[0]["decoded_bytes_read"] == 11


@pytest.mark.asyncio
async def test_concatenated_gzip_members_cannot_reset_decoded_byte_budget(monkeypatch, traces):
    packed = encode(b"x" * 800, "gzip") + encode(b"y" * 800, "gzip")
    stream = Chunks([(0, packed)])
    install(monkeypatch, stream, "gzip")
    with pytest.raises(FetchStopped) as caught:
        await request(1024)
    assert caught.value.status == "too_large" and stream.closed
    assert traces[0]["decoded_bytes_read"] == 1025


@pytest.mark.asyncio
@pytest.mark.parametrize("encoding", ["br", "zstd", "gzip, deflate"])
async def test_unknown_or_stacked_encoding_is_explicitly_unsupported(monkeypatch, traces, encoding):
    stream = Chunks([(0, b"must not be read")])
    install(monkeypatch, stream, encoding)
    with pytest.raises(FetchStopped) as caught:
        await request()
    assert caught.value.status == "unsupported_encoding" and stream.closed
    assert stream.reads == 0 and traces[0]["encoded_bytes_read"] == 0
    assert traces[0]["content_encoding"] == encoding


@pytest.mark.asyncio
async def test_block_status_is_returned_without_reading_or_decoding_body(monkeypatch, traces):
    stream = Chunks([(0, b"must not be read")])
    requests = install(monkeypatch, stream, "br", status=403)
    result = await request()
    assert result.status_code == 403 and result.body == b"" and len(requests) == 1
    assert stream.closed and stream.reads == 0
    assert traces[0]["body_read"] == "not_requested_status"


@pytest.mark.asyncio
async def test_compressed_idle_timeout_keeps_partial_wire_and_entity_evidence(monkeypatch, traces):
    packed = encode(b"x" * 1000, "gzip")
    stream = Chunks([(0, packed[:-8]), (1, packed[-8:])])
    install(monkeypatch, stream, "gzip")
    with pytest.raises(TimeoutError):
        await request(body_idle_timeout_seconds=0.01)
    row = traces[0]
    assert stream.closed and row["timeout_kind"] == "body_idle"
    assert row["encoded_bytes_read"] == len(packed) - 8 and row["decoded_bytes_read"] == 1000
    assert row["body_sha256"] == hashlib.sha256(b"x" * 1000).hexdigest()
    assert not row["body_complete"] and row["partial_body"]


@pytest.mark.asyncio
async def test_cancellation_propagates_and_closes_compressed_stream(monkeypatch, traces):
    packed = encode(b"x" * 1000, "deflate")
    stream = Chunks([(0, packed[:-4]), (1, packed[-4:])])
    install(monkeypatch, stream, "deflate")
    task = asyncio.create_task(request(body_idle_timeout_seconds=1))
    for _ in range(50):
        if traces and traces[0]["encoded_bytes_read"]:
            break
        await asyncio.sleep(0.001)
    assert traces[0]["encoded_bytes_read"]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stream.closed and traces[0]["status"] == "cancelled"
    assert not traces[0]["body_complete"]
