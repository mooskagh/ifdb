from celery import shared_task

from .discovery import run_discover
from .edit import run_edit
from .fetch import run_fetch
from .reconcile import run_reconcile


@shared_task
def discover_sources(types=None, auto_import_new=False, pipeline_id=None):
    provider_stats = []
    discovered = run_discover(
        types=types,
        on_provider_done=provider_stats.append if auto_import_new else None,
    )
    if not auto_import_new:
        return dict(discovered)

    new_ids = [
        source_id for stats in provider_stats for source_id in stats.new_ids
    ]
    if not new_ids:
        return {"discovered": dict(discovered), "auto_import_new": None}

    fetch_stats = []
    for source_id in new_ids:
        fetch_stats.extend(run_fetch(source_id=source_id))

    history_ids = set()

    def collect_orphan_history(_source, _outcome, history):
        if history and history.game_id is None:
            history_ids.add(history.pk)

    reconcile_stats = []
    for source_id in new_ids:
        reconcile_stats.extend(
            run_reconcile(
                source_id=source_id,
                on_source_done=collect_orphan_history,
            )
        )

    edit_stats = [
        run_edit(history_id=history_id, pipeline_id=pipeline_id).__dict__
        for history_id in sorted(history_ids)
    ]
    return {
        "discovered": dict(discovered),
        "auto_import_new": {
            "source_ids": new_ids,
            "fetch": [stats.__dict__ for stats in fetch_stats],
            "reconcile": [stats.__dict__ for stats in reconcile_stats],
            "edit": edit_stats,
        },
    }


@shared_task
def reconcile_sources():
    return [stats.__dict__ for stats in run_reconcile()]


@shared_task
def fetch_sources(limit=5, source_id=None):
    return [
        stats.__dict__ for stats in run_fetch(limit=limit, source_id=source_id)
    ]


@shared_task(bind=True)
def edit_sources(self, limit=5, history_id=None, pipeline_id=None):
    return run_edit(
        limit=limit,
        history_id=history_id,
        pipeline_id=pipeline_id,
        task_id=self.request.id,
    ).__dict__
