import asyncio

from src.core.database import Database
from src.core.models import RequestLog, Task, Token


def test_cleanup_database_removes_logs_and_finished_tasks_only(tmp_path):
    db = Database(str(tmp_path / "flow.db"))

    async def run():
        await db.init_db()
        token_id = await db.add_token(Token(st="st-1", at="at-1", email="user@example.com"))

        await db.create_task(Task(task_id="task-processing", token_id=token_id, model="m", prompt="p", status="processing"))
        await db.create_task(Task(task_id="task-completed", token_id=token_id, model="m", prompt="p", status="completed"))
        await db.add_request_log(
            RequestLog(
                token_id=token_id,
                operation="generate_image",
                request_body="{}",
                response_body="{}",
                status_code=200,
                duration=0.1,
            )
        )

        result = await db.cleanup_database()
        remaining_processing = await db.get_task("task-processing")
        removed_completed = await db.get_task("task-completed")
        logs = await db.get_logs(limit=10)

        return result, remaining_processing, removed_completed, logs

    result, remaining_processing, removed_completed, logs = asyncio.run(run())

    assert result["deleted_logs"] == 1
    assert result["deleted_finished_tasks"] == 1
    assert remaining_processing is not None
    assert removed_completed is None
    assert logs == []
