import asyncio
import threading
from contextlib import asynccontextmanager

from src.core.database import Database
from src.core.models import Token


def _build_token(token_id_hint=1, credits=10):
    return Token(
        st=f"st-{token_id_hint}",
        at=f"at-{token_id_hint}",
        email=f"user{token_id_hint}@example.com",
        name=f"user{token_id_hint}",
        credits=credits,
        is_active=True,
    )


def _create_database(tmp_path):
    db = Database(str(tmp_path / "flow.db"))
    asyncio.run(db.init_db())
    asyncio.run(db.init_config_from_toml({}, is_first_startup=True))
    return db


def _attach_connect_counter(db):
    original_connect = db._connect
    counter = {"count": 0}

    @asynccontextmanager
    async def counting_connect(*args, **kwargs):
        counter["count"] += 1
        async with original_connect(*args, **kwargs) as conn:
            yield conn

    db._connect = counting_connect
    return counter


def test_system_info_stats_uses_short_ttl_cache(monkeypatch, tmp_path):
    db = _create_database(tmp_path)
    asyncio.run(db.add_token(_build_token(1, credits=12)))
    counter = _attach_connect_counter(db)
    clock = {"now": 100.0}

    monkeypatch.setattr("src.core.database.time.monotonic", lambda: clock["now"])

    first = asyncio.run(db.get_system_info_stats())
    second = asyncio.run(db.get_system_info_stats())
    clock["now"] += db._read_cache_ttls["system_info_stats"] + 0.01
    third = asyncio.run(db.get_system_info_stats())

    assert first["total_tokens"] == 1
    assert first["active_tokens"] == 1
    assert first["total_credits"] == 12
    assert second == first
    assert third == first
    assert counter["count"] == 2


def test_tokens_with_stats_cache_invalidates_after_stat_write(tmp_path):
    db = _create_database(tmp_path)
    token_id = asyncio.run(db.add_token(_build_token(1)))
    counter = _attach_connect_counter(db)

    first = asyncio.run(db.get_all_tokens_with_stats())
    second = asyncio.run(db.get_all_tokens_with_stats())
    asyncio.run(db.increment_image_count(token_id))
    third = asyncio.run(db.get_all_tokens_with_stats())

    assert first[0]["image_count"] == 0
    assert second[0]["image_count"] == 0
    assert third[0]["image_count"] == 1
    assert counter["count"] == 3


def test_generation_config_cache_invalidates_after_update(tmp_path):
    db = _create_database(tmp_path)
    counter = _attach_connect_counter(db)

    first = asyncio.run(db.get_generation_config())
    second = asyncio.run(db.get_generation_config())
    asyncio.run(db.update_generation_config(111, 222))
    third = asyncio.run(db.get_generation_config())

    assert first.image_timeout == second.image_timeout
    assert first.video_timeout == second.video_timeout
    assert third.image_timeout == 111
    assert third.video_timeout == 222
    assert counter["count"] == 3


def test_cached_read_is_safe_across_event_loops(tmp_path):
    db = _create_database(tmp_path)
    first_loader_started = threading.Event()
    release_first_loader = threading.Event()
    loader_calls_lock = threading.Lock()
    loader_calls = {"count": 0}
    results = []
    errors = []

    async def loader():
        with loader_calls_lock:
            loader_calls["count"] += 1
            call_number = loader_calls["count"]

        if call_number == 1:
            first_loader_started.set()
            while not release_first_loader.is_set():
                await asyncio.sleep(0.01)

        return {"call_number": call_number}

    def run_cached_read():
        try:
            results.append(asyncio.run(db._cached_read("cross_loop_cache_key", loader)))
        except Exception as exc:  # pragma: no cover - exercised by the old implementation
            errors.append(exc)

    first_thread = threading.Thread(target=run_cached_read)
    second_thread = threading.Thread(target=run_cached_read)

    first_thread.start()
    assert first_loader_started.wait(timeout=2), "first loader did not start in time"
    second_thread.start()
    release_first_loader.set()

    first_thread.join(timeout=2)
    second_thread.join(timeout=2)

    assert not errors
    assert len(results) == 2
