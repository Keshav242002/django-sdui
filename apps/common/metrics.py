"""
Celery task success/failure counters, wired once via CommonConfig.ready()
(rules.md §2 -- shared cross-cutting logic lives in apps/common, not
duplicated per task).
"""

from celery.signals import task_failure, task_success
from prometheus_client import Counter

CELERY_TASKS = Counter(
    "sdui_celery_tasks_total",
    "Celery task completions by task name and status",
    ["task_name", "status"],
)


def _on_success(sender=None, **kwargs):
    CELERY_TASKS.labels(task_name=sender.name, status="success").inc()


def _on_failure(sender=None, **kwargs):
    CELERY_TASKS.labels(task_name=sender.name, status="failure").inc()


def connect_celery_signals() -> None:
    task_success.connect(_on_success)
    task_failure.connect(_on_failure)
