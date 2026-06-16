from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("curation", "0011_gameedit_previous_canonical_text"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="gamehistory",
            name="priority",
        ),
        migrations.AlterField(
            model_name="gamehistoryauditlog",
            name="field",
            field=models.CharField(
                blank=True,
                choices=[
                    ("AUTO_UPDATES", "Auto-update policy"),
                    ("STATE", "State"),
                    ("CANONICAL_TEXT", "Canonical text"),
                ],
                max_length=32,
                null=True,
                verbose_name="Field",
            ),
        ),
    ]
