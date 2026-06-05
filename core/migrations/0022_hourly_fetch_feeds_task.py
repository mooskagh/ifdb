import json

from django.db import migrations


def create_hourly_fetch_feeds_task(apps, schema_editor):
    IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    schedule, _ = IntervalSchedule.objects.get_or_create(
        every=1,
        period="hours",
    )
    PeriodicTask.objects.update_or_create(
        name="Fetch feeds",
        defaults={
            "interval": schedule,
            "task": "core.tasks.fetch_feeds",
            "args": json.dumps([]),
            "kwargs": json.dumps({}),
        },
    )


def delete_hourly_fetch_feeds_task(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name="Fetch feeds").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0021_delete_taskqueueelement"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [
        migrations.RunPython(
            create_hourly_fetch_feeds_task,
            delete_hourly_fetch_feeds_task,
        ),
    ]
