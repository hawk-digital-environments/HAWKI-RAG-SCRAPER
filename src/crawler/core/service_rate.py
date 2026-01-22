import asyncio
import time
from typing import Optional


class RateLimiter:
    """Rate limiter to control request frequency"""

    def __init__(self, max_rpm: int, request_delay: Optional[int] = None):
        self.max_rpm = max_rpm
        self.request_delay = request_delay / 1000 if request_delay else None
        self.min_interval = 60 / max_rpm if not request_delay else None
        self.last_request_time = 0
        self.lock = asyncio.Lock()

    async def acquire(self):
        """Wait until it's safe to make another request"""
        async with self.lock:
            current_time = time.time()

            if self.request_delay:
                time_since_last = current_time - self.last_request_time
                if time_since_last < self.request_delay:
                    await asyncio.sleep(self.request_delay - time_since_last)
            elif self.min_interval:
                time_since_last = current_time - self.last_request_time
                if time_since_last < self.min_interval:
                    await asyncio.sleep(self.min_interval - time_since_last)

            self.last_request_time = time.time()
