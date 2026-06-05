from celery import shared_task

from .discovery import run_discover
from .fetch import run_fetch
from .reconcile import run_reconcile


@shared_task
def discover_sources(types=None):
    return dict(run_discover(types=types))


@shared_task
def reconcile_sources():
    return [stats.__dict__ for stats in run_reconcile()]


@shared_task
def fetch_sources(limit=5):
    return [stats.__dict__ for stats in run_fetch(limit=limit)]
