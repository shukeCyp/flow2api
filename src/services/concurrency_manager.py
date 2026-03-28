"""Concurrency manager for token-based rate limiting"""
import asyncio
import threading
import time
from typing import Dict, Optional, Any
from ..core.logger import debug_logger


class ConcurrencyManager:
    """Manages concurrent request limits for each token"""

    def __init__(self):
        """Initialize concurrency manager"""
        # token_id -> max concurrency limit (only stores >0 values, missing means unlimited)
        self._image_limits: Dict[int, int] = {}
        self._video_limits: Dict[int, int] = {}
        # token_id -> current in-flight requests
        self._image_inflight: Dict[int, int] = {}
        self._video_inflight: Dict[int, int] = {}
        self._async_state_guard = threading.Lock()
        self._async_primitives_by_loop: dict[int, dict[str, Any]] = {}

    def _get_async_primitives(self) -> dict[str, Any]:
        """Return loop-local asyncio primitives for the active event loop."""
        loop = asyncio.get_running_loop()
        loop_id = id(loop)
        state = self._async_primitives_by_loop.get(loop_id)
        if state and state["loop"] is loop:
            return state

        with self._async_state_guard:
            stale_loop_ids = [
                existing_loop_id
                for existing_loop_id, existing_state in self._async_primitives_by_loop.items()
                if existing_state["loop"].is_closed()
            ]
            for stale_loop_id in stale_loop_ids:
                self._async_primitives_by_loop.pop(stale_loop_id, None)

            state = self._async_primitives_by_loop.get(loop_id)
            if state and state["loop"] is loop:
                return state

            state = {
                "loop": loop,
                "lock": asyncio.Lock(),
            }
            self._async_primitives_by_loop[loop_id] = state
            return state

    async def initialize(self, tokens: list):
        """
        Initialize concurrency counters from token list

        Args:
            tokens: List of Token objects with image_concurrency and video_concurrency fields
        """
        lock = self._get_async_primitives()["lock"]
        async with lock:
            self._image_limits.clear()
            self._video_limits.clear()

            # 初始化时重置 in-flight，避免重启后带入脏状态
            self._image_inflight.clear()
            self._video_inflight.clear()

            for token in tokens:
                self._image_inflight[token.id] = 0
                self._video_inflight[token.id] = 0

                if token.image_concurrency and token.image_concurrency > 0:
                    self._image_limits[token.id] = token.image_concurrency
                if token.video_concurrency and token.video_concurrency > 0:
                    self._video_limits[token.id] = token.video_concurrency

            debug_logger.log_info(f"Concurrency manager initialized with {len(tokens)} tokens")

    async def can_use_image(self, token_id: int) -> bool:
        """
        Check if token can be used for image generation

        Args:
            token_id: Token ID

        Returns:
            True if token has available image concurrency, False if concurrency is 0
        """
        lock = self._get_async_primitives()["lock"]
        async with lock:
            limit = self._image_limits.get(token_id)
            # Missing limit means unlimited (-1)
            if limit is None:
                return True

            inflight = self._image_inflight.get(token_id, 0)
            if inflight >= limit:
                debug_logger.log_info(
                    f"Token {token_id} image concurrency exhausted (inflight: {inflight}/{limit})"
                )
                return False

            return True

    async def can_use_video(self, token_id: int) -> bool:
        """
        Check if token can be used for video generation

        Args:
            token_id: Token ID

        Returns:
            True if token has available video concurrency, False if concurrency is 0
        """
        lock = self._get_async_primitives()["lock"]
        async with lock:
            limit = self._video_limits.get(token_id)
            # Missing limit means unlimited (-1)
            if limit is None:
                return True

            inflight = self._video_inflight.get(token_id, 0)
            if inflight >= limit:
                debug_logger.log_info(
                    f"Token {token_id} video concurrency exhausted (inflight: {inflight}/{limit})"
                )
                return False

            return True

    async def acquire_image(self, token_id: int) -> bool:
        """
        Acquire image concurrency slot

        Args:
            token_id: Token ID

        Returns:
            True if acquired, False if not available
        """
        lock = self._get_async_primitives()["lock"]
        async with lock:
            limit = self._image_limits.get(token_id)
            inflight = self._image_inflight.get(token_id, 0)

            if limit is not None and inflight >= limit:
                return False

            new_inflight = inflight + 1
            self._image_inflight[token_id] = new_inflight
            if limit is None:
                debug_logger.log_info(f"Token {token_id} acquired image slot (inflight: {new_inflight}, limit: unlimited)")
            else:
                debug_logger.log_info(f"Token {token_id} acquired image slot (inflight: {new_inflight}/{limit})")
            return True

    async def wait_acquire_image(self, token_id: int, timeout_seconds: float) -> tuple[bool, int]:
        """等待获取图片硬并发槽位，避免请求在短暂竞争下直接失败。"""
        wait_started = time.monotonic()
        timeout_seconds = max(1.0, float(timeout_seconds or 1.0))
        deadline = wait_started + timeout_seconds

        while True:
            if await self.acquire_image(token_id):
                waited_ms = int((time.monotonic() - wait_started) * 1000)
                return True, waited_ms

            if time.monotonic() >= deadline:
                waited_ms = int((time.monotonic() - wait_started) * 1000)
                return False, waited_ms

            await asyncio.sleep(0.05)

    async def wait_acquire_video(self, token_id: int, timeout_seconds: float) -> tuple[bool, int]:
        """等待获取视频硬并发槽位，避免请求在短暂竞争下直接失败。"""
        wait_started = time.monotonic()
        timeout_seconds = max(1.0, float(timeout_seconds or 1.0))
        deadline = wait_started + timeout_seconds

        while True:
            if await self.acquire_video(token_id):
                waited_ms = int((time.monotonic() - wait_started) * 1000)
                return True, waited_ms

            if time.monotonic() >= deadline:
                waited_ms = int((time.monotonic() - wait_started) * 1000)
                return False, waited_ms

            await asyncio.sleep(0.05)

    async def acquire_video(self, token_id: int) -> bool:
        """
        Acquire video concurrency slot

        Args:
            token_id: Token ID

        Returns:
            True if acquired, False if not available
        """
        lock = self._get_async_primitives()["lock"]
        async with lock:
            limit = self._video_limits.get(token_id)
            inflight = self._video_inflight.get(token_id, 0)

            if limit is not None and inflight >= limit:
                return False

            new_inflight = inflight + 1
            self._video_inflight[token_id] = new_inflight
            if limit is None:
                debug_logger.log_info(f"Token {token_id} acquired video slot (inflight: {new_inflight}, limit: unlimited)")
            else:
                debug_logger.log_info(f"Token {token_id} acquired video slot (inflight: {new_inflight}/{limit})")
            return True

    async def release_image(self, token_id: int):
        """
        Release image concurrency slot

        Args:
            token_id: Token ID
        """
        lock = self._get_async_primitives()["lock"]
        async with lock:
            inflight = self._image_inflight.get(token_id, 0)
            if inflight <= 0:
                self._image_inflight[token_id] = 0
                debug_logger.log_warning(f"Token {token_id} release_image called with inflight=0")
                return

            new_inflight = inflight - 1
            self._image_inflight[token_id] = new_inflight
            limit = self._image_limits.get(token_id)
            if limit is None:
                debug_logger.log_info(f"Token {token_id} released image slot (inflight: {new_inflight}, limit: unlimited)")
            else:
                debug_logger.log_info(f"Token {token_id} released image slot (inflight: {new_inflight}/{limit})")

    async def release_video(self, token_id: int):
        """
        Release video concurrency slot

        Args:
            token_id: Token ID
        """
        lock = self._get_async_primitives()["lock"]
        async with lock:
            inflight = self._video_inflight.get(token_id, 0)
            if inflight <= 0:
                self._video_inflight[token_id] = 0
                debug_logger.log_warning(f"Token {token_id} release_video called with inflight=0")
                return

            new_inflight = inflight - 1
            self._video_inflight[token_id] = new_inflight
            limit = self._video_limits.get(token_id)
            if limit is None:
                debug_logger.log_info(f"Token {token_id} released video slot (inflight: {new_inflight}, limit: unlimited)")
            else:
                debug_logger.log_info(f"Token {token_id} released video slot (inflight: {new_inflight}/{limit})")

    async def get_image_remaining(self, token_id: int) -> Optional[int]:
        """
        Get remaining image concurrency for token

        Args:
            token_id: Token ID

        Returns:
            Remaining count or None if no limit
        """
        lock = self._get_async_primitives()["lock"]
        async with lock:
            limit = self._image_limits.get(token_id)
            if limit is None:
                return None
            inflight = self._image_inflight.get(token_id, 0)
            return max(0, limit - inflight)

    async def get_video_remaining(self, token_id: int) -> Optional[int]:
        """
        Get remaining video concurrency for token

        Args:
            token_id: Token ID

        Returns:
            Remaining count or None if no limit
        """
        lock = self._get_async_primitives()["lock"]
        async with lock:
            limit = self._video_limits.get(token_id)
            if limit is None:
                return None
            inflight = self._video_inflight.get(token_id, 0)
            return max(0, limit - inflight)

    async def get_image_inflight(self, token_id: int) -> int:
        """Get current in-flight image request count for token"""
        lock = self._get_async_primitives()["lock"]
        async with lock:
            return self._image_inflight.get(token_id, 0)

    async def get_video_inflight(self, token_id: int) -> int:
        """Get current in-flight video request count for token"""
        lock = self._get_async_primitives()["lock"]
        async with lock:
            return self._video_inflight.get(token_id, 0)

    async def reset_token(self, token_id: int, image_concurrency: int = -1, video_concurrency: int = -1):
        """
        Reset concurrency counters for a token

        Args:
            token_id: Token ID
            image_concurrency: New image concurrency limit (-1 for no limit)
            video_concurrency: New video concurrency limit (-1 for no limit)
        """
        async with self._lock:
            if image_concurrency > 0:
                self._image_limits[token_id] = image_concurrency
            elif token_id in self._image_limits:
                del self._image_limits[token_id]

            if video_concurrency > 0:
                self._video_limits[token_id] = video_concurrency
            elif token_id in self._video_limits:
                del self._video_limits[token_id]

            # 重置时确保存在 in-flight 计数字段
            self._image_inflight.setdefault(token_id, 0)
            self._video_inflight.setdefault(token_id, 0)

            debug_logger.log_info(f"Token {token_id} concurrency reset (image: {image_concurrency}, video: {video_concurrency})")
