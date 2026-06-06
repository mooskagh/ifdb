import json

from django.db import migrations


def create_source_pipeline_tasks(apps, schema_editor):
    IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    five_minutes, _ = IntervalSchedule.objects.get_or_create(
        every=5,
        period="minutes",
    )
    hourly, _ = IntervalSchedule.objects.get_or_create(
        every=1,
        period="hours",
    )
    PeriodicTask.objects.update_or_create(
        name="Discover sources",
        defaults={
            "interval": hourly,
            "task": "curation.tasks.discover_sources",
            "args": json.dumps([]),
            "kwargs": json.dumps({"types": None}),
            "enabled": False,
        },
    )
    PeriodicTask.objects.update_or_create(
        name="Fetch sources",
        defaults={
            "interval": five_minutes,
            "task": "curation.tasks.fetch_sources",
            "args": json.dumps([]),
            "kwargs": json.dumps({"limit": 5}),
            "enabled": False,
        },
    )
    PeriodicTask.objects.update_or_create(
        name="Reconcile sources",
        defaults={
            "interval": five_minutes,
            "task": "curation.tasks.reconcile_sources",
            "args": json.dumps([]),
            "kwargs": json.dumps({}),
            "enabled": False,
        },
    )


def delete_source_pipeline_tasks(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(
        name__in=["Discover sources", "Fetch sources", "Reconcile sources"]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("curation", "0018_llmworkflow_runner_params"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [
        migrations.RunPython(
            create_source_pipeline_tasks,
            delete_source_pipeline_tasks,
        ),
    ]
