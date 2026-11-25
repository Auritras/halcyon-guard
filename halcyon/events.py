"""Server-Sent Events: push live updates to every open dashboard."""
import asyncio
import json
import threading

HEARTBEAT = 15  # seconds


class EventBus:
    def __init__(self):
        self._subs = set()
        self._lock = threading.Lock()

    def publish(self, event: dict) -> None:
        """Safe to call from any thread (endpoints run in a thread pool)."""
        with self._lock:
            subs = list(self._subs)
        for loop, queue in subs:
            try:
                loop.call_soon_threadsafe(self._put, queue, event)
            except RuntimeError:  # loop already closed
                pass

    @staticmethod
    def _put(queue: asyncio.Queue, event: dict) -> None:
        if queue.full():
            queue.get_nowait()
        queue.put_nowait(event)

    async def stream(self, request):
        loop = asyncio.get_running_loop()
        sub = (loop, asyncio.Queue(maxsize=500))
        with self._lock:
            self._subs.add(sub)
        try:
            yield "retry: 2000\n\n"
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(sub[1].get(), HEARTBEAT)
                    yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            with self._lock:
                self._subs.discard(sub)
