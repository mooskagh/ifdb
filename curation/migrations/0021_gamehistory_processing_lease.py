from django.db import migrations, models


def rename_in_progress(apps, schema_editor):
    GameHistory = apps.get_model("curation", "GameHistory")
    GameHistory.objects.filter(state="IN_PROGRESS").update(
        state="SCHEDULED_FOR_UPDATE"
    )


def restore_in_progress(apps, schema_editor):
    GameHistory = apps.get_model("curation", "GameHistory")
    GameHistory.objects.filter(state="SCHEDULED_FOR_UPDATE").update(
        state="IN_PROGRESS"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("curation", "0020_editpipeline_seed_defaults"),
    ]

    operations = [
        migrations.AlterField(
            model_name="gamehistory",
            name="state",
            field=models.CharField(
                choices=[
                    ("SETTLED", "Settled"),
                    (
                        "SCHEDULED_FOR_UPDATE",
                        "Scheduled for automatic update",
                    ),
                    ("PROCESSING", "Processing"),
                    ("NEEDS_ATTENTION", "Needs attention"),
                ],
                default="SCHEDULED_FOR_UPDATE",
                max_length=32,
                verbose_name="State",
            ),
        ),
        migrations.AddField(
            model_name="gamehistory",
            name="processing_started_at",
            field=models.DateTimeField(
                blank=True, null=True, verbose_name="Processing started at"
            ),
        ),
        migrations.AddField(
            model_name="gamehistory",
            name="processing_task_id",
            field=models.CharField(
                blank=True,
                max_length=255,
                null=True,
                verbose_name="Processing task id",
            ),
        ),
        migrations.RunPython(rename_in_progress, restore_in_progress),
    ]
