import asyncio

from src.core.models import Token
from src.services.token_manager import TokenManager


class _FakeDB:
    def __init__(self):
        self.token = Token(
            id=1,
            st="st",
            at="at",
            email="user@example.com",
            current_project_id=None,
            current_project_name=None,
        )
        self.projects = []
        self.project_id_seq = 0

    async def get_token(self, token_id: int):
        return self.token.model_copy(deep=True) if token_id == 1 else None

    async def get_projects_by_token(self, token_id: int):
        if token_id != 1:
            return []
        return [project.model_copy(deep=True) for project in self.projects]

    async def add_project(self, project):
        self.project_id_seq += 1
        stored = project.model_copy(deep=True)
        stored.id = self.project_id_seq
        self.projects.append(stored)
        return stored.id

    async def update_token(self, token_id: int, **kwargs):
        if token_id != 1:
            return
        for key, value in kwargs.items():
            setattr(self.token, key, value)


class _FakeFlowClient:
    def __init__(self):
        self.create_calls = 0

    async def create_project(self, st: str, title: str) -> str:
        self.create_calls += 1
        return f"project-{self.create_calls}"


def _run_in_new_loop(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_token_manager_project_pool_is_safe_across_event_loops():
    db = _FakeDB()
    flow_client = _FakeFlowClient()
    manager = TokenManager(db, flow_client)

    first_project = _run_in_new_loop(manager.ensure_project_exists(1))
    second_project = _run_in_new_loop(manager.ensure_project_exists(1))

    assert first_project == "project-1"
    assert second_project == "project-2"
    assert flow_client.create_calls == 4
    assert len(db.projects) == 4
