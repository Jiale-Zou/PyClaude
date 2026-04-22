from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable


async def gather_limit(limit: int, coros: list[Callable[[], Awaitable[object]]]) -> list[object]:
    semaphore = asyncio.Semaphore(limit)

    async def _run_one(factory: Callable[[], Awaitable[object]]) -> object:
        async with semaphore:
            return await factory()

    return await asyncio.gather(*[_run_one(coro) for coro in coros])
