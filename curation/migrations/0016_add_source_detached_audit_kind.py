from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("curation", "0015_llmmodel_workflow_trajectory"),
    ]

    operations = [
        migrations.AlterField(
            model_name="gamehistoryauditlog",
            name="kind",
            field=models.CharField(
                choices=[
                    (
                        "INITIAL_IMPORT",
                        "Initial import from old importer",
                    ),
                    ("SOURCE_ATTACHED", "Source attached"),
                    ("SOURCE_DETACHED", "Source detached"),
                    ("FIELD_CHANGE", "Field changed"),
                ],
                max_length=32,
                verbose_name="Kind",
            ),
        ),
    ]
