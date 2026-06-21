from celery import shared_task

from core.feedfetcher import run_fetch_feeds


@shared_task
def fetch_feeds(limit=5):
    return [stats.__dict__ for stats in run_fetch_feeds(limit=limit)]
