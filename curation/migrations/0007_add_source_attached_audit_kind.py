from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("curation", "0006_sourcediscoverystatus_absent_unused_duplicates"),
    ]

    operations = [
        migrations.AlterField(
            model_name="gamehistoryauditlog",
            name="kind",
            field=models.CharField(
                choices=[
                    ("INITIAL_IMPORT", "Initial import from old importer"),
                    ("SOURCE_ATTACHED", "Source attached"),
                    ("FIELD_CHANGE", "Field changed"),
                ],
                max_length=32,
                verbose_name="Kind",
            ),
        ),
    ]
