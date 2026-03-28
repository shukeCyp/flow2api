import asyncio

from src.core.models import Token
from src.services.token_manager import TokenManager


class FakeDB:
    def __init__(self, tokens, delay=0, fail_after_calls=None):
        self.tokens = list(tokens)
        self.delay = delay
        self.fail_after_calls = fail_after_calls
        self.get_active_tokens_calls = 0
        self.update_calls = []

    async def get_active_tokens(self):
        self.get_active_tokens_calls += 1
        if (
            self.fail_after_calls is not None
            and self.get_active_tokens_calls > self.fail_after_calls
        ):
            raise RuntimeError("database unavailable")
        if self.delay:
            await asyncio.sleep(self.delay)
        return [token.model_copy(deep=True) for token in self.tokens if token.is_active]

    async def update_token(self, token_id, **kwargs):
        self.update_calls.append((token_id, kwargs))
        for token in self.tokens:
            if token.id == token_id:
                for key, value in kwargs.items():
                    setattr(token, key, value)
                return
        raise AssertionError(f"Token {token_id} not found")

    async def reset_error_count(self, token_id):
        return None


def _token(token_id=1, is_active=True):
    return Token(
        id=token_id,
        st=f"st-{token_id}",
        at=f"at-{token_id}",
        email=f"user{token_id}@example.com",
        is_active=is_active,
    )


def test_get_active_tokens_uses_ttl_cache(monkeypatch):
    clock = {"now": 100.0}
    db = FakeDB([_token(1)])
    manager = TokenManager(db, flow_client=None)

    monkeypatch.setattr("src.services.token_manager.time.monotonic", lambda: clock["now"])

    first = asyncio.run(manager.get_active_tokens())
    second = asyncio.run(manager.get_active_tokens())
    clock["now"] += manager._active_tokens_cache_ttl + 0.01
    third = asyncio.run(manager.get_active_tokens())

    assert len(first) == 1
    assert len(second) == 1
    assert len(third) == 1
    assert db.get_active_tokens_calls == 2


def test_get_active_tokens_coalesces_concurrent_cache_miss():
    db = FakeDB([_token(1), _token(2)], delay=0.01)
    manager = TokenManager(db, flow_client=None)
    manager._active_tokens_cache_ttl = 60

    async def run():
        return await asyncio.gather(
            manager.get_active_tokens(),
            manager.get_active_tokens(),
            manager.get_active_tokens(),
        )

    results = asyncio.run(run())

    assert db.get_active_tokens_calls == 1
    assert [len(tokens) for tokens in results] == [2, 2, 2]


def test_disable_token_invalidates_active_token_cache():
    db = FakeDB([_token(1, is_active=True)])
    manager = TokenManager(db, flow_client=None)
    manager._active_tokens_cache_ttl = 60

    first = asyncio.run(manager.get_active_tokens())
    asyncio.run(manager.disable_token(1))
    second = asyncio.run(manager.get_active_tokens())

    assert len(first) == 1
    assert second == []
    assert db.get_active_tokens_calls == 2
    assert db.update_calls == [(1, {"is_active": False})]


def test_get_active_tokens_reuses_stale_cache_when_refresh_fails(monkeypatch):
    clock = {"now": 100.0}
    db = FakeDB([_token(1)], fail_after_calls=1)
    manager = TokenManager(db, flow_client=None)
    manager._active_tokens_cache_ttl = 0.5
    manager._active_tokens_stale_retry_delay = 3.0

    monkeypatch.setattr("src.services.token_manager.time.monotonic", lambda: clock["now"])

    first = asyncio.run(manager.get_active_tokens())
    clock["now"] += manager._active_tokens_cache_ttl + 0.01
    second = asyncio.run(manager.get_active_tokens())

    assert len(first) == 1
    assert len(second) == 1
    assert db.get_active_tokens_calls == 2
    assert manager._active_tokens_cache_expires_at == clock["now"] + 3.0
