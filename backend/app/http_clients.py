"""Lifespan-owned pools for trusted API endpoints, never arbitrary page fetching."""
from __future__ import annotations

import asyncio
import hashlib
import weakref
from contextlib import asynccontextmanager

import httpx


class HTTPPool:
    def __init__(self):
        self.clients = {}
        self.leases = 1

    def get(self, settings, purpose, timeout_seconds, trust_env):
        # Separate credentials and providers. Never log this registry or retain
        # raw credentials in keys; each request supplies its own authorization.
        origin = settings.llm_base_url if purpose == "llm" else {
            "search:searxng": settings.searxng_url,
            "search:tavily": "https://api.tavily.com",
            "search:serper": "https://google.serper.dev",
        }.get(purpose, purpose)
        secret = settings.llm_api_key if purpose == "llm" else {
            "search:tavily": settings.tavily_api_key,
            "search:serper": settings.serper_api_key,
        }.get(purpose, "")
        key = (purpose, origin, hashlib.sha256(secret.encode()).hexdigest(), bool(trust_env))
        if key not in self.clients:
            self.clients[key] = httpx.AsyncClient(
                timeout=httpx.Timeout(timeout_seconds, connect=5), follow_redirects=False,
                trust_env=trust_env,
                limits=httpx.Limits(max_connections=8, max_keepalive_connections=4,
                                   keepalive_expiry=20))
        return self.clients[key]

    async def close(self):
        clients, self.clients = list(self.clients.values()), {}
        await asyncio.gather(*(client.aclose() for client in clients))


_pools = weakref.WeakKeyDictionary()


def start_http_pool():
    loop = asyncio.get_running_loop()
    pool = _pools.get(loop)
    if pool is None:
        pool = _pools[loop] = HTTPPool()
    else:
        pool.leases += 1
    return pool


async def stop_http_pool(pool):
    pool.leases -= 1
    if pool.leases:
        return
    loop = asyncio.get_running_loop()
    if _pools.get(loop) is pool:
        del _pools[loop]
    await pool.close()


@asynccontextmanager
async def managed_client(settings, purpose, *, timeout_seconds, trust_env=False):
    """Injected test clients stay caller-owned; stand-alone calls still close."""
    pool = _pools.get(asyncio.get_running_loop())
    if pool is not None:
        yield pool.get(settings, purpose, timeout_seconds, trust_env)
    else:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds, connect=5),
                                     follow_redirects=False, trust_env=trust_env) as client:
            yield client
