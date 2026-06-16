from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("curation", "0024_add_note_audit_field"),
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
                    ("ABANDONED", "Abandoned"),
                ],
                default="SCHEDULED_FOR_UPDATE",
                max_length=32,
                verbose_name="State",
            ),
        ),
        migrations.AlterField(
            model_name="gamehistoryauditlog",
            name="kind",
            field=models.CharField(
                choices=[
                    ("INITIAL_IMPORT", "Initial import from old importer"),
                    ("SOURCE_ATTACHED", "Source attached"),
                    ("SOURCE_DETACHED", "Source detached"),
                    ("GAME_MERGED", "Game merged"),
                    ("FIELD_CHANGE", "Field changed"),
                ],
                max_length=32,
                verbose_name="Kind",
            ),
        ),
    ]
