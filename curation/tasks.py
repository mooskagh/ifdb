from celery import shared_task

from .discovery import run_discover
from .edit import run_edit
from .fetch import run_fetch
from .reconcile import run_reconcile


@shared_task
def discover_sources(types=None):
    return dict(run_discover(types=types))


@shared_task
def reconcile_sources():
    return [stats.__dict__ for stats in run_reconcile()]


@shared_task
def fetch_sources(limit=5, source_id=None):
    return [
        stats.__dict__ for stats in run_fetch(limit=limit, source_id=source_id)
    ]


@shared_task
def edit_sources(limit=5, history_id=None, pipeline_id=None):
    return run_edit(
        limit=limit, history_id=history_id, pipeline_id=pipeline_id
    ).__dict__
