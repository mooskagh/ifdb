import json

from django.db import migrations


def create_periodic_fetch_urls_task(apps, schema_editor):
    IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    schedule, _ = IntervalSchedule.objects.get_or_create(
        every=1,
        period="hours",
    )
    PeriodicTask.objects.update_or_create(
        name="Fetch URLs",
        defaults={
            "interval": schedule,
            "task": "games.tasks.fetch_urls",
            "args": json.dumps([]),
            "kwargs": json.dumps({"limit": 10}),
            "enabled": False,
        },
    )


def delete_periodic_fetch_urls_task(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name="Fetch URLs").delete()


class Migration(migrations.Migration):
    dependencies = [
        (
            "games",
            "0038_storedfile_url_failing_since_url_last_attempt_and_more",
        ),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [
        migrations.RunPython(
            create_periodic_fetch_urls_task,
            delete_periodic_fetch_urls_task,
        ),
    ]
