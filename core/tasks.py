from celery import shared_task

from core.feedfetcher import fetch_feeds_impl


@shared_task
def fetch_feeds():
    fetch_feeds_impl()
