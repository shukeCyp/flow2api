import asyncio
import sqlite3

from src.core.database import Database


class FakeConnection:
    def __init__(self):
        self.closed = False
        self.executed = []

    async def execute(self, query, params=None):
        self.executed.append((query, params))

    async def close(self):
        self.closed = True


def test_connect_creates_missing_parent_directory(monkeypatch, tmp_path):
    db_file = tmp_path / "missing" / "nested" / "flow.db"
    db = Database(str(db_file))
    opened = FakeConnection()

    async def fake_connect(path, timeout):
        assert path == str(db_file.resolve())
        assert db_file.parent.exists()
        return opened

    monkeypatch.setattr("src.core.database.aiosqlite.connect", fake_connect)

    async def run():
        async with db._connect():
            pass

    asyncio.run(run())

    assert opened.closed is True


def test_connect_retries_transient_cantopen(monkeypatch, tmp_path):
    db_file = tmp_path / "data" / "flow.db"
    db = Database(str(db_file))
    db._connect_retry_delay = 0
    attempts = {"count": 0}

    async def fake_connect(path, timeout):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise sqlite3.OperationalError("unable to open database file")
        return FakeConnection()

    monkeypatch.setattr("src.core.database.aiosqlite.connect", fake_connect)

    async def run():
        async with db._connect():
            pass

    asyncio.run(run())

    assert attempts["count"] == 3
