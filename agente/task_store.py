"""Task Store em memoria: dict[task_id, Task]. Sem persistencia."""

from __future__ import annotations

from task_model import Task, novo_id


class TaskStore:
    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}

    def criar(self, context_id: str | None = None) -> Task:
        task = Task(id=novo_id("task"), context_id=context_id or novo_id("ctx"))
        self._tasks[task.id] = task
        return task

    def obter(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)
